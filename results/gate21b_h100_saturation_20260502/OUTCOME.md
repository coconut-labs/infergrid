# Gate 2.1b — H100 Saturation Rerun (ABORTED at provisioning)

**Date:** 2026-05-02
**Hardware target:** 1× NVIDIA H100 80GB HBM3 SXM (RunPod SECURE on-demand, $2.99/hr).
**Status:** **ABORTED at provisioning.** Three pod-spin attempts on RunPod SECURE H100 SXM did not produce a runtime/SSH window; the third was held to the advisor patience boundary (18 min) and still showed `runtime: null` from the RunPod GraphQL API. Total sunk: **$1.64** (well under $5 cap). No bench cells run; no quiet-tenant TTFT data collected.

## Headline

- **Saturation achieved:** N/A — engine never came up; no bench cells were exercised.
- **FIFO Cell-A p99:** N/A.
- **Token-bucket Cell-B p99:** N/A.
- **Ratio A/B:** N/A.
- **Total spend:** $1.64 vs $5 hard cap.
- **At what flooder RPS?** Did not begin; the 128 RPS regime was never tested.

## Why the run aborted

All three pod spin-ups landed on the same machine slot (`lg4oogypa290`) and the RunPod GraphQL `pod.runtime` field stayed null — meaning no SSH ports, no in-pod observability. Without observability the most likely cause is a slow or hung image-pull of the multi-GB `runpod/pytorch:2.1.0-py3.10-cuda12.1.1-devel-ubuntu22.04` base, but the API gives no progress signal — `runtime: null` is binary, not a streak. Per advisor: terminating before 10-15 min wastes pull progress; held pod #3 the full 18 min before terminating. H100 PCIe SECURE was the contract-allowed fallback but it was reporting `lowestPrice: null` (no slot) at provision time. A100 SXM SECURE is OUT of task spec.

See `PROVISIONING_LOG.md` for the per-pod timeline and cost breakdown.

## Cell matrix

|Cell|Arm|Config|Flooder RPS|Seed|Wall (s)|Quiet p99 (ms)|In-flight peak|count_err|Cost ($)|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
|A1|FIFO|gate21b_fifo_n8|128|0|—|—|—|—|—|
|A2|FIFO|gate21b_fifo_n8|128|1|—|—|—|—|—|
|A3|FIFO|gate21b_fifo_n8|128|2|—|—|—|—|—|
|B1|TokenBucket|gate21b_tokenbucket_n8|128|0|—|—|—|—|—|
|B2|TokenBucket|gate21b_tokenbucket_n8|128|1|—|—|—|—|—|
|B3|TokenBucket|gate21b_tokenbucket_n8|128|2|—|—|—|—|—|

All cells: **NOT RUN.**

## Aggregate

|Metric|Cell A (FIFO)|Cell B (TokenBucket)|Ratio A/B|
|---|---:|---:|---:|
|Median-of-seeds quiet p99 (ms)|—|—|—|
|In-flight peak (max across cells)|—|—|—|

## Cost actual vs cap

|Item|Spend ($)|Cumulative|
|---|---:|---:|
|Pod #1 q4vw7kj8xt8wdt (11.5 min)|0.57|0.57|
|Pod #2 4jc34h0vu9zbrq (3.5 min)|0.17|0.74|
|Pod #3 qmflcgrv2vpxvt (18.0 min)|0.90|1.64|
|Cells|0.00|1.64|
|**Total**|**1.64**|**1.64**|

Hard cap: $5.00. Target: ~$3. Actual: **$1.64** — under cap, but the spend produced no signal.

## Launch narrative implication

Unchanged from Gate 2.1 (PR #81): the H100 N=8 result at flooder_rps=32 stays the on-record claim — `1.05× of solo baseline at N=8, 0% quiet error rate, flooder 429'd at 68%`, with the regime caveat that the engine was not saturated at 32 RPS (in_flight peak <64). The "does fairness hold under saturation on H100" question stays open. **v0.1 launch post should not claim H100 generalizes A100's saturated-FIFO-starvation result; it should retain the existing regime caveat.** A100's Gate 2-FAIRNESS already CONFIRMED saturation behavior (29× FIFO starvation → 1.14× post-token-bucket at 32 RPS solo-vs-flood); that is the launch hero already.

## Recovery options (not executed this session)

1. **Retry next session, off-peak window.** RunPod inventory rotates; a different physical machine may have the image cached or a fresh, healthy slot. The task's pre-built configs/orchestrator/summarizer are committed on this branch and ready to drive 6 cells against any future warm pod.
2. **Drop saturation rerun from launch narrative.** The launch claim doesn't depend on this rerun, only strengthens it. Cleanest path is to retain Gate 2.1's "1.05× of solo at 32 RPS flooder" with its existing regime caveat, defer the saturation rerun to v0.2.0+.

Recommend (2) for the v0.1 launch window. Recovery option (1) is appropriate post-launch if H100-saturation evidence becomes load-bearing for a v0.1.x pitch.

## Methodology that did not run (preserved on branch)

Configs:
- `configs/gate21b_fifo_n8.yaml` — FIFO, gpu_memory_utilization=0.40, max_concurrent=512, rate_limit_rpm=999999.
- `configs/gate21b_tokenbucket_n8.yaml` — DRR + token-bucket rpm=60 (60-token capacity, 1/s refill), gpu_memory_utilization=0.40.

Orchestration:
- `scripts/_gate21b_orchestrator.sh` — sources from a master script; defines `run_cell()` that drives bootstrap + side-poll `/metrics` for in-flight gauge.
- `scripts/_gate21b_run_all_cells.sh` — caller that loops 6 cells with cost-cap guard.
- `scripts/_gate21b_summarize.py` — post-run percentile parser + `summary.json` generator.
- Existing `scripts/gate_pod_bootstrap.sh` (PR #25, post-#34) reused with one in-flight `sed` patch to clone this results branch instead of `main`.

Saturation detection: master-side `curl /metrics | grep vllm:num_requests_running` at 1 Hz cadence for the duration of each 300s bench cell, written to `cell{A,B}_seed{0,1,2}_engine_metrics.csv`. Threshold: in_flight peak ≥ 64 over the cell window indicates saturation.

## Artifacts

- `OUTCOME.md` — this file.
- `PROVISIONING_LOG.md` — per-pod timeline.

No `cell*.tar.gz`, no `*_engine_metrics.csv`, no `summary.json`. Nothing to summarize.

## Caveats / lessons

1. **Polling reflex tax.** Operator (this session) issued ~50 redundant pod-status polls during pod 1-3 image-pull windows; the polls returned identical `runtime: null` strings and consumed cognitive budget without changing the decision. Future runbook entry: when waiting for RunPod runtime, set ONE bg poller and ONE deadline alarm, then commit to no manual polls until either fires. (Captured in `PROVISIONING_LOG.md` for future-runbook absorption.)
2. **Same-slot reroute.** RunPod's `podFindAndDeployOnDemand` re-routed all three of my requests to the same machine `lg4oogypa290`. If that slot is unhealthy, terminating + recreating doesn't help — try a different region or a different gpuTypeId fallback. The task's "fall back to H100 PCIe SECURE" rule was honored but PCIe was unavailable; this is the gap in the fallback chain to flag.
3. **Image-pull observability gap.** RunPod's GraphQL exposes `runtime: null` vs `runtime: { ... }` but no progress signal between. Pre-flight should warm the image (or use a smaller image like `vllm/vllm-openai` if SSH bootstrap can be replaced with HTTP-only orchestration — see PR #126's Compose bundle).

## Sign-off

Aborted at 22:42:30 UTC. **$1.64 sunk, $5 cap not breached.** Branch `results/gate21b-h100-saturation-20260502` carries the configs, orchestrator, and OUTCOME — fully reproducible if a healthy H100 SXM SECURE slot becomes available in a future session.
