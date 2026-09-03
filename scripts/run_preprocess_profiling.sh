#!/usr/bin/env bash
set -u -o pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=/usr/bin/python3
FRAME=${FRAME:-"$ROOT/results/correctness/Camera_0000_t60.png"}
ITERATIONS=${ITERATIONS:-9000}
OUT="$ROOT/results/preprocess_profiling"
mkdir -p "$OUT"

for streams in 1 8; do
  for run in 1 2 3; do
    log="$OUT/preprocess_${streams}stream_run${run}.log"
    if [[ -e "$log" ]]; then
      echo "ERROR: refusing to overwrite existing raw log: $log" >&2
      exit 1
    fi
    {
      echo "Experiment: RT-DETR preprocessing-only profiling"
      echo "Device: NVIDIA Jetson AGX Thor"
      echo "Power mode: MAXN / ID 0 (protocol setting; runner does not change or verify it)"
      echo "DVFS: enabled"
      echo "jetson_clocks: not used"
      echo "Git commit: $(git -C "$ROOT" rev-parse HEAD)"
      echo "Git branch: $(git -C "$ROOT" branch --show-current)"
      echo "Input frame: $FRAME"
      echo "Input description: real Warehouse Camera_0000 frame replicated across independent workloads"
      echo "Streams: $streams"
      echo "Run: $run"
      echo "Iterations per stream: $ITERATIONS"
      "$PYTHON" "$ROOT/scripts/profile_preprocess.py" --frame "$FRAME" --streams "$streams" --iterations "$ITERATIONS"
    } 2>&1 | tee "$log"
    status=${PIPESTATUS[0]}
    if (( status != 0 )); then exit "$status"; fi
  done
done
