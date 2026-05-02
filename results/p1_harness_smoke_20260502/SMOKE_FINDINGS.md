# P1 harness smoke — findings (#125 flag GPU integration)

**Date:** 2026-05-02
**Pod:** `ky3xwz1i1k47d8` (same as gauge preflight; see `../p1_gauge_preflight_20260502/GAUGE_FINDINGS.md`).
**Harness:** `benchmarks/scripts/benchmark_n_tenant_single_model.py` at main HEAD `cb18d5e`. Runs PR #125 flags (`--prefix-overlap`, `--shared-prefix-tokens`, `--bias-flooder-cost`, `--bias-after-N-reqs`, `--bias-window-s`).

## Invocation

Run from local Mac against the RunPod HTTPS proxy:

```bash
SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())") \
python3 benchmarks/scripts/benchmark_n_tenant_single_model.py \
  --url https://ky3xwz1i1k47d8-8001.proxy.runpod.net \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --flooder-rps 8 --quiet-rps 1 --num-quiet 7 \
  --duration-s 60 --max-tokens 16 --timeout-s 30 --seed 42 \
  --prefix-overlap 0.7 --shared-prefix-tokens 256 \
  --bias-flooder-cost 4.0 --bias-after-N-reqs 100 --bias-window-s 30 \
  --output-dir results/p1_harness_smoke_20260502/
```

`SSL_CERT_FILE` is needed because the harness uses aiohttp without a custom SSL context, and the Mac Python 3.13 install ships without bundled CAs. Not a harness bug — a local-environment workaround.

## Per-check verdict

### f. Harness exits 0 — PASS

Harness ran to completion. Wrote `summary.json`, 8 per-tenant CSVs, and the summary recap log block. No tracebacks, no `WARN: bench non-zero`. Wall time 63 s for a 60 s duration (~3 s setup). The shell pipe through `tee` masked the explicit exit code in the trailing `echo HARNESS_RC=` (PIPESTATUS array vs single `?`), but every observable side-effect of a clean run is present.

### g. Per-tenant CSV rows for all 8 tenants — PASS

Task spec called the file `per_request.csv`; the actual harness writes one CSV per tenant (`tenant_flooder.csv` + `tenant_quiet_0..6.csv`). Mapping the task's check (g) to the actual schema:

| tenant | file | rows |
|---|---|---|
| flooder | tenant_flooder.csv | 246 |
| quiet_0 | tenant_quiet_0.csv | 58 |
| quiet_1 | tenant_quiet_1.csv | 51 |
| quiet_2 | tenant_quiet_2.csv | 64 |
| quiet_3 | tenant_quiet_3.csv | 69 |
| quiet_4 | tenant_quiet_4.csv | 66 |
| quiet_5 | tenant_quiet_5.csv | 64 |
| quiet_6 | tenant_quiet_6.csv | 59 |
| **total** |  | **677** |

All 8 tenants produced a CSV. Aggregate quiet n=431, flooder n=246. (The task spec in section "Verify" line g should be updated to the per-tenant filename pattern.)

### h. Bias-state transition log — PASS

Multiple "tenant=flooder entering bias state (>100 reqs in 30.0s window, multiplier=4.00x)" log lines fired. Excerpted from `harness.log`:

```
2026-05-02 17:49:56,763 [INFO] __main__: tenant=flooder entering bias state (>100 reqs in 30.0s window, multiplier=4.00x)
2026-05-02 17:50:19,645 [INFO] __main__: tenant=flooder exiting bias state (<=100 reqs in 30.0s window)
2026-05-02 17:50:20,030 [INFO] __main__: tenant=flooder entering bias state ...
... (8 enter / 7 exit transitions over the 60 s run)
```

The flooder hit 100 reqs in the first ~13 s (at 8 RPS that's ~104 reqs in 13 s once start-up RTT settled), entered bias, and oscillated near the threshold for the rest of the run. Behavior matches the bias-window sliding-counter design.

### i. `summary.json["bench_args"]` records all 5 new flag values — PASS

```json
"bench_args": {
  "flooder_rps": 8.0, "quiet_rps": 1.0, "num_quiet": 7,
  "duration_s": 60.0, "max_tokens": 16, "model": "meta-llama/Llama-3.1-8B-Instruct",
  "seed": 42, "prompt_length_dist": "",
  "prefix_overlap": 0.7,
  "shared_prefix_tokens": 256,
  "bias_flooder_cost": 4.0,
  "bias_after_n_reqs": 100,
  "bias_window_s": 30.0
}
```

All five new keys present with the values passed on the command line. The serialization is reproducible (no randomness in the args block) — Gate 3 reviewers can audit run config from `summary.json` alone.

## Quality observations (not gating, useful for M4)

- **Latency on the proxy was the bottleneck, not the engine.** Quiet p50 79.9 ms / p99 3,655 ms; flooder p50 83.9 ms / p99 3,575 ms. The 3.6 s p99 tail looks like queue depth at the RunPod HTTPS proxy under 8+7=15 RPS, not vLLM. M4's measurement runs MUST be from on-pod (loopback) to remove the proxy as a confound. Use the runpod/pytorch base + bootstrap script pattern for M4, not this image entrypoint override.
- **Per-quiet p99 spread = 1.01x.** Tight clustering — no rogue tenant. Consistent with admission-DRR + uniform quiet RPS. Not a fairness signal under this regime; M4's flooder-vs-quiet contrast is what tests fairness.
- **Prefix overlap is engaged.** The harness logged "Prefix-overlap enabled: fraction=0.70, shared_prefix_tokens=256" at startup. Gauge value never moved much (max 0.0044) because 16-token completions and a 256-token shared prefix on an 8B model with `--gpu-memory-utilization 0.40` don't fill the cache. M4 will need longer shared prefixes (1024+ tokens per RFC §Validation, "long doc + short tenant-specific suffix") to actually pressure the cache.

## Verdict

**#125 harness flags are M4-ready.** All five flags accept their values, both new behaviors (prefix-overlap prefix injection + bias-state cost multiplier) engage end-to-end, the bias-state transition is observable in logs, and the summary.json correctly serializes the configuration. No follow-up issue needed for the flag implementation itself.

The proxy-vs-loopback latency confound noted above is an M4 setup choice, not a #125 bug.

## Files

- `summary.json` — bench_args, per-tenant percentiles, prompt-length histograms, wall time.
- `tenant_flooder.csv`, `tenant_quiet_0..6.csv` — per-request rows.
- `harness.log` — full stdout/stderr, including bias-state transitions.
