# Gate 3 — Tenant-Aware KV Eviction (Path C Probe)

**Date:** <TBD_DATE>
**Hardware:** 1× <TBD_GPU_MODEL> on RunPod (SECURE on-demand, ~$<TBD_HOURLY>/hr) — see Caveats re: GPU substitution if A100-SXM4 80GB unavailable.
**Total cost:** ~$<TBD_COST_ACTUAL> actual (ceiling $<TBD_COST_CEILING>; T2 hard cap $20).
**main tip at start:** `<TBD_SHA>` (<TBD_PR_POINTER>).
**Model:** `meta-llama/Llama-3.1-8B-Instruct`, bfloat16, max_model_len=4096, gpu_memory_utilization=0.40 (tight VRAM to bind eviction).
**Workload:** 1 flooder @ 32 RPS + 7 quiet @ 1 RPS each, 70% prompt-prefix overlap (RAG-style: <TBD_PREFIX_TOKENS>-token shared prefix), 300s sustained, 128-token outputs, 3 seeds per arm.
**Prefix-overlap mechanism:** <TBD_PREFIX_MECHANISM — harness flag if landed, else bench-side mock procedure used>.
**Status:** **<TBD_STATUS>.** <TBD_STATUS_ONELINER>

**Hypothesis going in:** under engine pressure created by 32:1 RPS skew + heavy prefix overlap + tight VRAM, LRU eviction creates cross-tenant cache thrash. Tenant-aware eviction (oracle, Arm 2) should cut quiet-tenant p99 TTFT by ≥1.5× vs LRU baseline (Arm 1). Null: admission-side DRR already captures most of the gap; Arm 2 - Arm 1 < 1.2× and W4 implementation is unjustified.

---

## Headline numbers

Median across 7 quiets of per-tenant p99 TTFT, then median across 3 seeds.

| | Arm 1 LRU baseline | Arm 2 Oracle tenant-aware | Arm 3 Admission only |
|---|---:|---:|---:|
| `quiet_user.ttft_p50` (median across 7 quiets) | <TBD> ms | <TBD> ms | <TBD> ms |
| **`quiet_user.ttft_p99` (median across 7 quiets)** | **<TBD> ms** | **<TBD> ms** | **<TBD> ms** |
| `quiet_user.ttft_p99` (worst of 7 quiets) | <TBD> ms | <TBD> ms | <TBD> ms |
| `quiet_user.ttft_p99` (best of 7 quiets) | <TBD> ms | <TBD> ms | <TBD> ms |
| `quiet_user.count_ok` (sum across 7, sum across 3 seeds) | <TBD> | <TBD> | <TBD> |
| `flooder.count_ok` | <TBD> | <TBD> | <TBD> |
| `flooder.count_err` (429) | <TBD> | <TBD> | <TBD> |

**Path C decision delta: Arm 1 / Arm 2 quiet p99 = <TBD>×.**
**Per-quiet-tenant spread (max - min p99 across 7, Arm 2): <TBD> ms.**

---

## Pre-committed criteria (from runbook + strategic plan §5)

| Criterion | Value | Result |
|---|---|---|
| Arm 2 - Arm 1 quiet p99 delta ≥ 1.5× (green; pursue W4) | <TBD>× | **<TBD>** |
| Arm 2 - Arm 1 delta in [1.2×, 1.5×) (yellow; flag-gated) | <TBD>× | **<TBD>** |
| Arm 2 - Arm 1 delta < 1.2× (red; disconfirm + park) | <TBD>× | **<TBD>** |
| Arm 2 flooder gets 429d (rate-limit fires, plumbing OK) | flooder count_err=<TBD> | **<TBD>** |
| Arm 2 no quiet tenant gets 429d (plumbing check) | quiet count_err sum=<TBD> | **<TBD>** |
| Arm 2 per-quiet spread ≤ 1.5× max/min | max/min=<TBD> | **<TBD>** |
| Prefix-cache hit rate measurably higher in Arm 2 vs Arm 1 (eviction signal) | Arm 1 hit=<TBD>%, Arm 2 hit=<TBD>% | **<TBD>** |

The last criterion is the load-bearing eviction signal: if hit-rate doesn't move between Arm 1 and Arm 2, the workload didn't exercise eviction at all and the result is null-by-construction (re-do with tighter gmu or higher prefix overlap).

---

## All arms — full data table (per seed × per arm)

| Arm | Seed | Config | quiet_p50 (med/worst) | quiet_p99 (med/worst) | flood_p99 | flood_err | Notes |
|---|---|---|---:|---:|---:|---:|---|
| **1** | 0 | gate3_kv_eviction.yaml arm1 | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | LRU baseline |
| **1** | 1 | same | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | |
| **1** | 2 | same | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | |
| **2** | 0 | gate3_kv_eviction.yaml arm2 | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | Oracle tenant-aware |
| **2** | 1 | same | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | |
| **2** | 2 | same | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | |
| **3** | 0 | gate3_kv_eviction.yaml arm3 | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | Admission only |
| **3** | 1 | same | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | |
| **3** | 2 | same | <TBD>/<TBD> | <TBD>/<TBD> | <TBD> | <TBD> | |

---

## What the data falsifies and confirms

### Confirmed
- <TBD>

### Falsified
- <TBD>

### Diagnosed
- <TBD>

---

## Per-quiet-tenant breakdown (Arm 2, seed 0)

| Tenant | count_ok | ttft_p50 (ms) | ttft_p99 (ms) | count_err |
|---|---:|---:|---:|---:|
| quiet_0 | <TBD> | <TBD> | <TBD> | <TBD> |
| quiet_1 | <TBD> | <TBD> | <TBD> | <TBD> |
| quiet_2 | <TBD> | <TBD> | <TBD> | <TBD> |
| quiet_3 | <TBD> | <TBD> | <TBD> | <TBD> |
| quiet_4 | <TBD> | <TBD> | <TBD> | <TBD> |
| quiet_5 | <TBD> | <TBD> | <TBD> | <TBD> |
| quiet_6 | <TBD> | <TBD> | <TBD> | <TBD> |
| **spread** | — | **<TBD>** | **<TBD>** | — |

If Arm 2's spread shows the 7 quiets within ~1.5× on p99 with all blocks pinned, the oracle is functioning. A wider spread under Arm 2 indicates the pin mechanism leaked (block IDs collided, prefix-hash imperfect, or weight mapping failed bench-side).

---

## Operational notes

- <TBD: pod spin count / any resume vs terminate lessons>
- <TBD: prefix-overlap mechanism — harness flag landed pre-W3 OR bench-side mock applied at run time; document the procedure used>
- <TBD: cost actual vs ceiling, OOM retries, gmu drops if any>

---

## Implications for the W4 decision gate

<TBD: 1-4 bullets on what Path C says about Path A1.

If GREEN (≥1.5×): the W4 reuse_score implementation has clear headroom; A1 is funded. Capture the Arm 2 - Arm 1 delta as the implementation target.

If YELLOW (1.2-1.5×): A1 ships flag-gated experimental; document the regime where it helps (long shared prefix, high RPS skew, tight VRAM) and where it doesn't (short prompts, low skew, ample VRAM).

If RED (<1.2×): admission-side DRR already captures the gap. Draft disconfirm post for `docs/launch/`. Park A1 to v0.3 tracking issue. Re-anchor T2 as "trace + replay tooling + null result." Reference strategic plan §1 disconfirm framing.>

**W3 decision-gate result:** <TBD: GREEN / YELLOW / RED + one-line rationale>.

---

## Rsync'd artifacts

Per cell (`arm{1,2,3}_seed{0,1,2}/`):
- `summary.json` — bench-harness aggregate + per-tenant percentiles (includes warmup; used only for count_ok and wall_time_s)
- `tenant_flooder.csv`, `tenant_quiet_{0..6}.csv` — per-request rows; **source of truth** for post-60s-warmup percentile extraction
- `bench.log` — harness stdout
- `server.log`, `engine_logs/` — kvwarden + vLLM stderr
- `gpu_trace.csv` — 1Hz nvidia-smi sample
- `prometheus_dump.txt` — kvwarden /metrics at end-of-cell
- `status_{before,after}.json` — kvwarden /kvwarden/status snapshots
- `pip_freeze.txt`, `git_head.txt` — reproducibility pins

Top-level:
- `summarize_gate3.py` — post-warmup percentile re-extractor (first 60s of submit_time excluded per CSV)
- `post_warmup_summary.json` — output of summarize_gate3.py across all cells
- `per_tenant_ttft_histograms.png` (optional) — CDFs across 7 quiets per arm

---

## Caveats not yet investigated

1. **GPU substitution.** If A100-SXM4 80GB availability collapses during scheduling, document the actual pod GPU here. Absolute latencies will differ; the per-tenant fairness ratio should preserve since it's a property of the eviction layer, not the compute substrate.
2. **Prefix-overlap fidelity.** <TBD: whether the realized prefix overlap matched the requested 70% — bench-side mock measurement variance, harness flag bugs if landed late.>
3. **Eviction signal.** <TBD: did `nvidia-smi memory.used` actually saturate near gmu=0.40? If not, eviction never fired and the result is null-by-construction; rerun at gmu=0.35.>
4. **Oracle validity.** <TBD: bench-side mock pinning vs the W4 wired implementation may diverge — Arm 2 is a synthetic upper bound, not a behavioral spec for A1.>

These are caveats on the Path C result, not on the v0.2.0 ship decision.

---

## Decision tree from here

<TBD: conditional on outcome.
- GREEN → W4 starts 05-20; A1 lands W6; full Gate 3 Arm 3 reruns at $8 (M6).
- YELLOW → W4 starts 05-20 with explicit experimental flag; v0.2.0 ships flag-gated.
- RED → draft disconfirm post; park A1 to v0.3; re-anchor T2 as null-result chapter.>

This OUTCOME is interpretation-friendly per the runbook contract: raw numbers + diagnostic decomposition + the user calls the framing.
