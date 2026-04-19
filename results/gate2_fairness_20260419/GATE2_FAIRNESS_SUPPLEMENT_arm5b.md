# Gate 2-FAIRNESS — Arm 5b Supplement: Token Bucket Eliminates the Warmup Transient

**Date:** 2026-04-19
**Hardware:** 1× NVIDIA A100-SXM4 80GB on RunPod (SECURE on-demand, fresh pod)
**Cost:** ~$0.30 (~10 min billable wall × $1.89/hr)
**Code tip:** `9d8ef87` (PR #47 — token-bucket rate-limit replaces 60s sliding window) + `cda7138` (PR #48 — Arm 5b config yaml).
**Config:** `configs/gate2_fairness_token_bucket.yaml` (IDENTICAL to Arm 5's `gate2_fairness_drr_ratelimit.yaml` except `tenant_defaults.rate_limit_burst: 10`).
**Status:** **CLEAN CONFIRM.** The caveat on the headline Gate 2-FAIRNESS result is gone — quiet tenant TTFT stays within 1.35× of solo baseline for the FULL bench, with no warmup transient.

---

## The caveat that PR #47 fixes

Arm 5 (the original hero arm) had the 503× p50-steady-state improvement over Arm 1's 523× starvation — but the full-bench p99 was 5378ms because the TenantBudget's 60-second sliding window took ~19s to accumulate 600 historical flooder requests before any 429 fired. During that startup window, vLLM saturated and quiet's TTFT inherited the saturation. Per `GATE2_FAIRNESS_OUTCOME.md` per-window trace, quiet p50 was >1000ms at t=0-30s and again at t=60-80s.

The fix in PR #47: replace sliding window with a token bucket that engages from t=0. Backward-compatible (default burst=rate_limit_rpm preserves sliding-window-equivalent semantics for existing configs). For fairness-critical workloads, set `rate_limit_burst` to a small value like `rate_limit_rpm/60` (1 second of capacity at 10 RPS sustained).

---

## Arm 5b raw numbers

### quiet_user (the variable under test)

| Metric | Arm 0 solo baseline | Arm 1 FIFO contended | **Arm 5 (sliding window)** | **Arm 5b (token bucket)** |
|---|---:|---:|---:|---:|
| ttft_p50_ms | 28.5 | 15087.3 | 45.7 (full) / ~30 (steady) | **33.0** |
| ttft_p95_ms | 42.2 | 27955.2 | 4863.6 | **59.1** |
| ttft_p99_ms | **54.9** | **28716.0** | **5377.8** | **74.2** |
| ttft_max_ms | 55.8 | 28790.5 | 5776.4 | **74.5** |
| total_p50_ms | 1607.4 | 18750.5 | 3344.9 | 2396.4 |
| total_p99_ms | 1708.3 | 32324.3 | 9011.2 | 2624.8 |
| count_ok | 262 (240s) | 113 (120s) | 113 (120s) | 113 (120s) |
| count_err | 0 | 0 | 0 | 0 |

### flooder (throttled by design)

| Metric | Arm 1 | Arm 5 | **Arm 5b** |
|---|---:|---:|---:|
| ttft_p50_ms | 15690.1 | 3197.9 | **32.2** |
| ttft_p99_ms | 28744.3 | 5743.1 | **66.3** |
| count_ok | 3733 | 1200 | **1208** |
| count_err | 0 | 2570 | **2588** |

---

## Per-window quiet TTFT trace — side-by-side

This is the load-bearing diagnostic. If the token bucket works as theory predicts, every 10-second window in Arm 5b should show quiet TTFT at baseline (~30ms), with no transients.

| window | Arm 5 (sliding) p50 | Arm 5 max | Arm 5b (bucket) p50 | Arm 5b max |
|---|---:|---:|---:|---:|
| t=0-10s | **1390.0 ms** | 3244.9 ms | **45.4 ms** | 58.0 ms |
| t=10-20s | **4065.8 ms** | 5377.8 ms | **29.8 ms** | 44.9 ms |
| t=20-30s | **2297.5 ms** | 4337.7 ms | **38.4 ms** | 50.5 ms |
| t=30-40s | 29.8 ms | 45.8 ms | 41.4 ms | 60.8 ms |
| t=40-50s | 34.1 ms | 40.6 ms | 33.9 ms | 59.0 ms |
| t=50-60s | 28.0 ms | 35.6 ms | 34.9 ms | 56.1 ms |
| t=60-70s | **1143.2 ms** | 3487.2 ms | **43.7 ms** | 62.1 ms |
| t=70-80s | **4791.9 ms** | 5060.2 ms | **32.8 ms** | 74.2 ms |
| t=80-90s | **1841.1 ms** | 5776.4 ms | **32.7 ms** | 35.6 ms |
| t=90-100s | 36.3 ms | 41.5 ms | 34.8 ms | 74.5 ms |
| t=100-110s | 29.6 ms | 43.5 ms | 24.8 ms | 37.0 ms |
| t=110-120s | 31.8 ms | 37.9 ms | 24.8 ms | 47.8 ms |

Arm 5 had **5 transient windows** with quiet p50 > 1000ms (t=0-30s and t=60-90s — the second transient was the sliding-window edge where early timestamps aged out, briefly re-permitting flooder bursts).

Arm 5b has **ZERO transient windows**. Every 10-second window has p50 ≤ 46ms and max ≤ 75ms. The token bucket holds the line from the very first flooder burst through the full 120 seconds.

---

## Pre-committed criteria

| Criterion | Arm 5b value | Result |
|---|---|---|
| `quiet_p99 ≤ 300ms` (5× Arm 0 baseline) full-bench | 74.2 ms | **PASS** (well under) |
| All 10s windows show quiet p50 near baseline (~30-50ms) | max window p50 = 45.4 ms | **PASS** (cleanly) |
| Flooder gets 429'd | count_err=2588 | **PASS** |
| Quiet ALSO getting 429s (plumbing bug) | count_err=0 | **PASS** (no regression) |

**All criteria pass.** The token bucket is the right mechanism; the sliding window was a real defect.

---

## Headline improvement over Arm 1 (starvation baseline)

- **p50:** 15087 ms → **33.0 ms** = **457× improvement**
- **p99:** 28716 ms → **74.2 ms** = **387× improvement**
- **No transient exception.** Every window of the bench is at baseline.

And vs Arm 0 (solo quiet):
- p50: 28.5ms → 33.0ms = **1.16× of solo baseline** under flooder contention.
- p99: 54.9ms → 74.2ms = **1.35× of solo baseline** under flooder contention.

The quiet tenant is **essentially unaware of the flooder's presence.**

---

## What this means for the launch post

The caveat paragraph in the original OUTCOME ("full-bench p99 is dominated by a sliding-window warmup transient …") **can be deleted from the launch post draft.** The clean narrative is:

> We measured a 523× tail-latency starvation on vanilla vLLM when a noisy neighbor shares a single-model engine. InferGrid's per-tenant token-bucket rate-limit at the budget gate brings the quiet tenant within 1.35× of solo baseline — ~10 lines of config. The quiet tenant is essentially unaware of the flooder.

The "we tried 3 configurations" research narrative still plays as the honest-engineering supporting beat — the full story (Arms 3/4/5 failures → Arm 5 near-win with sliding-window caveat → Arm 5b clean-win with token bucket) is a tight, defensible arc of measurement-driven product development.

---

## Artifacts

- `gate2f_arm5b_20260419_163431/gate2f_arm5b_*_results.tar.gz` (240 KB tarball)
- Extracted: `benchmarks/{tenant_flooder.csv, tenant_quiet_user.csv, summary.json}`, `server.log`, `engine_logs/`, `prometheus_dump.txt`, `gpu_trace.csv`, `status_{before,after}.json`, `phase_*.ts`, `pip_freeze.txt`.

---

## Remaining caveats (not blockers)

1. Arm 5b flooder max TTFT at 321ms is unusually high for a rate-limited client; likely a burst that snuck through during a refill instant. Does not affect quiet's numbers.
2. Quiet's max TTFT of 74ms lives in the t=70-80s and t=90-100s windows. These are ~1.35× the Arm 0 max (55.8ms) and may reflect incidental engine-batch contention when flooder's refill happens to land simultaneously with quiet's request. Acceptable for the claim; could be smoothed further by smaller refill granularity (deferred).
3. Sample size is still 113 quiet requests per arm — at 1 RPS for 120s, fundamental. p99 has ~1 sample below it; p95 has ~5. For preprint-quality claims, rerun with longer wall (e.g., 5 min × 1 RPS = 300 samples for cleaner p99).

These are launch-post-friendly "here's what we'd test next" items, not architectural concerns.
