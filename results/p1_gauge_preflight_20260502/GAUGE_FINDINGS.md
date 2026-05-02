# P1 gauge preflight — findings

**Date:** 2026-05-02
**Pod:** `ky3xwz1i1k47d8` — 1x A100 SXM4 80GB spot, COMMUNITY, $0.79/hr, EUR-IS-2.
**Image:** `vllm/vllm-openai:v0.19.1`. Verified `/version` -> `{"version":"0.19.1"}`.
**Model:** `meta-llama/Llama-3.1-8B-Instruct`, `--gpu-memory-utilization 0.40 --max-model-len 4096`.
**Access:** RunPod HTTPS proxy `https://ky3xwz1i1k47d8-8001.proxy.runpod.net`. The `vllm/vllm-openai` image runs vLLM as PID 1 with no sshd, so SSH-based access was not available; the proxy was the only path. Adds ~20-100 ms RTT overhead vs loopback. Cadence is therefore a lower bound on the gauge update rate (proxy can only hide updates, not invent them).

## Verbatim metric block from `/metrics`

```
# HELP vllm:kv_cache_usage_perc KV-cache usage. 1 means 100 percent usage.
# TYPE vllm:kv_cache_usage_perc gauge
vllm:kv_cache_usage_perc{engine="0",model_name="meta-llama/Llama-3.1-8B-Instruct"} 0.0
```

Full snapshot at `metrics_snapshot.txt` (56,843 bytes captured idle).

## Per-check verdict

### a. `vllm:kv_cache_usage_perc` line exists in `/metrics` — PASS

Exact line above. Present on every scrape across 232 samples + standalone curls.

### b. Type is `gauge` — PASS

`# TYPE vllm:kv_cache_usage_perc gauge` declared in the HELP/TYPE preamble immediately above the value line.

### c. Label set is `model_name` ONLY — **FAIL (RFC implication: section §Design needs an amendment)**

Actual label set: `engine="0",model_name="meta-llama/Llama-3.1-8B-Instruct"`. Two labels, not one. The RFC at `docs/rfcs/T2-cache-pressure-admission.md` §Design states (line ~52):

> 1. **Instance-level.** The only label is `model_name`. There is no per-tenant, per-request, or per-block label.

vLLM 0.19.x added an `engine` label for multi-engine routing (also visible on the sibling histograms `vllm:kv_block_*`). The `engine` label is `"0"` for single-engine deployments, and the gauge is still instance-level (one engine instance per pod under our spec), so the practical reading of the RFC's claim — "the gauge tells us global engine cache pressure, not per-tenant pressure" — survives intact.

**RFC implication:** the literal claim about the label set is wrong but the load-bearing inference (no per-tenant attribution from the engine; v0.2 composes engine pressure with kvwarden's tenant ledger) is unaffected. Two minimal RFC edits before Show HN:

1. §Design line ~52: change "The only label is `model_name`" -> "Labels are `model_name` and `engine` (the latter identifies the engine instance within a multi-engine deployment; values were `engine=\"0\"` only on the deployments verified). Both labels are instance-level — neither carries per-tenant or per-request information."
2. The poller/scraper logic locked in M5a must extract `(engine, model_name)` as a tuple, not just `model_name`, when surfacing per-(engine,model) pressure into `cache_manager.snapshot()`. The multi-instance section ("max across instances of the same model") still applies and is now slightly stronger: max is taken across `(engine, model_name)` tuples. Honest one-line scope add.

This is a documentation-grade RFC bug, not a kill criterion — the lever still exists and the mechanism still works. Do NOT block Show HN on it; do amend the RFC pre-launch so the launch post does not over-claim.

### d. Value is in [0.0, 1.0] — PASS

Observed range over 60 s of 4 RPS small-completion load: min 0.0, max 0.0044. Inside [0, 1]. No out-of-range or negative values observed; no clamp needed for this regime, but the v0.2 implementation should still defensively clamp (RFC test `test_gauge_value_out_of_range_clamps` is appropriately scoped).

Caveat: the workload was tiny (8-32 token completions, no shared prefix) so the gauge stayed near zero. This does NOT validate behavior under saturation; M4 is the test of the saturation regime. What it does validate: the gauge doesn't go negative, doesn't NaN out, and doesn't exceed 1.0 under a normal load.

### e. Update cadence — PASS at the level the RFC needs

60-second probe at 4 Hz scrape (250 ms target interval) + 4 RPS completion stream. Cadence script: `scripts/p1_gauge_cadence.py`. Raw timeline at `cadence.json`.

| metric | value |
|---|---|
| samples_total | 232 |
| samples_with_value (regex match) | 231 (99.6%) |
| distinct gauge values seen | 28 |
| inter-distinct-update **p50** | 0.2535 s |
| inter-distinct-update **p95** | 9.5453 s |
| inter-distinct-update p99 | 9.5492 s |
| inter-distinct-update min | 0.2505 s |
| inter-distinct-update max | 9.5492 s |
| inter-distinct-update mean | 1.8806 s |
| gauge value range observed | [0.0, 0.0044] |
| load requests sent | 239 |

Reading the distribution: the **p50 = 0.2535 s** sits exactly at the scrape interval, meaning vLLM updates the gauge at least once per 250 ms scrape under load — consistent with vLLM's ~per-step Prometheus emission. The **p95 = 9.55 s** reflects long stretches of identical 0.0 readings between completion bursts (the gauge correctly returned to 0 between requests). The "9.55 s" gap is not an update-rate problem; it's the gauge accurately reporting that the cache was empty.

**Verdict:** vLLM 0.19.1 updates the gauge at >= 1 Hz under load — comfortably above the RFC's "if updates < 1 Hz, fall back to staleness-bounded poller" threshold (R6 in `~/Personal Projects/.claude/agent-memory-local/god-planner/project_kvwarden_t2_scope_apr28.md`, mitigation row 1). The fixed 250 ms poller cadence locked in §Design is sufficient. No bounded-staleness fallback path is required for v0.2.

## Operational notes for M4

- **Image entrypoint override worked.** `dockerEntrypoint: ["sh", "-c"], dockerStartCmd: [single string]` correctly launched `vllm serve` and bound to 0.0.0.0:8001. The RunPod HTTP proxy maps 8001/http transparently.
- **Spot wait was ~5 minutes**, not the 30-90 s typical of secure cloud. EUR-IS-2 had capacity but the bid->accept loop on community spot is slower than secure. Plan an extra 5-10 min slack into M4 wall-time accounting.
- **No SSH on `vllm/vllm-openai` image.** If M4 needs in-pod commands (it does, for `nvidia-smi` traces), either:
  1. Switch to `runpod/pytorch:*` base + install vLLM ourselves (adds ~3-5 min cold start, gains sshd via PUBLIC_KEY env), OR
  2. Run the harness from local against the proxy URL (what was done here for Check 2). Works for benchmarking but doesn't capture GPU traces.
  M4 should use option (1) for the data capture path; this preflight used option (2) only because GPU traces aren't gating.

## Cost

- 18 min 18 s pod uptime at $0.79/hr = **$0.241** spent.
- Hard cap was $3.00; comfortably inside.

## Files

- `metrics_snapshot.txt` — full Prometheus dump captured idle.
- `cadence.json` — 232-sample timeline + analysis.
- `run.log` — orchestrator log (initial SSH-coupled attempt; pivoted to local+proxy mid-run).
- `orchestrator.log` — duplicate of run.log lines via the orchestrator's own logger.
