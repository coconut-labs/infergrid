# Reproduce the hero number

`infergrid bench reproduce-hero` runs the same 300 s noisy-neighbor
bench that produced the numbers in the [launch post](launch/gate0_launch_post.md)
and prints your box's result side-by-side with the published reference.

## Quick start (local)

```bash
# Terminal 1 — start the server against the hero config.
infergrid serve --config configs/gate2_fairness_token_bucket.yaml --port 8000

# Wait for /health (first call is 503 while vLLM JIT-compiles, 30-90 s on A100).
until curl -fs http://localhost:8000/health > /dev/null; do sleep 5; done

# Terminal 2 — run the bench.
infergrid bench reproduce-hero
```

Finishes in ~5 min. Artifacts land in `./infergrid-reproduce-<timestamp>/`
(`report.json`, `summary.json`, per-tenant CSVs).

## Flavors

| Flag | Tenants | Published quiet p99 | Config |
|---|---|---:|---|
| `--flavor 2tenant` (default) | 1 flooder + 1 quiet | 61.5 ms (1.14x solo) | `configs/gate2_fairness_token_bucket.yaml` |
| `--flavor n6`                | 1 flooder + 5 quiet | 61.0 ms (1.13x solo) | `configs/gate2_fairness_token_bucket_n6.yaml` |
| `--flavor n8`                | 1 flooder + 7 quiet | 50.4 ms (1.05x solo) | `configs/gate21_fairness_n8.yaml` |

## `--pod`: one-command provision + run + teardown

```bash
export RUNPOD_API_KEY=<key>
export HF_TOKEN=<huggingface-token>
infergrid bench reproduce-hero --pod          # ~25 min wall time
infergrid bench reproduce-hero --pod --no-delete  # keep pod for post-run inspection
```

Provisions 1x A100 SXM, runs the bench, tears the pod down on exit
(including on Ctrl-C). Requires `pip install runpod` (lazy-imported).

## Common errors

- **`nothing listening on localhost:8000`** — server not up. Start with
  `infergrid serve --config <flavor-config> --port 8000`.
- **`Model ... not found in /v1/models`** — your config doesn't include
  `meta-llama/Llama-3.1-8B-Instruct`; use a flavor config above.
- **`HTTP 503 on /health`** — vLLM still JIT-compiling. Wait 30-90 s.

Expected divergence: GPU not A100-SXM4, or vLLM build not `0.19.1`.
File an issue with `tenant_*.csv` attached if the published arm is 2x+
from reference on a matched A100 + `vllm==0.19.1`.
