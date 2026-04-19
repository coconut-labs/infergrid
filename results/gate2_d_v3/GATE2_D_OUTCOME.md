# Gate 2 D — Multi-model OOM-under-burst — Outcome

**Date:** 2026-04-19
**Hardware:** A100-SXM4 80GB (Pod 6 for D1, fresh Pod 7 for D2 after Pod 6 cross-arm CUDA leak)
**Software:** vLLM 0.19.1, InferGrid main @ post-PR-#64
**Bench:** `benchmarks/scripts/benchmark_chat_rag_burst.py` — chat steady 5 RPS on Llama-3.1-8B, RAG bursts 3× (15 RPS / 30 s) on Qwen-2.5-7B with 4K-token prompts
**Spend:** ~$1.50 (Pod 6 D1 + Pod 7 D2)

## Headline — pre-committed null rule applies

Both arms ran 300 s on co-loaded Llama+Qwen with the same chat+RAG burst pattern:

| Arm | Config | CHAT p99 | RAG p99 | OOM count |
|---|---|---:|---:|---:|
| D1 (InferGrid full stack) | `gate2_multi_tenant.yaml` | 1,552 ms | 29,343 ms | 0 |
| D2 (round-robin proxy)    | `gate2_round_robin.yaml`   | 1,160 ms | 100,330 ms | 0 |

**Neither arm OOM'd.** The hypothesis "InferGrid's admission prevents OOM that
round-robin can't catch" is **not testable from this workload** because the
workload doesn't actually push either configuration into OOM territory. With
Llama at 0.40 GPU memory + Qwen at 0.40 GPU memory + headroom, both engines
fit comfortably and bursts get queued, not rejected.

Per the pre-committed null rule (god-planner sprint plan, 2026-04-19):
**Track D is cut from the launch post.** No honest OOM-prevention claim is
possible from this data; airing a null result weakens, not strengthens, the
launch narrative.

## What we DID find (preserved for the post-launch roadmap)

D1 admission throttled the RAG tail at 30 s (the bench's 120 s timeout,
reached after 30 s of queue wait). D2 round-robin lets RAG queue grow to
100 s before the same timeout fires. So:

- **InferGrid bounds tail latency more aggressively** (D1's 30s vs D2's 100s on RAG p99)
- **Round-robin's chat is marginally faster** (D2 1,160 ms vs D1 1,552 ms — admission overhead = ~400ms p99 cost in this workload shape)

Net for chat-tenant protection: the configurations are within ~25% of each other.
Neither is dramatically better at protecting chat from RAG bursts. Both arms
saw identical chat error counts (0) and identical chat throughput (n=1494).

## Why the experiment was inconclusive

The bench dimensions chose for "OOM under burst" don't actually push the engine
into OOM. Llama-8B at 0.40 GPU mem util ≈ 32 GB; Qwen-7B at 0.40 ≈ 32 GB; total
64 GB on an 80 GB A100 leaves 16 GB for KV cache + activations. The 4K-token RAG
prompts at 15 RPS for 30 s would need ~450 simultaneous in-flight RAG requests
to OOM the KV cache; the bench peaks at ~150 in-flight (15 RPS × 10s avg latency)
during a burst. Headroom 3×.

To actually test OOM-prevention, the bench would need either:
- Larger models (e.g., Llama-70B + Qwen-32B), filling the GPU closer to limit
- Longer context (e.g., 16K-token RAG prompts)
- Higher burst intensity (e.g., 30+ RPS)

The original Pod 6 D1 → D2 transition DID hit OOM (Pod 6 nvidia-smi showed
66 GB held by D1's lingering CUDA context, D2 engines failed to allocate at
boot). That OOM is real but it's a vLLM cross-restart cleanup issue, not a
within-bench burst issue. CORRECTIONS C8 documents the pod-level workaround
(separate pod per arm).

## Decision

- **Cut Track D from the launch post.** No false claims about OOM-prevention.
- **Add to post-launch roadmap:** rerun with larger models (Llama-70B + Qwen-32B
  on a 2× A100 pod) where co-load actually approaches GPU limits. Budget:
  ~$10, ~30 min.
- **Keep the bench script** (`benchmarks/scripts/benchmark_chat_rag_burst.py`) — it's
  the right shape, just needs bigger models to provoke the failure mode it tests.

## Raw artifacts

- `results/gate2_d_v3/gate2_d_20260419_205528/d1_inferGrid_*/` — D1 from Pod 6
- `results/gate2_d_v3/gate2_d_d2only_20260419_212123/` — D2 from fresh Pod 7
- `results/gate2_d_v3/gate2_d_20260419_205528/d2_roundRobin_*/server.log` — Pod 6 D2 OOM evidence (engines failed to start under residual CUDA context)
