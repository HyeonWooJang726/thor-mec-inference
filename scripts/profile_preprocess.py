#!/usr/bin/env python3
"""Profile the verified RT-DETR preprocessing on an in-memory real frame."""

import argparse
import datetime
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from rtdetr_preprocess import preprocess_bgr


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True, help="Real Warehouse frame image")
    parser.add_argument("--streams", required=True, type=int)
    parser.add_argument("--iterations", type=int, default=9000, help="Frames per stream (default: 9000)")
    args = parser.parse_args()
    if args.streams < 1 or args.iterations < 1:
        parser.error("--streams and --iterations must be at least 1")
    return args


def git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def main():
    args = parse_args()
    frame_path = Path(args.frame).resolve()
    frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if frame is None:
        print(f"ERROR: failed to load input frame: {frame_path}", file=sys.stderr)
        return 1
    if frame.shape != (1080, 1920, 3) or frame.dtype != np.uint8:
        print(f"ERROR: expected uint8 BGR 1920x1080, got {frame.shape} {frame.dtype}", file=sys.stderr)
        return 1

    cv2.setNumThreads(1)
    check = preprocess_bgr(frame)
    if check.shape != (1, 3, 640, 640) or check.dtype != np.float32:
        print(f"ERROR: unexpected output tensor: {check.shape} {check.dtype}", file=sys.stderr)
        return 1

    start_barrier = threading.Barrier(args.streams + 1)
    counts = [0] * args.streams
    failures = []

    def worker(index):
        try:
            start_barrier.wait()
            output = None
            for _ in range(args.iterations):
                output = preprocess_bgr(frame)
            if output.shape != (1, 3, 640, 640) or output.dtype != np.float32:
                raise RuntimeError(f"unexpected output tensor: {output.shape} {output.dtype}")
            counts[index] = args.iterations
        except Exception as error:
            failures.append((index, str(error)))

    threads = [threading.Thread(target=worker, args=(i,), name=f"preprocess-{i}") for i in range(args.streams)]
    for thread in threads:
        thread.start()
    start_time = time.perf_counter()
    start_barrier.wait()
    for thread in threads:
        thread.join()
    end_time = time.perf_counter()

    if failures:
        for index, error in failures:
            print(f"ERROR stream={index}: {error}", file=sys.stderr)
        return 1

    elapsed = end_time - start_time
    total_frames = sum(counts)
    aggregate_fps = total_frames / elapsed
    per_stream_fps = aggregate_fps / args.streams
    print(f"streams: {args.streams}")
    print(f"iterations per stream: {args.iterations}")
    for index, count in enumerate(counts):
        print(f"stream {index} processed frames: {count}")
    print(f"total processed frames: {total_frames}")
    print(f"elapsed time [s]: {elapsed:.6f}")
    print(f"aggregate preprocessing throughput [frames/s]: {aggregate_fps:.3f}")
    print(f"per-stream average throughput [frames/s]: {per_stream_fps:.3f}")
    print("concurrency: one Python thread per stream; OpenCV internal threads=1")
    print(f"timestamp: {datetime.datetime.now().astimezone().isoformat()}")
    print(f"git commit: {git_commit()}")
    print(f"input frame: {frame_path} (real Warehouse Camera_0000 frame, loaded before timer)")
    print("timer semantics: barrier release to completion of all preprocessing iterations; frame loading and validation excluded")
    print("output tensor: shape=1x3x640x640 dtype=float32 layout=NCHW")
    print(
        f"RESULT streams={args.streams} total_frames={total_frames} elapsed_s={elapsed:.6f} "
        f"aggregate_fps={aggregate_fps:.3f} per_stream_fps={per_stream_fps:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
