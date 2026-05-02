#!/bin/bash
# Drive 6 cells (A1-A3 FIFO, B1-B3 TokenBucket) on a warm pod.
# Caller exports POD_HOST, POD_PORT, RESULTS_LOCAL_DIR, HF_TOKEN.
# Optional: FLOODER_RPS (default 128), DURATION_S (default 300).
#
# Sources scripts/_gate21b_orchestrator.sh which defines run_cell.
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_gate21b_orchestrator.sh"

FLOODER_RPS="${FLOODER_RPS:-128}"
DURATION_S="${DURATION_S:-300}"
COST_PER_HR="${COST_PER_HR:-2.99}"
COST_CAP_USD="${COST_CAP_USD:-4.50}"
SUNK_USD="${SUNK_USD:-0.74}"   # default carries forward attempts #1 + #2
RUN_START_EPOCH=$(date +%s)
declare -a FAILED_CELLS=()

cost_check() {
  local now=$(date +%s)
  local elapsed_s=$(( now - RUN_START_EPOCH ))
  local pod_cost=$(python3 -c "print(${elapsed_s}/3600.0 * ${COST_PER_HR})")
  local total_cost=$(python3 -c "print(${SUNK_USD} + ${pod_cost})")
  echo "[cost] elapsed=${elapsed_s}s pod_cost=\$$pod_cost total=\$$total_cost cap=\$$COST_CAP_USD"
  if python3 -c "import sys; sys.exit(0 if ${total_cost} >= ${COST_CAP_USD} else 1)"; then
    echo "[cost] ABORT: total cost \$$total_cost >= cap \$$COST_CAP_USD"
    return 1
  fi
  return 0
}

cells=(
  "cellA_seed0:configs/gate21b_fifo_n8.yaml:0"
  "cellA_seed1:configs/gate21b_fifo_n8.yaml:1"
  "cellA_seed2:configs/gate21b_fifo_n8.yaml:2"
  "cellB_seed0:configs/gate21b_tokenbucket_n8.yaml:0"
  "cellB_seed1:configs/gate21b_tokenbucket_n8.yaml:1"
  "cellB_seed2:configs/gate21b_tokenbucket_n8.yaml:2"
)

for spec in "${cells[@]}"; do
  IFS=":" read -r CELL CFG SEED <<< "$spec"
  if ! cost_check; then
    echo "[run_all] cost cap hit before $CELL; breaking"
    FAILED_CELLS+=("$CELL (cost-cap)")
    break
  fi
  echo "[run_all] starting $CELL"
  if ! run_cell "$CELL" "$CFG" "$SEED" "$FLOODER_RPS" "$DURATION_S"; then
    FAILED_CELLS+=("$CELL")
    echo "[run_all] $CELL FAILED — continuing"
  fi
done

if [ ${#FAILED_CELLS[@]} -gt 0 ]; then
  echo "[run_all] FAILED CELLS: ${FAILED_CELLS[*]}"
  exit 1
fi
echo "[run_all] all 6 cells DONE"
