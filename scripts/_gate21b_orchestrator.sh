#!/bin/bash
# Gate 2.1b master orchestrator (run from laptop, NOT on the pod).
# - SSH into the pod, scp env+bootstrap, sed-patch bootstrap to clone our branch
#   (so the gate21b configs are visible).
# - For each cell, kick off bootstrap with the right config + bench args.
# - Poll for _DONE / _FAILED, rsync results.
# - Side-poll /metrics every 1s for engine_metrics.csv (saturation detection).
#
# Required env (caller exports):
#   POD_HOST   pod IP
#   POD_PORT   ssh port
#   BRANCH     git branch on coconut to clone (default results/gate21b-...)
#   RESULTS_LOCAL_DIR  local dir to rsync into (results/gate21b_h100_saturation_20260502)
#   HF_TOKEN   for the pod env
#
# Cell matrix (loop in caller):
#   A1 / A2 / A3  -> configs/gate21b_fifo_n8.yaml,        seeds 0/1/2
#   B1 / B2 / B3  -> configs/gate21b_tokenbucket_n8.yaml, seeds 0/1/2
set -u
set -o pipefail

POD_HOST="${POD_HOST:?POD_HOST required}"
POD_PORT="${POD_PORT:?POD_PORT required}"
BRANCH="${BRANCH:-results/gate21b-h100-saturation-20260502}"
RESULTS_LOCAL_DIR="${RESULTS_LOCAL_DIR:?RESULTS_LOCAL_DIR required}"
HF_TOKEN="${HF_TOKEN:?HF_TOKEN required}"

SSH="ssh -p $POD_PORT -i $HOME/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@$POD_HOST"
SCP="scp -P $POD_PORT -i $HOME/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

mkdir -p "$RESULTS_LOCAL_DIR"

ssh_with_retry() {
  local n=0
  until $SSH "$@" 2>/dev/null; do
    n=$((n+1))
    [ $n -ge 10 ] && return 1
    sleep 5
  done
}

echo "[orch] pushing env + bootstrap"
printf 'export HF_TOKEN=%q\nexport MAX_POD_SECS=7200\n' "$HF_TOKEN" \
  | $SSH 'cat > /root/.gate_env'

# Patch the bootstrap clone command to use our branch (configs/gate21b_*.yaml live there).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
sed -e "s|--branch main --depth 1|--branch ${BRANCH} --depth 1|" \
    "$SCRIPT_DIR/gate_pod_bootstrap.sh" \
  > "$TMPDIR/gate_pod_bootstrap_patched.sh"

if ! grep -q "git clone --branch ${BRANCH}" "$TMPDIR/gate_pod_bootstrap_patched.sh"; then
  echo "[orch] FATAL: sed patch did not produce expected branch line"
  grep "git clone" "$TMPDIR/gate_pod_bootstrap_patched.sh" || true
  exit 2
fi
$SCP "$TMPDIR/gate_pod_bootstrap_patched.sh" "root@$POD_HOST:/workspace/gate_pod_bootstrap.sh"

echo "[orch] verifying SSH + GPU"
$SSH 'mkdir -p /workspace; nvidia-smi -L; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader'

run_cell() {
  local CELL_NAME="$1"   # e.g. cellA_seed0
  local CONFIG="$2"      # e.g. configs/gate21b_fifo_n8.yaml
  local SEED="$3"
  local FLOODER_RPS="$4"
  local DURATION_S="$5"

  local RUN_NAME="gate21b_${CELL_NAME}_$(date -u +%Y%m%d_%H%M%S)"
  echo "[orch] === $RUN_NAME (config=$CONFIG seed=$SEED flooder_rps=$FLOODER_RPS) ==="

  # Launch bootstrap (blocks the SSH session via background nohup).
  local BENCH_ARGS="--url http://localhost:8000 --model meta-llama/Llama-3.1-8B-Instruct --flooder-rps ${FLOODER_RPS} --quiet-rps 1 --num-quiet 7 --duration-s ${DURATION_S} --max-tokens 128 --output-dir RDIR/benchmarks --seed ${SEED}"

  $SSH "rm -f /workspace/${RUN_NAME}_DONE /workspace/${RUN_NAME}_FAILED; \
        nohup bash /workspace/gate_pod_bootstrap.sh \
          --run-name ${RUN_NAME} \
          --config ${CONFIG} \
          --bench-script benchmarks/scripts/benchmark_n_tenant_single_model.py \
          --bench-args '${BENCH_ARGS}' \
          > /workspace/bootstrap_${RUN_NAME}.console 2>&1 & disown"

  # Wait for the bootstrap to reach Phase 7 (bench start) - phase_7.ts marker.
  echo "[orch]   waiting for bench-start marker (phase_7.ts)..."
  local READY=0
  for i in $(seq 1 80); do
    sleep 10
    if $SSH "test -f /workspace/results/${RUN_NAME}/phase_7.ts" 2>/dev/null; then
      READY=1
      echo "[orch]   bench started after $((i*10))s"
      break
    fi
    if $SSH "test -f /workspace/${RUN_NAME}_FAILED" 2>/dev/null; then
      echo "[orch]   bootstrap FAILED before bench"
      break
    fi
  done

  if [ "$READY" != "1" ]; then
    echo "[orch]   engine never reached bench-start; aborting cell $CELL_NAME"
    return 1
  fi

  # Side-poll /metrics every 1s for saturation detection.
  local METRICS_LOCAL="$RESULTS_LOCAL_DIR/${CELL_NAME}_engine_metrics.csv"
  echo "ts_unix,num_requests_running,num_requests_waiting" > "$METRICS_LOCAL"
  $SSH "rm -f /workspace/${RUN_NAME}_metrics.csv; \
        nohup bash -c 'for i in \$(seq 1 $((DURATION_S + 60))); do \
          ts=\$(date +%s); \
          R=\$(curl -sf http://localhost:8000/metrics 2>/dev/null | grep -E \"^vllm:num_requests_running\" | tail -1 | awk \"{print \\\$2}\"); \
          W=\$(curl -sf http://localhost:8000/metrics 2>/dev/null | grep -E \"^vllm:num_requests_waiting\" | tail -1 | awk \"{print \\\$2}\"); \
          echo \"\$ts,\${R:-NaN},\${W:-NaN}\" >> /workspace/${RUN_NAME}_metrics.csv; \
          sleep 1; \
        done' > /dev/null 2>&1 & disown"

  # Wait for _DONE or _FAILED with a hard cap (wait up to DURATION_S + 600s).
  local DEADLINE=$((DURATION_S + 600))
  local DONE=0
  for i in $(seq 1 $((DEADLINE / 10))); do
    sleep 10
    if $SSH "test -f /workspace/${RUN_NAME}_DONE" 2>/dev/null; then
      DONE=1
      echo "[orch]   _DONE after $((i*10))s"
      break
    fi
    if $SSH "test -f /workspace/${RUN_NAME}_FAILED" 2>/dev/null; then
      echo "[orch]   _FAILED marker present"
      break
    fi
  done

  # Always pull metrics CSV + console.
  $SCP "root@$POD_HOST:/workspace/${RUN_NAME}_metrics.csv" "$METRICS_LOCAL.tmp" 2>/dev/null \
    && tail -n +1 "$METRICS_LOCAL.tmp" >> "$METRICS_LOCAL" \
    && rm -f "$METRICS_LOCAL.tmp"
  $SCP "root@$POD_HOST:/workspace/bootstrap_${RUN_NAME}.console" "$RESULTS_LOCAL_DIR/${CELL_NAME}.console" 2>/dev/null || true

  # Pull the tarball if available.
  $SCP "root@$POD_HOST:/workspace/${RUN_NAME}_results.tar.gz" "$RESULTS_LOCAL_DIR/${CELL_NAME}.tar.gz" 2>/dev/null || true

  if [ "$DONE" != "1" ]; then
    echo "[orch]   cell $CELL_NAME did NOT finish; pod-side processes killed"
    $SSH "pkill -9 -f 'kvwarden serve' 2>/dev/null; pkill -9 -f vllm 2>/dev/null; pkill -9 -f gate_pod_bootstrap 2>/dev/null" || true
    return 1
  fi

  # Kill the kvwarden+vllm process to clean state for the next cell (no hot-reload).
  echo "[orch]   tearing down engine for next cell"
  $SSH "pkill -9 -f 'kvwarden serve' 2>/dev/null; pkill -9 -f vllm 2>/dev/null; sleep 5; pkill -9 -f vllm 2>/dev/null || true"
  sleep 10
  return 0
}

# Caller invokes run_cell() per cell; this script is sourced as a library.
