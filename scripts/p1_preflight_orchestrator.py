#!/usr/bin/env python3
"""
T2 cache-pressure admission preflight orchestrator (P1, 2026-05-02).

Spins a 1x A100 SXM4 80GB spot pod on RunPod, runs two checks against a
freshly-served vLLM 0.19.1 + Llama-3.1-8B-Instruct, archives results, then
tears the pod down. The teardown lives in a finally block so an exception or
timeout still releases credits.

Checks (per task spec):
  1. Gauge preflight  - vllm:kv_cache_usage_perc exists, gauge type, label
                        set is model_name only, value in [0,1], cadence under
                        a steady 4 RPS load. Backs RFC docs/rfcs/T2-cache-
                        pressure-admission.md.
  2. Harness smoke    - benchmarks/scripts/benchmark_n_tenant_single_model.py
                        runs 7 quiet + 1 flooder for 60s with the new PR #125
                        flags. Verifies the bias-state log fires and summary
                        records all five new flag values.

Hard cost cap $3, wall cap 3000s. 1xA100 SXM 80GB spot is $0.79/hr - 50min
budget = $0.66 ceiling.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

REST_BASE = "https://rest.runpod.io/v1"
WORKTREE = Path(__file__).resolve().parent.parent
RESULTS_GAUGE = WORKTREE / "results" / "p1_gauge_preflight_20260502"
RESULTS_HARNESS = WORKTREE / "results" / "p1_harness_smoke_20260502"
ORCH_LOG = RESULTS_GAUGE / "orchestrator.log"

POD_NAME = "p1-preflight-20260502"
GPU_TYPE_ID = "NVIDIA A100-SXM4-80GB"
IMAGE = "vllm/vllm-openai:v0.19.1"
CONTAINER_DISK_GB = 80
HF_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
VLLM_PORT = 8001

WALL_CAP_S = 3000  # 50 min hard
COST_CAP_USD = 3.00
HOURLY_RATE_FALLBACK = 1.39  # secure ceiling, used if API doesn't return cost


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S', time.gmtime())}Z] {msg}"
    print(line, flush=True)
    try:
        ORCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ORCH_LOG, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


_HTTP_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        api_key = os.environ["RUNPOD_API_KEY"]
        _HTTP_CLIENT = httpx.Client(
            base_url=REST_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _HTTP_CLIENT


def api(method: str, path: str, body: dict | None = None, timeout: int = 30) -> tuple[int, dict | list | str]:
    """REST call. Returns (status, parsed json or raw text)."""
    try:
        resp = _client().request(method, path, json=body, timeout=timeout)
    except httpx.RequestError as exc:
        return -1, f"transport_error: {exc!r}"
    raw = resp.text
    try:
        return resp.status_code, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return resp.status_code, raw


def create_pod(pubkey: str) -> dict:
    """Create the spot A100 pod. Returns pod record on success."""
    # Bake the SSH pubkey via PUBLIC_KEY env (RunPod's standard injection
    # mechanism for OpenSSH server containers; vLLM's image uses pytorch base).
    body = {
        "name": POD_NAME,
        "imageName": IMAGE,
        "gpuTypeIds": [GPU_TYPE_ID],
        "gpuCount": 1,
        "cloudType": "COMMUNITY",  # spot lives on community
        "interruptible": True,  # spot
        "containerDiskInGb": CONTAINER_DISK_GB,
        "ports": ["8001/http", "22/tcp"],
        "env": {
            "PUBLIC_KEY": pubkey,
            "HF_TOKEN": os.environ["HF_TOKEN"],
            "VLLM_LOGGING_LEVEL": "INFO",
        },
        # Override the image entrypoint with the vLLM serve command.
        "dockerEntrypoint": ["sh", "-c"],
        "dockerStartCmd": [
            f"vllm serve {HF_MODEL} "
            f"--gpu-memory-utilization 0.40 "
            f"--max-model-len 4096 "
            f"--port {VLLM_PORT} "
            f"--host 0.0.0.0"
        ],
        "supportPublicIp": True,
    }
    log(f"create_pod request: {json.dumps({k: v for k, v in body.items() if k != 'env'})}")
    status, resp = api("POST", "/pods", body)
    if status not in (200, 201):
        log(f"create FAIL status={status} resp={resp!r}")
        raise RuntimeError(f"pod create failed: status={status}")
    pod = resp if isinstance(resp, dict) else {}
    log(f"create OK id={pod.get('id')} costPerHr=${pod.get('costPerHr')}")
    return pod


def wait_for_running(pod_id: str, timeout_s: int = 600) -> dict:
    """Poll until status=RUNNING and SSH port is mapped."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, resp = api("GET", f"/pods/{pod_id}")
        if status != 200 or not isinstance(resp, dict):
            log(f"poll status={status}")
            time.sleep(10)
            continue
        ds = resp.get("desiredStatus")
        port_map = resp.get("portMappings") or {}
        public_ip = resp.get("publicIp")
        ssh_port = port_map.get("22")
        log(
            f"poll desiredStatus={ds} publicIp={public_ip} ssh_port={ssh_port}"
        )
        if ds == "RUNNING" and ssh_port and public_ip:
            return resp
        time.sleep(10)
    raise TimeoutError(f"pod {pod_id} did not reach RUNNING+SSH within {timeout_s}s")


def ssh_cmd(public_ip: str, ssh_port: int, command: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a command on the pod via SSH. Sandbox-disabled by caller."""
    return subprocess.run(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=20",
            "-o", "ServerAliveInterval=15",
            "-p", str(ssh_port),
            f"root@{public_ip}",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def scp_from(public_ip: str, ssh_port: int, remote: str, local: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "scp",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=20",
            "-r",
            "-P", str(ssh_port),
            f"root@{public_ip}:{remote}",
            local,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def scp_to(public_ip: str, ssh_port: int, local: str, remote: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "scp",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=20",
            "-P", str(ssh_port),
            local,
            f"root@{public_ip}:{remote}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def wait_for_ssh(public_ip: str, ssh_port: int, timeout_s: int = 240) -> None:
    """SSH may need ~30-90s after RUNNING for sshd to be ready."""
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        proc = ssh_cmd(public_ip, ssh_port, "echo ssh_ready", timeout=25)
        if proc.returncode == 0 and "ssh_ready" in proc.stdout:
            log(f"ssh ready after waiting")
            return
        last_err = (proc.stderr or proc.stdout).strip()[:120]
        log(f"ssh not ready yet: {last_err}")
        time.sleep(10)
    raise TimeoutError(f"ssh did not come up within {timeout_s}s; last={last_err!r}")


def wait_for_vllm_health(public_ip: str, ssh_port: int, timeout_s: int = 600) -> None:
    """Poll /health from inside the pod (avoids local network policy)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        proc = ssh_cmd(
            public_ip, ssh_port,
            f"curl -fsS -m 5 http://localhost:{VLLM_PORT}/health -o /dev/null -w '%{{http_code}}'",
            timeout=20,
        )
        code = (proc.stdout or "").strip()
        if proc.returncode == 0 and code == "200":
            log("vllm /health: 200")
            return
        log(f"vllm /health rc={proc.returncode} code={code!r}")
        time.sleep(10)
    raise TimeoutError(f"vllm /health 200 not seen within {timeout_s}s")


def delete_pod(pod_id: str) -> None:
    """Idempotent. Verifies 404 after delete."""
    if not pod_id:
        return
    log(f"delete_pod {pod_id}")
    status, resp = api("DELETE", f"/pods/{pod_id}", timeout=60)
    log(f"delete returned status={status}")
    # verify
    status_v, _ = api("GET", f"/pods/{pod_id}", timeout=20)
    if status_v == 404:
        log(f"pod {pod_id} confirmed terminated (404)")
    else:
        log(f"WARN: post-delete GET status={status_v}; pod may not be torn down")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print pod spec, do not create")
    parser.add_argument("--reuse-pod", help="Existing pod id to reuse (skip create+wait)")
    args = parser.parse_args()

    pubkey = Path("~/.ssh/id_ed25519.pub").expanduser().read_text().strip()
    log(f"pubkey loaded: {pubkey[:50]}...")

    if args.dry_run:
        log("dry-run; skipping pod creation")
        return 0

    RESULTS_GAUGE.mkdir(parents=True, exist_ok=True)
    RESULTS_HARNESS.mkdir(parents=True, exist_ok=True)

    pod_id: str = ""
    public_ip: str = ""
    ssh_port: int = 0
    cost_per_hr: float = HOURLY_RATE_FALLBACK
    t_start = time.time()

    def elapsed_cost() -> float:
        return (time.time() - t_start) / 3600.0 * cost_per_hr

    def alarm_handler(signum, frame):
        log(f"WALL CAP {WALL_CAP_S}s reached; raising")
        raise TimeoutError("wall cap")

    signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(WALL_CAP_S)

    try:
        if args.reuse_pod:
            pod_id = args.reuse_pod
            status, resp = api("GET", f"/pods/{pod_id}")
            if status != 200:
                raise RuntimeError(f"reuse_pod {pod_id} not found")
            pod = resp
        else:
            pod = create_pod(pubkey)
            pod_id = pod["id"]
            cost_per_hr = float(pod.get("costPerHr") or HOURLY_RATE_FALLBACK)
            log(f"pod {pod_id} created, hourly=${cost_per_hr}")
            pod = wait_for_running(pod_id)

        public_ip = pod["publicIp"]
        ssh_port = int(pod["portMappings"]["22"])
        cost_per_hr = float(pod.get("costPerHr") or cost_per_hr)
        log(f"pod up: ip={public_ip} ssh_port={ssh_port} hourly=${cost_per_hr}")
        log(f"elapsed={time.time()-t_start:.0f}s spend=${elapsed_cost():.3f}")

        wait_for_ssh(public_ip, ssh_port)
        log(f"elapsed={time.time()-t_start:.0f}s spend=${elapsed_cost():.3f}")

        # vLLM cold-start: it pulls the model on first run. ~3-5 min on
        # a warm HF cache, ~7-10 min cold. The image command is set at
        # creation, so it should already be running.
        wait_for_vllm_health(public_ip, ssh_port, timeout_s=900)
        log(f"vllm ready; elapsed={time.time()-t_start:.0f}s spend=${elapsed_cost():.3f}")

        if elapsed_cost() > COST_CAP_USD:
            log(f"COST CAP exceeded after engine start; aborting")
            raise RuntimeError("cost cap")

        # === CHECK 1: gauge preflight ===
        log("=== Check 1: gauge preflight ===")
        # 1a-d: scrape /metrics, parse, persist verbatim line.
        proc = ssh_cmd(
            public_ip, ssh_port,
            f"curl -fsS http://localhost:{VLLM_PORT}/metrics > /workspace/metrics_snapshot.txt && "
            f"echo 'metrics_bytes='$(wc -c < /workspace/metrics_snapshot.txt) && "
            f"grep -nE 'vllm:kv_cache_usage_perc' /workspace/metrics_snapshot.txt | head -20",
            timeout=30,
        )
        log(f"check 1a-d ssh rc={proc.returncode}")
        log(f"stdout: {proc.stdout}")
        if proc.stderr:
            log(f"stderr: {proc.stderr[:300]}")

        # Pull the snapshot back.
        scp_from(public_ip, ssh_port, "/workspace/metrics_snapshot.txt",
                 str(RESULTS_GAUGE / "metrics_snapshot.txt"))

        # 1e: cadence test - upload the cadence script and run it on-pod
        # so HTTP overhead is loopback, not the trans-Atlantic round-trip.
        cadence_script = WORKTREE / "scripts" / "p1_gauge_cadence.py"
        scp_to(public_ip, ssh_port, str(cadence_script), "/workspace/p1_gauge_cadence.py")
        log("running cadence test on-pod (60s @ 4 Hz scrape + 4 RPS load)")
        proc = ssh_cmd(
            public_ip, ssh_port,
            f"cd /workspace && python3 p1_gauge_cadence.py --url http://localhost:{VLLM_PORT} "
            f"--model {HF_MODEL} --duration-s 60 --scrape-hz 4 --load-rps 4 "
            f"--out /workspace/cadence.json 2>&1",
            timeout=120,
        )
        log(f"cadence rc={proc.returncode}")
        # First 400 chars of stdout for log
        log(f"cadence stdout (truncated): {proc.stdout[:600]}")
        if proc.stderr:
            log(f"cadence stderr: {proc.stderr[:300]}")

        scp_from(public_ip, ssh_port, "/workspace/cadence.json",
                 str(RESULTS_GAUGE / "cadence.json"))
        log(f"elapsed={time.time()-t_start:.0f}s spend=${elapsed_cost():.3f}")

        # === CHECK 2: harness smoke ===
        log("=== Check 2: harness smoke (#125 flags) ===")
        # Clone the worktree branch on-pod so the harness with PR #125 flags
        # is available. Use the merged main since 9322cdc.
        proc = ssh_cmd(
            public_ip, ssh_port,
            "cd /workspace && rm -rf kvwarden && "
            "git clone --depth 1 --branch main https://github.com/coconut-labs/kvwarden.git && "
            "cd kvwarden && git rev-parse --short HEAD && "
            "python3 -m pip install --quiet aiohttp",
            timeout=120,
        )
        log(f"clone rc={proc.returncode} head={proc.stdout.strip()}")
        if proc.returncode != 0:
            log(f"clone stderr: {proc.stderr[:400]}")

        proc = ssh_cmd(
            public_ip, ssh_port,
            "cd /workspace/kvwarden && mkdir -p results/p1_smoke && "
            f"python3 benchmarks/scripts/benchmark_n_tenant_single_model.py "
            f"--url http://localhost:{VLLM_PORT} "
            f"--model {HF_MODEL} "
            "--flooder-rps 8 "
            "--quiet-rps 1 "
            "--num-quiet 7 "
            "--duration-s 60 "
            "--max-tokens 16 "
            "--timeout-s 30 "
            "--seed 42 "
            "--prefix-overlap 0.7 "
            "--shared-prefix-tokens 256 "
            "--bias-flooder-cost 4.0 "
            "--bias-after-N-reqs 100 "
            "--bias-window-s 30 "
            "--output-dir results/p1_smoke "
            "2>&1 | tee results/p1_smoke/harness.log; "
            "echo HARNESS_RC=${PIPESTATUS[0]}",
            timeout=180,
        )
        log(f"harness ssh rc={proc.returncode}")
        log(f"harness tail: ...{proc.stdout[-1500:]}")
        if proc.stderr:
            log(f"harness stderr: {proc.stderr[:400]}")

        scp_from(public_ip, ssh_port, "/workspace/kvwarden/results/p1_smoke/",
                 str(RESULTS_HARNESS) + "/")
        log(f"elapsed={time.time()-t_start:.0f}s spend=${elapsed_cost():.3f}")

        log("checks complete")
        return 0

    except Exception as exc:
        log(f"ORCHESTRATOR EXCEPTION: {type(exc).__name__}: {exc}")
        return 1
    finally:
        signal.alarm(0)
        log(f"final spend=${elapsed_cost():.3f} elapsed={time.time()-t_start:.0f}s")
        try:
            delete_pod(pod_id)
        except Exception as exc:
            log(f"DELETE EXCEPTION: {exc}; check RunPod console for {pod_id}")


if __name__ == "__main__":
    sys.exit(main())
