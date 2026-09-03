#!/usr/bin/env bash
set -u -o pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=/usr/bin/python3
VIDEO=${VIDEO:-/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/train/Warehouse_000/videos/Camera_0000.mp4}
EXPECTED_FRAMES=${EXPECTED_FRAMES:-9000}
OUT="$ROOT/results/decode_preprocess_profiling"
PIPELINE="filesrc -> qtdemux -> h264parse -> nvv4l2decoder -> nvvidconv -> video/x-raw,format=BGRx,width=1920,height=1080 -> videoconvert -> video/x-raw,format=BGR,width=1920,height=1080 -> appsink sync=false"
mkdir -p "$OUT"

for streams in 1 2 4 8; do
  for run in 1 2 3; do
    log="$OUT/decode_preprocess_${streams}stream_run${run}.log"
    if [[ -e "$log" ]]; then
      echo "ERROR: refusing to overwrite existing raw log: $log" >&2
      exit 1
    fi
    {
      echo "Experiment: H.264 decode + RT-DETR preprocessing profiling"
      echo "Device: NVIDIA Jetson AGX Thor"
      echo "Power mode: MAXN / ID 0 (protocol setting; runner does not change or verify it)"
      echo "DVFS: enabled"
      echo "jetson_clocks: not used"
      echo "Git commit: $(git -C "$ROOT" rev-parse HEAD)"
      echo "Git branch: $(git -C "$ROOT" branch --show-current)"
      echo "Video: $VIDEO"
      echo "Codec: H.264 High Profile"
      echo "Resolution: 1920x1080"
      echo "Frame rate: 30 FPS"
      echo "Expected frames per stream: $EXPECTED_FRAMES"
      echo "Expected total frames: $((streams * EXPECTED_FRAMES))"
      echo "Actual pipeline: $PIPELINE"
      echo "Run: $run"
      echo "Streams: $streams"
      "$PYTHON" "$ROOT/scripts/profile_decode_preprocess.py" --video "$VIDEO" --streams "$streams" --expected-frames "$EXPECTED_FRAMES"
    } 2>&1 | tee "$log"
    status=${PIPESTATUS[0]}
    if (( status != 0 )); then exit "$status"; fi
  done
done
