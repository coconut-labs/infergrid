# Phase 1 Findings: Scheduling Overhead

*Generated: 2026-04-16 20:50 UTC*

This document presents Phase 1 profiling results measuring scheduling overhead 
in vLLM and SGLang across multiple models including dense and MoE architectures.

## Model: Llama-3.1-8B-Instruct

- **Hardware:** NVIDIA A100-SXM4-80GB
- **Driver:** 580.126.16
- **Model ID:** meta-llama/Llama-3.1-8B-Instruct
- **Workload:** TODO
- **Concurrency sweep:** 1,8,32,64,128,256
- **Requests per level:** 200
- **Timestamp:** 2026-04-16T18:33:05Z

### Tools
- py-spy: flame graph generation (SVG + speedscope)
- pynvml: GPU monitoring
- Custom async benchmark client

### Throughput Comparison (tokens/second)

| Concurrency | vLLM | SGLang | Gap (%) |
|-------------|------|--------|---------|
| — | No data | — | — |

### Latency Comparison (TTFT p50/p99, ms)

| Concurrency | vLLM TTFT p50 | vLLM TTFT p99 | SGLang TTFT p50 | SGLang TTFT p99 |
|-------------|---------------|---------------|-----------------|-----------------|
| — | No data | — | — | — |

#### TPOT Comparison (ms)

| Concurrency | vLLM TPOT p50 | SGLang TPOT p50 |
|-------------|---------------|-----------------|
| — | No data | — |

### GPU Utilization Patterns

| Concurrency | vLLM Util % | SGLang Util % | Delta |
|-------------|-------------|---------------|-------|
| — | No data | — | — |

## Cross-Model Comparison

Shows throughput (tok/s) across models and engines for identical concurrency levels.

| Concurrency | Model | vLLM (tok/s) | SGLang (tok/s) |
|-------------|-------|--------------|----------------|

## Identified Intervention Points for WorkloadRouter

### Priority 1: Batch Construction Optimization
- **Problem:** Construction padding waste.
- **Intervention:** Pre-sort requests by estimated length.

### Priority 2: KV Cache Pre-allocation
- **Intervention:** Predict KV cache requirements at routing time.

### Priority 3: Asynchronous Scheduling Pipeline
- **Intervention:** Pipeline scheduling with GPU execution.
