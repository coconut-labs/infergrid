"""``infergrid bench reproduce-hero`` — one-liner hero-number replication.

Drives ``benchmarks/scripts/benchmark_n_tenant_single_model.py`` as an
in-process import and prints a side-by-side table vs the published
Gate 2-FAIRNESS preprint v3 numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from rich.console import Console
from rich.table import Table

_HERO_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


@dataclass(frozen=True)
class FlavorSpec:
    """Bench-script args for one flavor (2tenant / n6 / n8)."""

    name: str
    num_quiet: int
    flooder_rps: float
    quiet_rps: float
    default_duration_s: float
    config_hint: str


@dataclass(frozen=True)
class Reference:
    """Published reference numbers for one flavor (pinned; do not re-measure)."""

    num_quiet: int
    solo_p99_ms: float
    fifo_p99_ms: float | None  # None for n6 (we only ran the rate-limit arm)
    tokenbucket_p99_ms: float
    ratio_of_solo: float
    source: str


FLAVORS: dict[str, FlavorSpec] = {
    "2tenant": FlavorSpec("2tenant", 1, 32.0, 1.0, 300.0, "configs/gate2_fairness_token_bucket.yaml"),
    "n6":      FlavorSpec("n6",      5, 32.0, 1.0, 300.0, "configs/gate2_fairness_token_bucket_n6.yaml"),
    "n8":      FlavorSpec("n8",      7, 32.0, 1.0, 300.0, "configs/gate21_fairness_n8.yaml"),
}

# Pinned from docs/launch/gate0_launch_post.md + per-flavor OUTCOMEs.
REFERENCES: dict[str, Reference] = {
    "2tenant": Reference(1, 53.9, 1585.0, 61.5, 1.14, "results/gate2_preprint_v3/"),
    "n6":      Reference(5, 53.9, None,   61.0, 1.13, "results/gate2_n6_v3/"),
    "n8":      Reference(7, 48.1, 59.0,   50.4, 1.05, "results/gate21_n8_20260421/"),
}


def _fmt_ms(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} ms" if v >= 1000 else f"{v:.1f} ms"


def _delta_badge(user: float, reference: float) -> str:
    """Rich-markup badge: green ≤15%, yellow ≤50%, red beyond."""
    if reference <= 0:
        return "[dim]n/a[/dim]"
    pct = (user - reference) / reference * 100
    sign = "+" if pct >= 0 else "−"
    mag = abs(pct)
    color = "green" if mag <= 15 else "yellow" if mag <= 50 else "red"
    return f"[{color}]{sign}{mag:.0f}%[/{color}]"


def render_comparison(
    flavor: str, user_quiet_p99_ms: float, user_flooder_429_rate: float,
    user_solo_p99_ms: float | None, console: Console,
) -> None:
    """Print a side-by-side user-vs-published table."""
    ref = REFERENCES[flavor]
    table = Table(
        title=f"reproduce-hero · flavor={flavor} (num_quiet={ref.num_quiet})",
        header_style="bold", title_justify="left",
    )
    table.add_column("Metric", style="cyan")
    table.add_column("Your box", justify="right")
    table.add_column("Published", justify="right", style="dim")
    table.add_column("Δ", justify="right")
    table.add_row(
        "Quiet p99 TTFT (token-bucket arm)",
        _fmt_ms(user_quiet_p99_ms), _fmt_ms(ref.tokenbucket_p99_ms),
        _delta_badge(user_quiet_p99_ms, ref.tokenbucket_p99_ms),
    )
    if ref.fifo_p99_ms is not None:
        table.add_row(
            "FIFO p99 (reference)", "[dim]—[/dim]",
            _fmt_ms(ref.fifo_p99_ms), "[dim](not measured at runtime)[/dim]",
        )
    if user_solo_p99_ms is not None:
        table.add_row(
            "Solo p99 (baseline)", _fmt_ms(user_solo_p99_ms),
            _fmt_ms(ref.solo_p99_ms), _delta_badge(user_solo_p99_ms, ref.solo_p99_ms),
        )
    table.add_row(
        "Flooder 429 rate",
        f"{user_flooder_429_rate * 100:.1f}%", "[dim]>90%[/dim]",
        "[green]ok[/green]" if user_flooder_429_rate > 0.5 else "[yellow]low[/yellow]",
    )
    console.print(table)
    console.print(
        f"[dim]Source: {ref.source} · see docs/launch/gate0_launch_post.md for methodology.[/dim]"
    )


def _detect_gpu() -> str | None:
    """Best-effort one-line GPU description from nvidia-smi, else None."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        lines = (out.stdout or "").strip().splitlines()
        return lines[0] if lines else None
    except Exception:
        return None


def _split_host_port(base_url: str) -> tuple[str, int]:
    """Parse ``http://host:port`` → ``(host, port)``. Default port 8000."""
    stripped = base_url.split("://", 1)[-1].rstrip("/").split("/", 1)[0]
    if ":" in stripped:
        host, port_s = stripped.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return stripped, 8000
    return stripped, 8000


def _port_listening(host: str, port: int) -> bool:
    """Cheap socket-level liveness probe."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


async def _preflight_server(
    base_url: str, model: str, console: Console
) -> tuple[bool, str | None]:
    """Verify /health + /v1/models and that the hero model is loaded."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(f"{base_url}/health") as r:
                if r.status != 200:
                    body = (await r.text())[:200]
                    return False, (
                        f"{base_url}/health HTTP {r.status} ({body!r}). First call is "
                        "503 while vLLM JIT-compiles (30-90s for 8B on A100)."
                    )
            async with s.get(f"{base_url}/v1/models") as r:
                if r.status != 200:
                    return False, (
                        f"{base_url}/v1/models HTTP {r.status}. Is this an InferGrid server?"
                    )
                payload = await r.json()
    except aiohttp.ClientConnectorError:
        _, port = _split_host_port(base_url)
        return False, (
            f"Could not connect to {base_url}. Start the server in another terminal:\n"
            f"  infergrid serve --config configs/gate2_fairness_token_bucket.yaml --port {port}"
        )
    except asyncio.TimeoutError:
        return False, f"{base_url} timed out after 5s. Is the server overloaded?"
    except Exception as exc:
        return False, f"Unexpected error probing {base_url}: {exc}"
    ids = {m.get("id") for m in payload.get("data", [])}
    if model not in ids and not any(model.split("/")[-1] in str(i) for i in ids):
        return False, (
            f"Model {model!r} not found in /v1/models (got {sorted(ids)!r}). "
            "Point --config at a YAML that includes this model."
        )
    return True, None


def _import_bench_module() -> Any:
    """Import the bench script from the repo checkout."""
    script_dir = Path(__file__).resolve().parents[3] / "benchmarks" / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        import benchmark_n_tenant_single_model as bench  # type: ignore[import-not-found]
        return bench
    except ImportError as exc:
        raise RuntimeError(
            "reproduce-hero requires a repo checkout (benchmark_n_tenant_single_model "
            "not importable). Clone https://github.com/coconut-labs/infergrid."
        ) from exc


def _count_429s(csv_path: Path) -> tuple[int, int]:
    """Return ``(n_429, n_total)`` from a tenant CSV. Missing file → (0, 0)."""
    if not csv_path.exists():
        return (0, 0)
    n_429 = n_total = 0
    with open(csv_path, newline="") as fh:
        for row in csv.DictReader(fh):
            n_total += 1
            err = row.get("error", "") or ""
            if err.startswith("HTTP 429") or "429" in err.split(":", 1)[0]:
                n_429 += 1
    return (n_429, n_total)


def _flooder_rate(output_dir: Path) -> float:
    """HTTP 429 ratio over total flooder requests (0 if missing)."""
    n_429, n_total = _count_429s(output_dir / "tenant_flooder.csv")
    return (n_429 / n_total) if n_total else 0.0


def _load_summary(output_dir: Path) -> dict[str, Any]:
    """Load ``summary.json`` written by the bench, or raise."""
    path = output_dir / "summary.json"
    if not path.exists():
        raise RuntimeError(
            f"Bench produced no summary.json at {path} — did it fail mid-run? "
            f"Check {output_dir}/tenant_*.csv for partial output."
        )
    with open(path) as fh:
        return json.load(fh)


def _build_report(
    flavor: FlavorSpec, summary: dict[str, Any], flooder_429_rate: float,
    base_url: str, duration_s: float, gpu: str | None,
    started_at: str, finished_at: str,
) -> dict[str, Any]:
    """Assemble the JSON report written alongside the bench artifacts."""
    ref = REFERENCES[flavor.name]
    qa = summary.get("quiet_aggregate", {}) or {}
    flood = summary.get("flooder", {}) or {}
    return {
        "schema_version": 1, "flavor": flavor.name, "model": _HERO_MODEL,
        "base_url": base_url, "duration_s": duration_s, "gpu": gpu,
        "started_at_utc": started_at, "finished_at_utc": finished_at,
        "bench_args": {"flooder_rps": flavor.flooder_rps, "quiet_rps": flavor.quiet_rps,
                       "num_quiet": flavor.num_quiet},
        "user_result": {
            "quiet_aggregate_p99_ms": qa.get("ttft_p99_ms", -1),
            "quiet_aggregate_count_ok": qa.get("count_ok", 0),
            "flooder_p99_ms": flood.get("ttft_p99_ms", -1),
            "flooder_429_rate": round(flooder_429_rate, 4),
        },
        "reference": {
            "source": ref.source, "solo_p99_ms": ref.solo_p99_ms,
            "fifo_p99_ms": ref.fifo_p99_ms,
            "tokenbucket_p99_ms": ref.tokenbucket_p99_ms,
            "ratio_of_solo": ref.ratio_of_solo,
        },
        "docs": "docs/launch/gate0_launch_post.md", "raw_summary": summary,
    }


async def _run(
    flavor: FlavorSpec, base_url: str, duration_s: float,
    output_dir: Path, console: Console,
) -> dict[str, Any]:
    """Pre-flight → bench → summary → report."""
    bench = _import_bench_module()
    ok, hint = await _preflight_server(base_url, _HERO_MODEL, console)
    if not ok:
        console.print(f"[red]✗[/red] pre-flight failed: {hint}")
        raise SystemExit(2)
    gpu = _detect_gpu()
    if gpu and "A100" not in gpu:
        console.print(
            f"[yellow]![/yellow] Detected GPU [bold]{gpu}[/bold] — reference "
            "numbers were measured on A100-SXM4. Expect divergence."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    ns = argparse.Namespace(
        url=base_url, model=_HERO_MODEL,
        flooder_rps=flavor.flooder_rps, quiet_rps=flavor.quiet_rps,
        num_quiet=flavor.num_quiet, duration_s=duration_s,
        max_tokens=64, timeout_s=60.0, seed=42,
        output_dir=str(output_dir), prompt_length_dist="",
    )
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = int(ns.duration_s)
    bench_task = asyncio.create_task(bench.main_async(ns))
    start_mono = time.monotonic()
    while not bench_task.done():
        elapsed = min(total, int(time.monotonic() - start_mono))
        console.print(f"  [dim]bench progress:[/dim] {elapsed}/{total}s")
        await asyncio.sleep(15.0)
    rc = await bench_task
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if rc != 0:
        raise SystemExit(f"bench script exited rc={rc}. See {output_dir}/tenant_*.csv.")
    summary = _load_summary(output_dir)
    report = _build_report(
        flavor, summary, _flooder_rate(output_dir),
        base_url, duration_s, gpu, started, finished,
    )
    with open(output_dir / "report.json", "w") as fh:
        json.dump(report, fh, indent=2)
    return report


def run_reproduce_hero(args: argparse.Namespace) -> None:
    """Entry point wired from :func:`infergrid.cli._cmd_bench`."""
    console = Console()
    if args.flavor not in FLAVORS:
        console.print(f"[red]✗[/red] unknown flavor: {args.flavor!r}")
        raise SystemExit(2)
    flavor = FLAVORS[args.flavor]
    base_url = args.base_url.rstrip("/")
    duration_s = float(args.duration_s or flavor.default_duration_s)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"./infergrid-reproduce-{stamp}").resolve()

    pod_ctx = None
    if args.pod:
        # Lazy-import: the runpod SDK is not a core dep.
        from infergrid._bench.pod import ensure_pod, pod_signal_handler

        pod_ctx = ensure_pod(console=console, delete_on_exit=not args.no_delete)
        base_url = pod_ctx.base_url
        signal.signal(signal.SIGINT, pod_signal_handler(pod_ctx))
        signal.signal(signal.SIGTERM, pod_signal_handler(pod_ctx))

    try:
        host, port = _split_host_port(base_url)
        if not _port_listening(host, port):
            console.print(
                f"[red]✗[/red] nothing listening on {host}:{port}. Start: "
                f"[cyan]infergrid serve --config {flavor.config_hint} --port {port}[/cyan]"
            )
            raise SystemExit(2)
        report = asyncio.run(_run(flavor, base_url, duration_s, output_dir, console))
    finally:
        if pod_ctx is not None and not args.no_delete:
            pod_ctx.teardown()

    u = report["user_result"]
    render_comparison(
        flavor=flavor.name,
        user_quiet_p99_ms=u["quiet_aggregate_p99_ms"],
        user_flooder_429_rate=u["flooder_429_rate"],
        user_solo_p99_ms=None,
        console=console,
    )
    console.print(
        f"\n[bold]artifacts:[/bold] {output_dir}\n"
        f"  report.json — side-by-side vs published\n"
        f"  summary.json — raw bench summary\n"
        f"  tenant_*.csv — per-request rows"
    )
