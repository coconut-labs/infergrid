# Research Roadmap: InferGrid

> **Status update (April 2026):** Phase 1 profiling is complete. Several original hypotheses were refuted by data — see below. The thesis has been updated to reflect measured reality. See [Phase 1 Findings](docs/phase1_findings.md) for full results.

## Revised Thesis: Middleware-Level Admission Control and Multi-Model Lifecycle for LLM Inference

### What the data showed (Phase 1, April 2026)

| Original Claim | Measured Reality | Status |
|----------------|-----------------|--------|
| vLLM trails SGLang by 29% | <5% throughput gap (engines converged) | **Refuted** |
| 81.6% compound GPU waste | GPU utilization 95-99% across all configs | **Refuted** |
| Middleware scheduling reduces TTFT 50-70% | HTTP proxy cannot modify engine-internal scheduling | **Refuted** |
| Scheduling cliff at high concurrency | c=128→c=256: +2% throughput, +1434% TTFT | **Confirmed** |
| SGLang better at saturation | SGLang 2.2x better TTFT at c=256 vs vLLM | **Confirmed (new finding)** |
| Cliff is hardware-independent | Same pattern on A100 SXM and H100 SXM | **Confirmed** |

### Updated Problem Statement

The scheduling cliff is real, hardware-independent, and unmanaged by any existing tool. At concurrency >128 on an 80GB GPU, inference engines enter a regime where doubling load yields marginal throughput (+2%) at massive latency cost (+1434% TTFT). No existing system prevents requests from entering this regime.

Separately, no lightweight tool provides intelligent multi-model lifecycle management (load, evict, hot-swap based on traffic patterns) on bare metal without Kubernetes.

### System Design (unchanged)

Three components, one runtime:

1. **WorkloadRouter** — Admission control + frequency-based model lifecycle (not LRU)
2. **CacheManager** — KV cache lifecycle tracking (metadata layer; planned LMCache integration for cross-tier offloading)
3. **TenantManager** — Per-tenant resource budgets with request isolation

### Revised Experiments

- Benchmark 1: Admission control ON vs OFF at scheduling cliff (c=128, c=256)
- Benchmark 2: Multi-model serving (InferGrid vs manual 2x vLLM vs Ollama)
- Benchmark 3: Model switch latency and eviction policy effectiveness
- Benchmark 4: InferGrid proxy overhead measurement

### Timeline (revised)

| Phase | Activity | Status |
|-------|----------|--------|
| Phase 1 | Profile vLLM/SGLang on A100/H100 | **Complete** |
| Phase 2 | Build WorkloadRouter + admission control | **Complete** |
| Phase 3 | Multi-model GPU benchmark | **Next** |
| Phase 4 | arXiv preprint | Weeks 3-4 |
| Phase 5 | OSS launch (HN, Reddit) | Week 4 |

### Target

Primary: arXiv preprint + open-source launch. Fallback: MLSys 2027 submission.

### Baselines to Beat

- Manual multi-instance vLLM (2x vLLM with --gpu-memory-utilization 0.4)
- Ollama multi-model serving (LRU eviction)
- Direct engine (vLLM/SGLang) without admission control

### Key References

- Phase 1 profiling data: `results/` directory
- Gap analysis: `docs/inference_orchestration_gaps_report.md`
- Strategic analysis: `docs/strategic_analysis.md`
