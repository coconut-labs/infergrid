#!/usr/bin/env bash
# =============================================================================
# InferGrid — Idempotent GPU Environment Setup
# =============================================================================
# Sets up a fresh Lambda Labs A100 instance for profiling.
# Safe to re-run: every step checks before acting.
#
# Usage:
#   export HF_TOKEN=hf_...
#   bash scripts/setup_gpu_env.sh
#
# Requirements:
#   - NVIDIA GPU with driver installed (Lambda Labs provides this)
#   - Python 3.11+ (Lambda Labs system Python)
#   - HF_TOKEN environment variable for gated model access
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODEL_ID="meta-llama/Llama-3.1-8B-Instruct"
VLLM_PORT=8000
SGLANG_PORT=8001

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---- Step 0: Preflight checks ----

log_info "=========================================="
log_info "InferGrid GPU Environment Setup"
log_info "=========================================="

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    log_error "Python 3.11+ required, found $PYTHON_VERSION"
    exit 1
fi
log_ok "Python $PYTHON_VERSION"

# ---- Step 1: Check CUDA / GPU ----

log_info "Step 1: Checking CUDA & GPU..."

if ! command -v nvidia-smi &>/dev/null; then
    log_error "nvidia-smi not found. No NVIDIA driver installed."
    exit 1
fi

DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
GPU_MEMORY=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader | head -1)
GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l | tr -d ' ')

log_ok "Driver: $DRIVER_VERSION"
log_ok "GPU: $GPU_NAME ($GPU_MEMORY) x $GPU_COUNT"

# Log CUDA version if nvcc is available
if command -v nvcc &>/dev/null; then
    CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $6}' | tr -d ',')
    log_ok "CUDA: $CUDA_VERSION"
else
    log_warn "nvcc not found — CUDA toolkit not installed (driver-only is fine for inference)"
fi

# ---- Step 2: Install Python dependencies ----

log_info "Step 2: Installing Python dependencies..."

install_if_missing() {
    local package=$1
    local pip_name=${2:-$1}
    if python3 -c "import $package" &>/dev/null; then
        log_ok "$package already installed"
        return 0
    fi
    log_info "Installing $pip_name..."
    pip install --no-cache-dir "$pip_name"
}

# Core project deps
cd "$PROJECT_ROOT"

# Install the project itself with all optional deps
if pip show infergrid &>/dev/null; then
    log_ok "infergrid package already installed"
else
    log_info "Installing infergrid with all dependencies..."
    pip install --no-cache-dir -e ".[dev,profiling]"
fi

# Install inference engines
if pip show vllm &>/dev/null; then
    log_ok "vLLM already installed"
else
    log_info "Installing vLLM (this may take a few minutes)..."
    pip install --no-cache-dir vllm
fi

if pip show sglang &>/dev/null; then
    log_ok "SGLang already installed"
else
    log_info "Installing SGLang (this may take a few minutes)..."
    pip install --no-cache-dir "sglang[all]"
fi

# Ensure huggingface-cli is available
if ! command -v huggingface-cli &>/dev/null; then
    pip install --no-cache-dir huggingface_hub[cli]
fi

log_ok "All Python dependencies installed"

log_info "Locking dependency versions to requirements-lock.txt..."
pip freeze > requirements-lock.txt
log_ok "Dependencies locked"

# ---- Step 3: Download model ----

log_info "Step 3: Downloading model ($MODEL_ID)..."

if [[ -z "${HF_TOKEN:-}" ]]; then
    log_error "HF_TOKEN environment variable not set."
    log_error "Get a token at https://huggingface.co/settings/tokens"
    log_error "Then: export HF_TOKEN=hf_..."
    exit 1
fi

# Check if model is already cached
MODEL_CACHE_DIR="$HOME/.cache/huggingface/hub/models--$(echo "$MODEL_ID" | tr '/' '--')"
if [[ -d "$MODEL_CACHE_DIR" ]]; then
    log_ok "Model already cached at $MODEL_CACHE_DIR"
else
    log_info "Downloading $MODEL_ID (~16GB, this takes 5-10 minutes)..."
    huggingface-cli download "$MODEL_ID" --token "$HF_TOKEN"
    log_ok "Model downloaded successfully"
fi

# ---- Step 4: vLLM smoke test ----

log_info "Step 4: vLLM smoke test..."

# Kill any existing vLLM server
pkill -f "vllm.entrypoints" 2>/dev/null || true
sleep 2

log_info "Starting vLLM server on port $VLLM_PORT..."
python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_ID" \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.8 \
    --port "$VLLM_PORT" \
    &>/tmp/vllm_setup.log &
VLLM_PID=$!

# Wait for server to be healthy
log_info "Waiting for vLLM server to load model (up to 180s)..."
VLLM_READY=false
for i in $(seq 1 180); do
    if curl -s "http://localhost:$VLLM_PORT/v1/models" &>/dev/null; then
        VLLM_READY=true
        break
    fi
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
        log_error "vLLM server process died. Check /tmp/vllm_setup.log"
        cat /tmp/vllm_setup.log | tail -20
        exit 1
    fi
    sleep 1
    if (( i % 30 == 0 )); then
        log_info "  Still waiting... (${i}s elapsed)"
    fi
done

if [[ "$VLLM_READY" != "true" ]]; then
    log_error "vLLM server failed to start within 180s"
    kill "$VLLM_PID" 2>/dev/null || true
    exit 1
fi
log_ok "vLLM server is healthy"

# Send smoke test request
log_info "Sending vLLM smoke test request..."
VLLM_RESPONSE=$(curl -s "http://localhost:$VLLM_PORT/v1/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"$MODEL_ID\", \"prompt\": \"Hello, world!\", \"max_tokens\": 16}")

if echo "$VLLM_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('choices')" 2>/dev/null; then
    log_ok "vLLM smoke test passed"
else
    log_error "vLLM smoke test failed. Response: $VLLM_RESPONSE"
    kill "$VLLM_PID" 2>/dev/null || true
    exit 1
fi

# Shut down vLLM
log_info "Shutting down vLLM server..."
kill "$VLLM_PID" 2>/dev/null || true
wait "$VLLM_PID" 2>/dev/null || true
sleep 3

# ---- Step 5: SGLang smoke test ----

log_info "Step 5: SGLang smoke test..."

# Kill any existing SGLang server
pkill -f "sglang" 2>/dev/null || true
sleep 2

log_info "Starting SGLang server on port $SGLANG_PORT..."
python3 -m sglang.launch_server \
    --model-path "$MODEL_ID" \
    --dtype bfloat16 \
    --mem-fraction-static 0.8 \
    --port "$SGLANG_PORT" \
    --host 0.0.0.0 \
    &>/tmp/sglang_setup.log &
SGLANG_PID=$!

# Wait for server to be healthy
log_info "Waiting for SGLang server to load model (up to 180s)..."
SGLANG_READY=false
for i in $(seq 1 180); do
    if curl -s "http://localhost:$SGLANG_PORT/v1/models" &>/dev/null; then
        SGLANG_READY=true
        break
    fi
    if ! kill -0 "$SGLANG_PID" 2>/dev/null; then
        log_error "SGLang server process died. Check /tmp/sglang_setup.log"
        cat /tmp/sglang_setup.log | tail -20
        exit 1
    fi
    sleep 1
    if (( i % 30 == 0 )); then
        log_info "  Still waiting... (${i}s elapsed)"
    fi
done

if [[ "$SGLANG_READY" != "true" ]]; then
    log_error "SGLang server failed to start within 180s"
    kill "$SGLANG_PID" 2>/dev/null || true
    exit 1
fi
log_ok "SGLang server is healthy"

# Send smoke test request
log_info "Sending SGLang smoke test request..."
SGLANG_RESPONSE=$(curl -s "http://localhost:$SGLANG_PORT/v1/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"$MODEL_ID\", \"prompt\": \"Hello, world!\", \"max_tokens\": 16}")

if echo "$SGLANG_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('choices')" 2>/dev/null; then
    log_ok "SGLang smoke test passed"
else
    log_error "SGLang smoke test failed. Response: $SGLANG_RESPONSE"
    kill "$SGLANG_PID" 2>/dev/null || true
    exit 1
fi

# Shut down SGLang
log_info "Shutting down SGLang server..."
kill "$SGLANG_PID" 2>/dev/null || true
wait "$SGLANG_PID" 2>/dev/null || true

# ---- Done ----

log_info "=========================================="
log_ok "Environment setup complete!"
log_info "=========================================="
log_info ""
log_info "Summary:"
log_info "  Python:  $PYTHON_VERSION"
log_info "  Driver:  $DRIVER_VERSION"
log_info "  GPU:     $GPU_NAME ($GPU_MEMORY) x $GPU_COUNT"
log_info "  Model:   $MODEL_ID"
log_info "  vLLM:    $(pip show vllm 2>/dev/null | grep Version | awk '{print $2}')"
log_info "  SGLang:  $(pip show sglang 2>/dev/null | grep Version | awk '{print $2}')"
log_info ""
log_info "Next: bash scripts/run_all_baselines.sh"
