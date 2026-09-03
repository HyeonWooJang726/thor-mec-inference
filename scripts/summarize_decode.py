#!/usr/bin/env python3
"""Validate decode raw logs and regenerate the tracked derived results."""

import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "decode_profiling"
STREAMS = (1, 4, 8)
RUNS = (1, 2, 3)


def field(text, pattern, label, cast=str):
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing {label}")
    return cast(match.group(1))


def parse_log(streams, run):
    path = RESULTS / f"decode_{streams}stream_run{run}.log"
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed_streams = field(text, r"^streams:\s*(\d+)\s*$", "streams", int)
    result = field(text, r"^RESULT\s+(.+)$", "RESULT")
    pairs = dict(re.findall(r"(\w+)=([^\s]+)", result))
    frames = {int(i): int(n) for i, n in re.findall(r"^stream (\d+) decoded frames:\s*(\d+)\s*$", text, re.MULTILINE)}
    eos = {int(i): value for i, value in re.findall(r"^stream (\d+) EOS:\s*(\w+)\s*$", text, re.MULTILINE)}
    expected_total = streams * 9000
    if parsed_streams != streams or int(pairs["streams"]) != streams:
        raise ValueError(f"{path}: streams mismatch")
    if frames != {i: 9000 for i in range(streams)}:
        raise ValueError(f"{path}: per-stream frame validation failed: {frames}")
    if eos != {i: "yes" for i in range(streams)}:
        raise ValueError(f"{path}: EOS validation failed: {eos}")
    total = field(text, r"^total decoded frames:\s*(\d+)\s*$", "total frames", int)
    if total != expected_total or int(pairs["total_frames"]) != expected_total:
        raise ValueError(f"{path}: total frame validation failed: {total}")
    return {
        "streams": streams,
        "run": run,
        "total_frames": total,
        "elapsed_s": float(pairs["elapsed_s"]),
        "aggregate_fps": float(pairs["aggregate_fps"]),
        "per_stream_fps": float(pairs["per_stream_fps"]),
        "source_log": path.relative_to(ROOT).as_posix(),
        "git_commit": field(text, r"^git commit:\s*(\S+)\s*$", "git commit"),
        "timestamp": field(text, r"^timestamp:\s*(\S+)\s*$", "timestamp"),
    }


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = [parse_log(streams, run) for streams in STREAMS for run in RUNS]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["streams"]].append(row)
    summary = []
    baseline = statistics.mean(row["aggregate_fps"] for row in grouped[1])
    for streams in STREAMS:
        group = grouped[streams]
        fps = [row["aggregate_fps"] for row in group]
        mean_fps = statistics.mean(fps)
        std_fps = statistics.stdev(fps)
        summary.append({
            "streams": streams,
            "run_count": len(group),
            "mean_elapsed_s": statistics.mean(row["elapsed_s"] for row in group),
            "mean_aggregate_fps": mean_fps,
            "std_aggregate_fps": std_fps,
            "cv_aggregate_fps_percent": std_fps / mean_fps * 100,
            "mean_per_stream_fps": statistics.mean(row["per_stream_fps"] for row in group),
            "scaling_vs_1stream": mean_fps / baseline,
        })
    write_csv(RESULTS / "formal_runs.csv", list(rows[0]), rows)
    write_csv(RESULTS / "summary.csv", list(summary[0]), summary)

    plt.figure(figsize=(6.4, 4.2))
    plt.plot(STREAMS, [row["mean_aggregate_fps"] for row in summary], "o-")
    plt.xticks(STREAMS)
    plt.xlabel("Number of streams")
    plt.ylabel("Aggregate throughput (frames/s)")
    plt.title("H.264 Decode Pipeline Throughput")
    plt.grid(alpha=.3)
    plt.tight_layout()
    figure = RESULTS / "figures" / "aggregate_throughput_vs_streams.png"
    figure.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(figure, dpi=160, bbox_inches="tight")
    plt.close()

    table_runs = [
        "| Streams | Run | Frames | Elapsed s | Aggregate fps | Per-stream fps |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table_runs.append(f"| {row['streams']} | {row['run']} | {row['total_frames']} | {row['elapsed_s']:.6f} | {row['aggregate_fps']:.3f} | {row['per_stream_fps']:.3f} |")
    table_summary = [
        "| Streams | Runs | Mean elapsed s | Mean aggregate fps | Sample std fps | CV % | Mean per-stream fps | Scaling vs 1 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        table_summary.append(f"| {row['streams']} | {row['run_count']} | {row['mean_elapsed_s']:.6f} | {row['mean_aggregate_fps']:.3f} | {row['std_aggregate_fps']:.3f} | {row['cv_aggregate_fps_percent']:.3f} | {row['mean_per_stream_fps']:.3f} | {row['scaling_vs_1stream']:.3f}x |")
    readme = f"""# H.264 decode pipeline profiling

Summary schema version: 1  
Generated by: `scripts/summarize_decode.py`  
Raw logs are the source of truth.

## Experiment purpose

NVIDIA Jetson AGX Thor에서 maximum-speed H.264 decode pipeline의 aggregate wall-clock throughput을 streams 수에 따라 characterization한다.

## Exact protocol

Power mode는 MAXN / ID 0, DVFS enabled, `jetson_clocks` 미사용 조건이다. streams={{1,4,8}}마다 3 runs를 수행했고, 모든 pipeline을 가능한 한 함께 PLAYING으로 전환한 시점부터 all-stream EOS까지 `time.perf_counter()`로 측정했다. 각 run은 stream당 9000 frames와 EOS를 검증했다.

## Pipeline

`filesrc -> qtdemux -> h264parse -> nvv4l2decoder -> fakesink` (`sync=false`). 이는 pure `nvv4l2decoder` execution time이 아니라 전체 decode pipeline의 maximum-speed wall-clock throughput이다.

## Input workload

H.264 High Profile, 1920x1080, 30 FPS, 300 s인 Warehouse_000의 `Camera_0000.mp4`를 사용했다. 동일한 Camera_0000 영상을 여러 independent pipelines에 replicate한 controlled workload이며, 서로 다른 4개/8개 camera video 실험이 아니다. 현재 Warehouse_000 local video set에서는 이 실험에 Camera_0000.mp4를 사용했다.

## Raw run results

{chr(10).join(table_runs)}

모든 9 runs에서 각 stream=9000 frames, expected total frames 및 각 stream EOS=yes가 검증되었다.

## Mean/std/CV summary

{chr(10).join(table_summary)}

표준편차는 3개 run의 sample standard deviation (`statistics.stdev`, n-1), CV는 `sample std / mean × 100`이다.

![Aggregate throughput vs streams](figures/aggregate_throughput_vs_streams.png)

## Scaling interpretation

1→4 streams에서 mean aggregate throughput이 증가한다. 4→8 streams에서는 aggregate throughput 증가가 거의 없는 plateau가 관찰된다. 이 결과만으로 `nvv4l2decoder` hardware 자체가 bottleneck이라고 단정할 수 없다.

## Limitations

이 controlled replicated-input 결과는 서로 다른 camera 입력의 동시 처리 결과가 아니다. file I/O, demux, parsing, memory subsystem, decoder resource sharing 중 어느 요소가 정확한 병목인지는 이 실험만으로 알 수 없다. 측정 범위에는 pipeline startup과 all-stream completion imbalance가 포함되며 pure NVDEC internal latency를 제공하지 않는다.
"""
    (RESULTS / "README.md").write_text(readme, encoding="utf-8")
    print("validated_runs=9 frame_and_eos_validation=passed")


if __name__ == "__main__":
    main()
