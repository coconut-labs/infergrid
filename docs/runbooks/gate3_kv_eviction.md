# Gate 3 — Tenant-Aware KV Eviction Runbook

**Audience:** the operator spending ~$8 in W3. Do these in order.
**Hardware:** 1× NVIDIA A100-SXM4 80GB on RunPod (SECURE on-demand, ~$1.50/hr at strategic-plan author time; verify at provision and update this runbook with the observed rate).
**Wall:** ~4.5 GPU-hours (9 cells × ~30 min), ~5h end-to-end with rsync.
**Cost:** ~$7-8 expected, **$20 hard ceiling** (T2 budget).
**main tip required:** W1 signature stub merged (PR #103-1 or successor); SHA captured in OUTCOME at run time.

---

## Why Gate 3 exists

Gate 2-FAIRNESS proved DRR + token-bucket admission keeps quiet-tenant p99 TTFT near-solo under flooder pressure. Admission is half the story: once admitted, the engine's KV cache is shared. If flooder blocks evict quiet blocks under LRU + heavy access skew, the quiet tenant pays a re-prefill tax on every request — and that tax shows up in TTFT, not in admission counters.

**Path C asks: at 32:1 RPS skew + 70% prompt prefix overlap + tight VRAM, does LRU eviction starve quiet tenants? What's the upper bound from tenant-aware eviction?**

Strategic plan: `~/Personal Projects/.claude/agent-memory-local/god-planner/project_kvwarden_t2_scope_apr28.md` §1. If oracle Arm 2 doesn't beat LRU Arm 1 by ≥1.2× on quiet-tenant p99 TTFT, the W4 reuse_score implementation cannot exceed it; T2 closes with a null result instead of 600-800 LOC of unmeasured code.

## Hypothesis

Under N=8 (1 flooder + 7 quiet), 70% prompt prefix overlap, flooder 32 RPS / quiet 1 RPS each, gpu_memory_utilization=0.40:

1. **Arm 1 (LRU baseline):** quiet p99 TTFT degraded by cross-tenant cache thrash. Engine LRU recycles quiet blocks; every quiet request re-prefills.
2. **Arm 2 (oracle tenant-aware):** flooder weight=0.1, quiet weight=1.0, blocks pinned above 0.5 weight. No quiet block evicts. Synthetic upper bound.
3. **Arm 3 (admission only, no eviction override):** v3 hero baseline. Teases out admission-alone vs eviction-alone gain.

**Pass / disconfirm rubric** (Arm 2 - Arm 1 quiet-p99 TTFT delta, median across 7 quiets):

| Delta | Action | v0.2.0 ship |
|---|---|---|
| ≥ 1.5× | Green; pursue W4 | Default-on, README hero |
| 1.2-1.5× | Yellow; flag-gated experimental | Documented regime |
| < 1.2× | Red; publish disconfirm, park A1 to v0.3 | LRU as default, null result |

**Metric of record:** per-tenant p99 TTFT aggregated across 7 quiets, reported as min/max/median. Headline = median (typical-quiet experience). Max-of-7 catches priority inversion; min-of-7 catches one lucky tenant masking degradation.

## Cell matrix

3 arms × 3 seeds = **9 cells**. ~30 min/cell wall.

| Phase | Per cell | Notes |
|---|---:|---|
| Pod provision | ~5 min | First cell only |
| Weights download | ~10 min | First cell only; cached on pod survival |
| vLLM cold-load | ~2-3 min | Every cell at gmu=0.40 |
| Bench warmup | ~10 min | 600s drain |
| Bench run | ~5 min | 300s sustained |
| Rsync | ~1 min | Every cell |

**Total compute:** 9 × 30 min = 4.5 GPU-hours. At $1.50/hr = ~$6.75 + 20% buffer = **~$8 budgeted**. **$20 hard cap**. Path-C-only (Arm 1 + Arm 2 × 3 seeds = 6 cells) drops cost to ~$5-6.

## Pre-flight

1. **Harness gap (BLOCKING for Arm 2).** `benchmarks/scripts/benchmark_n_tenant_single_model.py` ships `--prompt-length-dist` (Gate 2.2) but **NO `--prefix-overlap` flag**. The PROMPTS list is 8 short hardcoded strings with no shared prefix — running unmodified gives near-zero prefix-cache overlap regardless of `cache_manager` policy. Pick one before provisioning:
   - Land `--prefix-overlap PCT --prefix-tokens N` on the harness (sibling Agent T or follow-up PR; outside this runbook's scope).
   - Bench-side mock: pre-generate a long shared prefix (~1500 tokens of a Wikipedia article); wrap each PROMPTS entry as `f"{shared_prefix}\n\nQuestion: {prompt}"`; monkey-patch the harness invocation.
   - Skip Arm 2 + Arm 3, re-scope to "Arm 1 + admission baseline" until the gap closes.
   A 4.5h dry run on a no-overlap workload burns the entire $8 path-C budget.

2. **Local dress rehearsal.** Run the smoke command in "Reproduce locally" — confirm YAML loads, kvwarden CLI accepts the config, mock-engine smoke produces summary.json. Don't provision if it fails.

3. **HF_TOKEN valid for Llama:**
   ```bash
   curl -fsS -H "Authorization: Bearer $HF_TOKEN" \
     https://huggingface.co/api/models/meta-llama/Llama-3.1-8B-Instruct | head -c 200
   ```

4. **RunPod balance ≥ $25** (3× expected; pod retries common on SECURE).

5. **A100-SXM4 80GB SECURE spot ≤ $2.00/hr.** If higher, wait or switch region; update this runbook with the rate.

6. **Calendar block 5h.** Engine bring-up at gmu=0.40 + Llama-3.1-8B is the historical failure mode.

## Launch

### 1. Provision

```bash
runpodctl create pod \
  --name "kvwarden-gate3-kv-eviction" \
  --gpu-type "A100 SXM4 80GB" \
  --image vllm/vllm-openai:0.19.1 \
  --cloud-type SECURE \
  --container-disk-gb 80 \
  --ports "22/tcp,8000/http" \
  --env "HF_TOKEN=$HF_TOKEN" \
  --env "MAX_POD_SECS=21600"
```

(MAX_POD_SECS=21600 = 6h, above 4.5h compute budget. In-pod self-destruct is best-effort; the operator's calendar alarm is the actual ceiling.)

Capture `POD_IP`, `POD_PORT`. Smoke: `ssh -p $POD_PORT root@$POD_IP 'nvidia-smi -L'` should print the A100.

### 2. Push env + bootstrap

```bash
cat > /tmp/.gate3_env <<EOF
export HF_TOKEN=$HF_TOKEN
export MAX_POD_SECS=21600
EOF
scp -P $POD_PORT /tmp/.gate3_env root@$POD_IP:/root/.gate_env
scp -P $POD_PORT scripts/gate_pod_bootstrap.sh root@$POD_IP:/workspace/
```

### 3. Run cells

For each `(ARM, SEED)` in `{arm1, arm2, arm3} × {0, 1, 2}`:

```bash
ssh -p $POD_PORT root@$POD_IP <<REMOTE
nohup bash /workspace/gate_pod_bootstrap.sh \
  --run-name gate3_${ARM}_seed${SEED}_\$(date -u +%Y%m%d_%H%M%S) \
  --config configs/gate3_kv_eviction.yaml \
  --bench-script benchmarks/scripts/benchmark_n_tenant_single_model.py \
  --bench-args "--url http://localhost:8000 --model meta-llama/Llama-3.1-8B-Instruct --flooder-rps 32 --quiet-rps 1 --num-quiet 7 --duration-s 300 --max-tokens 128 --output-dir RDIR/benchmarks --seed ${SEED}" \
  > /workspace/bootstrap_${ARM}_${SEED}.console 2>&1 &
disown
REMOTE
```

Wait for `_DONE`, rsync, repeat.

**Path-C-only:** loop `{arm1, arm2} × {0, 1, 2}` = 6 cells = ~3 GPU-hours. Drop Arm 3 if budget tight or harness fix not in.

### 4. Teardown

```bash
runpodctl remove pod $POD_ID
```

Verify in console.

## Reading the result

Each cell's `summary.json` carries `quiet_aggregate.ttft_p99_ms` and `quiet_per_tenant.quiet_N.ttft_p99_ms`. Headline = median across 7 quiets of per-tenant p99, then median across 3 seeds.

```
arm_quiet_p99_med = median([
    median([cell.quiet_per_tenant[f"quiet_{i}"].ttft_p99_ms for i in range(7)])
    for cell in cells_for_arm
])
arm2_vs_arm1_delta = arm1_quiet_p99_med / arm2_quiet_p99_med
```

Apply the rubric.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| OOM on engine cold-load | gmu=0.40 too tight at A100 + bf16 | Drop to `gpu_memory_utilization: 0.35`; document in OUTCOME caveats |
| Engine cold-load > 5 min | A100 wheel cache cold or HF rate limit | Wait 5 min; check `server.log` for `Failed to pre-load`; retry HF download |
| All quiet tenants identical p99 | Prefix-overlap gap — 8 distinct short prompts, not shared-prefix | Re-do pre-flight item 1; don't burn budget on no-overlap |
| Arm 2 quiet p99 > Arm 1 quiet p99 | Oracle mock broken (pin didn't take), OR gmu too generous (no eviction pressure) | Verify pin honored; check `nvidia-smi --query-gpu=memory.used,memory.total --format=csv` mid-bench |
| Flooder count_err > 5% | Token-bucket fired (expected at 32 RPS w/ rate_limit_rpm=600) | Confirm errors are 429s in CSV; if timeouts, raise `--timeout-s 90` |
| Quiet count_err > 0% | Plumbing regression (admission rejecting quiet) | Check `tenant_rejected` in server.log; debug, don't interpret |

## Reproduce locally

CPU smoke against the mock engine (60s, no GPU):

```bash
python -m benchmarks.scripts.benchmark_n_tenant_single_model \
  --url http://localhost:8000 \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --flooder-rps 32 --quiet-rps 1 --num-quiet 7 \
  --duration-s 60 \
  --max-tokens 32 \
  --output-dir /tmp/gate3_smoke \
  --seed 0
```

Pre-launch `kvwarden serve --config configs/gate3_kv_eviction.yaml` in another terminal first; mock engine at `benchmarks/scripts/mock_engine.py`. Full run uses `--duration-s 300`.

## Provenance

After all cells complete, archive to `results/gate3_TBD/` (rename to `results/gate3_YYYYMMDD/` on run day):

- `arm{1,2,3}_seed{0,1,2}/` — full pod-side bundles per cell. Each: `summary.json`, `tenant_flooder.csv`, `tenant_quiet_{0..6}.csv`, `bench.log`, `server.log`, `engine_logs/`, `gpu_trace.csv`, `prometheus_dump.txt`, `status_{before,after}.json`, `pip_freeze.txt`, `git_head.txt`.
- `OUTCOME.md` — fill the pre-landed template at `results/gate3_TBD/OUTCOME.md`. Sed-replace seams marked `<TBD_*>`.
- `summarize_gate3.py` — post-warmup percentile re-extractor (mirror `results/h100_adversarial_sweep_20260421/summarize_sweep.py`; first 60s of submit_time excluded per CSV).
- `per_tenant_ttft_histograms.png` (optional) — matplotlib CDFs across 7 quiets per arm.

The OUTCOME template is pre-landed so the writeup is a mechanical fill.

## After Gate 3

1. Copy artifacts into `results/gate3_YYYYMMDD/`.
2. Fill `OUTCOME.md`.
3. Update `PROGRESS.md` with W3 decision-gate result.
4. Per the rubric:
   - **Green** (≥1.5×) → kick off W4 A1 implementation. Update issue #103.
   - **Yellow** (1.2-1.5×) → ship A1 flag-gated; document the regime in v0.2.0 release notes.
   - **Red** (<1.2×) → draft disconfirm post for `docs/launch/`, park A1 to v0.3 tracking issue, re-anchor T2 as "trace + replay tooling + null result." See strategic plan §1.
