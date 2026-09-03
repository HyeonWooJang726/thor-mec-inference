#!/usr/bin/env python3
"""기존 TensorRT raw log를 파싱해 연구 결과 요약물을 재생성한다."""

from __future__ import annotations

import csv
import hashlib
import re
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SUMMARY_MARKER = "=== Performance summary ==="

METRIC_COLUMNS = [
    "batch", "run", "throughput_qps", "effective_throughput_img_s",
    "host_latency_mean_ms", "host_latency_p95_ms", "host_latency_p99_ms",
    "enqueue_mean_ms", "h2d_mean_ms", "gpu_compute_mean_ms",
    "gpu_compute_p95_ms", "gpu_compute_p99_ms", "d2h_mean_ms",
    "gpu_compute_cv_percent", "source_file",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def metadata_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    return match.group(1) if match else None


def last_summary(text: str) -> str:
    if SUMMARY_MARKER not in text:
        raise ValueError("final Performance summary가 없음")
    return text.rsplit(SUMMARY_MARKER, 1)[1]


def number(pattern: str, text: str, label: str) -> float:
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"{label}을 final Performance summary에서 찾을 수 없음")
    return float(match.group(1))


def metric_line(summary: str, label: str) -> str:
    # timestamp/logger prefix 뒤의 metric label 전체가 정확히 일치해야 한다.
    match = re.search(rf"(?m)^(?:\[[^\]\n]+\]\s*)*{re.escape(label)}:\s*(.+)$", summary)
    if not match:
        raise ValueError(f"{label} line을 final Performance summary에서 찾을 수 없음")
    return match.group(1)


def stat(line: str, name: str) -> float:
    patterns = {
        "mean": r"\bmean\s*=\s*([0-9.]+)",
        "p95": r"percentile\(95%\)\s*=\s*([0-9.]+)",
        "p99": r"percentile\(99%\)\s*=\s*([0-9.]+)",
    }
    match = re.search(patterns[name], line)
    if not match:
        raise ValueError(f"{name} 값을 찾을 수 없음: {line}")
    return float(match.group(1))


def parse_performance(path: Path, batch: int, run: int) -> dict[str, object]:
    text = read_text(path)
    summary = last_summary(text)
    # 마지막 summary 이후 성공 marker가 있어야 formal 성공 run으로 인정한다.
    if "&&&& PASSED TensorRT.trtexec" not in summary:
        raise ValueError(f"{path}: final summary 이후 PASSED marker가 없음")
    host = metric_line(summary, "Latency")
    enqueue = metric_line(summary, "Enqueue Time")
    h2d = metric_line(summary, "H2D Latency")
    gpu = metric_line(summary, "GPU Compute Time")
    d2h = metric_line(summary, "D2H Latency")
    qps = number(r"(?m)^.*\bThroughput:\s*([0-9.]+)\s+qps", summary, "Throughput")
    cv_match = re.search(r"coefficient of variance\s*=\s*([0-9.]+)%", summary)
    return {
        "batch": batch,
        "run": run,
        "throughput_qps": qps,
        "effective_throughput_img_s": qps * batch,
        "host_latency_mean_ms": stat(host, "mean"),
        "host_latency_p95_ms": stat(host, "p95"),
        "host_latency_p99_ms": stat(host, "p99"),
        "enqueue_mean_ms": stat(enqueue, "mean"),
        "h2d_mean_ms": stat(h2d, "mean"),
        "gpu_compute_mean_ms": stat(gpu, "mean"),
        "gpu_compute_p95_ms": stat(gpu, "p95"),
        "gpu_compute_p99_ms": stat(gpu, "p99"),
        "d2h_mean_ms": stat(d2h, "mean"),
        "gpu_compute_cv_percent": float(cv_match.group(1)) if cv_match else None,
        "source_file": path.relative_to(ROOT).as_posix(),
    }


def discover_formal_runs() -> list[dict[str, object]]:
    rows = []
    for path in sorted(RESULTS.rglob("*.log")):
        text = read_text(path)
        experiment = metadata_value(text, "Experiment")
        batch_match = re.search(r"(?m)^(?:Batch|Shape):\s*(?:batch=)?(\d+)(?:x3x640x640)?\s*$", text)
        run_match = re.search(r"(?m)^Run:\s*(\d+)\s*$", text)
        if not batch_match or not run_match:
            continue
        batch = int(batch_match.group(1))
        run = int(run_match.group(1))
        is_batch_formal = (
            path.parent == RESULTS / "batch_profiling"
            and experiment == "RT-DETR isolated batch profiling"
            and "NV Power Mode: MAXN" in text
            and batch in {2, 4, 8}
        )
        is_b1_formal = (
            path.parent == RESULTS / "power_calibration"
            and experiment == "RT-DETR isolated inference"
            and batch == 1
            and "NV Power Mode: MAXN" in text
        )
        if is_batch_formal or is_b1_formal:
            running_match = re.search(r"(?m)^&&&& RUNNING TensorRT\.trtexec .+$", text)
            if not running_match:
                raise ValueError(f"{path}: trtexec invocation을 찾을 수 없음")
            invocation = running_match.group(0)
            if "--warmUp=2000" not in invocation or "--duration=30" not in invocation:
                raise ValueError(f"{path}: formal warm-up/duration 조건 불일치")
            if "jetson_clocks: not used" not in text:
                raise ValueError(f"{path}: jetson_clocks OFF를 log에서 확인할 수 없음")
            if not re.search(r"(?m)^.*\[I\] CUDA Graph: Disabled\s*$", text):
                raise ValueError(f"{path}: CUDA Graph OFF를 runtime log에서 확인할 수 없음")
            if not re.search(r"(?m)^.*\[I\] Inference Streams: 1\s*$", text):
                raise ValueError(f"{path}: inference streams=1을 runtime log에서 확인할 수 없음")
            if "--useCudaGraph" in invocation or "--useSpinWait" in invocation:
                raise ValueError(f"{path}: formal command에 CUDA Graph 또는 SpinWait option이 있음")
            rows.append(parse_performance(path, batch, run))
    rows.sort(key=lambda row: (int(row["batch"]), int(row["run"])))
    counts = {batch: sum(int(row["batch"]) == batch for row in rows) for batch in (1, 2, 4, 8)}
    if counts != {1: 3, 2: 3, 4: 3, 8: 3}:
        raise ValueError(f"formal run count 불일치: {counts}")
    return rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})


def summarize_formal(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["batch"])].append(row)
    result = []
    for batch in sorted(grouped):
        group = grouped[batch]
        qps = [float(row["throughput_qps"]) for row in group]
        mean = lambda key: statistics.mean(float(row[key]) for row in group)
        result.append({
            "batch": batch,
            "run_count": len(group),
            "throughput_qps_mean": statistics.mean(qps),
            "effective_throughput_img_s_mean": mean("effective_throughput_img_s"),
            "host_latency_mean_ms": mean("host_latency_mean_ms"),
            "host_latency_p95_ms_mean": mean("host_latency_p95_ms"),
            "host_latency_p99_ms_mean": mean("host_latency_p99_ms"),
            "gpu_compute_mean_ms": mean("gpu_compute_mean_ms"),
            "gpu_compute_p95_ms_mean": mean("gpu_compute_p95_ms"),
            "gpu_compute_p99_ms_mean": mean("gpu_compute_p99_ms"),
            "qps_run_to_run_cv_percent": statistics.stdev(qps) / statistics.mean(qps) * 100,
        })
    return result


def parse_oc3() -> list[dict[str, object]]:
    rows = []
    for path in sorted((RESULTS / "power_validation").glob("*oc3_validation*.log")):
        text = read_text(path)
        batch_match = re.search(r"RT-DETR b(\d+) OC3", text)
        mode_match = re.search(r"NV Power Mode:\s*(MAXN|120W)", text)
        before = re.search(r"=== OC3 before benchmark ===\s*(\d+)", text)
        after = re.search(r"=== OC3 after benchmark ===\s*(\d+)", text)
        delta = re.search(r"=== OC3 events during benchmark interval ===\s*(\d+)", text)
        run_match = re.search(r"(?mi)^(?:Run:\s*|.*\bValidation Run\s+)(\d+)\s*$", text)
        if not all((batch_match, mode_match, before, after, delta)):
            raise ValueError(f"{path}: OC3 필드 누락")
        batch = int(batch_match.group(1))
        run = int(run_match.group(1)) if run_match else None
        perf = parse_performance(path, batch, run if run is not None else 0)
        before_value, after_value, delta_value = int(before.group(1)), int(after.group(1)), int(delta.group(1))
        if after_value - before_value != delta_value:
            raise ValueError(f"{path}: OC3 delta 산술 불일치")
        rows.append({
            "power_mode": mode_match.group(1), "batch": batch, "run": run,
            "oc3_before": before_value, "oc3_after": after_value, "oc3_delta": delta_value,
            "throughput_qps": perf["throughput_qps"],
            "effective_throughput_img_s": perf["effective_throughput_img_s"],
            "host_latency_mean_ms": perf["host_latency_mean_ms"],
            "gpu_compute_mean_ms": perf["gpu_compute_mean_ms"],
            "source_file": path.relative_to(ROOT).as_posix(),
        })
    rows.sort(key=lambda row: (str(row["power_mode"]), int(row["batch"]), row["run"] is None, int(row["run"] or 0)))
    if len(rows) != 8:
        raise ValueError(f"OC3 validation run count 불일치: {len(rows)}")
    return rows


def save_plot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


def plot_batch(summary: list[dict[str, object]]) -> None:
    batches = [int(row["batch"]) for row in summary]
    effective = [float(row["effective_throughput_img_s_mean"]) for row in summary]
    host = [float(row["host_latency_mean_ms"]) for row in summary]
    host95 = [float(row["host_latency_p95_ms_mean"]) for row in summary]
    host99 = [float(row["host_latency_p99_ms_mean"]) for row in summary]
    gpu = [float(row["gpu_compute_mean_ms"]) for row in summary]
    gpu95 = [float(row["gpu_compute_p95_ms_mean"]) for row in summary]
    gpu99 = [float(row["gpu_compute_p99_ms_mean"]) for row in summary]
    figdir = RESULTS / "batch_profiling" / "figures"
    plt.figure(figsize=(6.4, 4.2)); plt.plot(batches, effective, "o-")
    plt.xticks(batches); plt.xlabel("Batch size"); plt.ylabel("Effective throughput (images/s)"); plt.title("Batch vs Effective Throughput"); plt.grid(alpha=.3)
    save_plot(figdir / "batch_vs_throughput.png")
    plt.figure(figsize=(6.4, 4.2)); plt.plot(batches, host, "o-", label="Mean"); plt.plot(batches, host95, "o-", label="p95"); plt.plot(batches, host99, "o-", label="p99")
    plt.xticks(batches); plt.xlabel("Batch size"); plt.ylabel("Host latency (ms/batch)"); plt.title("Batch vs Host Latency"); plt.legend(); plt.grid(alpha=.3)
    save_plot(figdir / "batch_vs_latency.png")
    plt.figure(figsize=(6.4, 4.2)); plt.plot(batches, gpu, "o-", label="Mean"); plt.plot(batches, gpu95, "o-", label="p95"); plt.plot(batches, gpu99, "o-", label="p99")
    plt.xticks(batches); plt.xlabel("Batch size"); plt.ylabel("GPU compute time (ms/batch)"); plt.title("Batch vs GPU Compute Time"); plt.legend(); plt.grid(alpha=.3)
    save_plot(figdir / "batch_vs_gpu_compute.png")


def mode_batch_means(oc3_rows: list[dict[str, object]]) -> dict[tuple[str, int], dict[str, float]]:
    values: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in oc3_rows:
        values[(str(row["power_mode"]), int(row["batch"]))].append(row)
    means = {}
    for key, group in values.items():
        means[key] = {
            "throughput": statistics.mean(float(row["effective_throughput_img_s"]) for row in group),
            "gpu": statistics.mean(float(row["gpu_compute_mean_ms"]) for row in group),
        }
    return means


def plot_power(oc3_rows: list[dict[str, object]]) -> None:
    figdir = RESULTS / "power_validation" / "figures"
    labels = [f"{row['power_mode']} b{row['batch']} r{row['run'] if row['run'] is not None else 'NA'}" for row in oc3_rows]
    deltas = [int(row["oc3_delta"]) for row in oc3_rows]
    plt.figure(figsize=(9, 4.5)); plt.bar(labels, deltas); plt.xticks(rotation=35, ha="right"); plt.ylabel("OC3 counter delta"); plt.title("OC3 Delta per Validation Run"); plt.grid(axis="y", alpha=.3)
    save_plot(figdir / "batch_vs_oc3.png")
    # OC3 diagnostic protocol끼리만 비교하며 b4 MAXN은 두 관측의 명시적 평균이다.
    means = mode_batch_means(oc3_rows); batches = [2, 4, 8]
    plt.figure(figsize=(6.4, 4.2))
    for mode in ("MAXN", "120W"):
        plt.plot(batches, [means[(mode, b)]["throughput"] for b in batches], "o-", label=mode)
    plt.xticks(batches); plt.xlabel("Batch size"); plt.ylabel("Effective throughput (images/s)"); plt.title("MAXN vs 120W Throughput"); plt.legend(); plt.grid(alpha=.3)
    save_plot(figdir / "maxn_vs_120w_throughput.png")
    plt.figure(figsize=(6.4, 4.2))
    for mode in ("MAXN", "120W"):
        plt.plot(batches, [means[(mode, b)]["gpu"] for b in batches], "o-", label=mode)
    plt.xticks(batches); plt.xlabel("Batch size"); plt.ylabel("GPU compute time (ms/batch)"); plt.title("MAXN vs 120W GPU Latency"); plt.legend(); plt.grid(alpha=.3)
    save_plot(figdir / "maxn_vs_120w_gpu_latency.png")


def markdown_table(summary: list[dict[str, object]]) -> str:
    lines = ["| Batch | Runs | QPS mean | Effective img/s | Host mean ms | Host p95 ms | Host p99 ms | GPU mean ms | Throughput CV % |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in summary:
        lines.append(
            f"| {row['batch']} | {row['run_count']} | {row['throughput_qps_mean']:.3f} | {row['effective_throughput_img_s_mean']:.3f} | "
            f"{row['host_latency_mean_ms']:.3f} | {row['host_latency_p95_ms_mean']:.3f} | {row['host_latency_p99_ms_mean']:.3f} | "
            f"{row['gpu_compute_mean_ms']:.3f} | {row['qps_run_to_run_cv_percent']:.3f} |"
        )
    return "\n".join(lines)


def write_batch_readme(summary: list[dict[str, object]]) -> None:
    table = markdown_table(summary)
    text = f"""# TensorRT batch profiling

Summary schema version: 1
Generated by: `scripts/summarize_profiling.py`
Raw logs are the source of truth.

## 목적

NVIDIA Jetson AGX Thor에서 RT-DETR Warehouse v1.0.2 / ResNet-50의 fixed batch-specific TensorRT 실행 특성을 격리해 비교한다.

## 실험 환경

- Device: NVIDIA Jetson AGX Thor
- Input: `B×3×640×640`
- Engine: fixed batch-specific, FP16-enabled TensorRT engine
- Power mode: MAXN / ID 0
- DVFS: enabled, `jetson_clocks`: OFF
- CUDA Graph: OFF, SpinWait: OFF, cross-inference streams: 1

## 실험 방법

각 batch `B={{1,2,4,8}}`에서 2 s warm-up 후 30 s measurement를 3회 수행했다. 각 log의 **마지막** `=== Performance summary ===`만 파싱했다. 중간 `Average on 10 runs ...` 출력은 formal result에 포함하지 않았다. Throughput run-to-run CV는 3회 QPS의 sample standard deviation을 mean으로 나눠 계산했다.

## 결과

{table}

현재 측정한 `B={{1,2,4,8}}` 범위에서는 b2가 effective throughput 최고점이다. 이는 측정 범위 안의 최고점이며, 모든 가능한 batch에 대한 global optimum을 뜻하지 않는다.

## 해석

raw log 재계산 기준 effective throughput은 b1 약 {summary[0]['effective_throughput_img_s_mean']:.2f}, b2 약 {summary[1]['effective_throughput_img_s_mean']:.2f}, b4 약 {summary[2]['effective_throughput_img_s_mean']:.2f}, b8 약 {summary[3]['effective_throughput_img_s_mean']:.2f} img/s다. b2 이후에는 batch당 GPU compute와 Host latency 증가가 effective throughput 증가로 이어지지 않았다. MAXN b4/b8에서는 후속 OC3 validation에서 OC3 activity가 확인되었으므로 large-batch 결과 해석에 caveat가 필요하다.

## 주의사항

- `trtexec Throughput`은 batch/query completions per second이며 image/s가 아니다. effective image throughput은 `batch × qps`다.
- batch latency를 batch size로 나눈 값을 per-image latency라고 해석하면 안 된다.
- 범위는 preprocessed tensor → H2D → TensorRT → D2H → outputs다.
- video decode, preprocessing, application queue, batch formation wait, JPEG, network, MEC는 포함하지 않는다.
- per-run GPU compute CV는 trtexec가 raw log에 coefficient를 출력한 run에만 기록하며, 누락값을 추정하지 않는다.

## 관련 파일

- `formal_runs.csv`: 12개 formal run의 원자료 파싱 결과
- `summary.csv`: batch별 3회 집계
- `figures/`: throughput 및 latency figure
- 원본 `.log`: 수정하지 않은 raw measurement
"""
    (RESULTS / "batch_profiling" / "README.md").write_text(text, encoding="utf-8")


def write_power_readme(rows: list[dict[str, object]]) -> None:
    lines = ["| Mode | Batch | Run | OC3 before | OC3 after | Delta | Effective img/s | GPU mean ms |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['power_mode']} | {row['batch']} | {row['run']} | {row['oc3_before']} | {row['oc3_after']} | {row['oc3_delta']} | {row['effective_throughput_img_s']:.3f} | {row['gpu_compute_mean_ms']:.3f} |")
    text = """# Power / OC3 validation

Summary schema version: 1
Generated by: `scripts/summarize_profiling.py`
Raw logs are the source of truth.

## 목적

MAXN과 120W에서 RT-DETR batch 실행 중 관찰된 OC3 counter 변화와 성능을 raw log 기준으로 정리한다.

## 측정 정의

각 값은 **OC3 delta observed during one trtexec run with 2-s warm-up and 30-s measurement**다. 측정 순서는 `OC3 before → trtexec invocation → warm-up 2 s → measurement 30 s → 종료 → OC3 after`이므로 strict한 `OC3 events / 30 s`로 표현하지 않는다.

## 결과

""" + "\n".join(lines) + """

MAXN b4에서 OC3 delta가 두 번 반복 재현되었고 MAXN b8에서도 발생했다. 120W에서는 OC3 activity가 크게 감소했다.

MAXN/120W 비교 figure는 b2/b4/b8 OC3 diagnostic protocol만 사용한다. b2와 b8은 mode별 1회 관측이고 MAXN b4는 2회 관측의 평균, 120W b4는 1회 관측이다. b1의 mode별 3회 calibration은 `power_calibration/README.md`에 별도로 유지하며 이 curve에 섞지 않는다.

## 해석과 제한

120W b2와 b4는 모두 OC3 delta=0이지만 b4 throughput은 b2보다 낮다. 따라서 b2 이후 throughput 감소를 OC3만으로 설명할 수 없다. 현재 관찰은 RT-DETR/TensorRT large-batch scaling behavior와 MAXN의 추가적인 hardware power protection이 함께 존재할 가능성을 보여주지만 인과관계를 확정하지 않는다.

OC3 event count는 throttle duration 또는 severity와 같은 지표가 아니다. MAXN b8 count가 b4보다 작으므로 batch 증가에 따라 OC3 count가 단조 증가한다고 해석하지 않는다. GUI 경고와 새로운 OC3 counter increment도 동일시하지 않는다.

## 관련 파일

- `oc3_summary.csv`: before/after/delta와 같은 run의 최종 성능 summary
- `figures/`: OC3 및 MAXN/120W 비교 figure
- `*_oc3_validation*.log`: 수정하지 않은 raw log
"""
    (RESULTS / "power_validation" / "README.md").write_text(text, encoding="utf-8")


def calibration_means() -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for path in sorted((RESULTS / "power_calibration").glob("rtdetr_b1_*_run*.log")):
        text = read_text(path); mode = re.search(r"NV Power Mode:\s*(MAXN|120W)", text); run = re.search(r"(?m)^Run:\s*(\d+)", text)
        if mode and run:
            grouped[mode.group(1)].append(parse_performance(path, 1, int(run.group(1))))
    result = {}
    for mode, rows in grouped.items():
        result[mode] = {key: statistics.mean(float(row[key]) for row in rows) for key in ("throughput_qps", "host_latency_mean_ms", "gpu_compute_mean_ms")}
    return result


def write_other_readmes() -> None:
    means = calibration_means(); low, high = means["120W"], means["MAXN"]
    throughput_gain = (high["throughput_qps"] / low["throughput_qps"] - 1) * 100
    host_drop = (high["host_latency_mean_ms"] / low["host_latency_mean_ms"] - 1) * 100
    gpu_drop = (high["gpu_compute_mean_ms"] / low["gpu_compute_mean_ms"] - 1) * 100
    (RESULTS / "power_calibration" / "README.md").write_text(f"""# Power calibration

b1 isolated inference를 120W와 MAXN에서 각각 3회 비교했다. 공통 조건은 2 s warm-up, 30 s measurement, DVFS enabled, `jetson_clocks` OFF다. 마지막 `Performance summary`의 3회 mean은 다음과 같다.

| Mode | Throughput QPS | Host mean ms | GPU mean ms |
|---|---:|---:|---:|
| 120W | {low['throughput_qps']:.3f} | {low['host_latency_mean_ms']:.3f} | {low['gpu_compute_mean_ms']:.3f} |
| MAXN | {high['throughput_qps']:.3f} | {high['host_latency_mean_ms']:.3f} | {high['gpu_compute_mean_ms']:.3f} |

MAXN은 120W 대비 throughput이 {throughput_gain:+.2f}% 높고 Host latency는 {host_drop:+.2f}%, GPU compute는 {gpu_drop:+.2f}% 낮았다. 이 결과는 b1과 해당 조건의 calibration 비교이며 다른 workload에 일반화하지 않는다.
""", encoding="utf-8")
    (RESULTS / "correctness" / "README.md").write_text("""# Real-frame correctness

NVIDIA PhysicalAI-SmartSpaces의 `Warehouse_000` / `Camera_0000.mp4` 실제 frame(H.264, 1920×1080, 30 FPS)을 사용해 correctness를 확인했다. 처리 경로는 `actual frame → resize 640×360 → pad 640×640 → BGR→RGB → /255 → FP32 NCHW → TensorRT`다.

원본 frame, 전처리 image/tensor, output JSON, detection 시각화 artifact를 함께 보존한다. 이는 실제 frame에 대한 입출력 correctness 확인이며 formal 성능 benchmark가 아니다.
""", encoding="utf-8")
    build_logs = sorted((RESULTS / "engine_build").glob("*.log"))
    built = sorted(int(re.search(r"_b(\d+)_build", path.name).group(1)) for path in build_logs if re.search(r"_b(\d+)_build", path.name))
    missing = sorted({1, 2, 4, 8} - set(built))
    (RESULTS / "engine_build" / "README.md").write_text(f"""# TensorRT engine build

batch별 실행 특성을 분리하고 runtime shape 변경의 영향을 배제하기 위해 b1/b2/b4/b8 fixed engine에서 `MIN=OPT=MAX=B`를 사용했다. `--fp16`은 FP16 tactic 사용을 허용하지만 build log의 precision은 `FP32+FP16`이므로 **FP16-enabled TensorRT engine**으로 표현하며 all-FP16이라고 단정하지 않는다.

현재 보존된 build log에서 확인되는 batch는 {built}다. b1 engine 파일은 존재하지만 b1 build raw log는 없어 build 과정은 이 폴더에서 확인할 수 없다. 확인 불가 batch: {missing}.
""", encoding="utf-8")
    (RESULTS / "smoke" / "README.md").write_text("""# Smoke test

Smoke test는 engine load, input binding, 짧은 실행 및 정상 종료 여부를 확인하기 위한 실행 가능성 검사다. warm-up 0 ms, duration 0 s, 10 iterations 조건이므로 formal profiling 결과로 사용하거나 formal run과 성능을 비교하지 않는다.
""", encoding="utf-8")
    (RESULTS / "README.md").write_text("""# 실험 결과 개요

## 완료된 범위

- Environment / reproducibility
- Dataset/video verification
- Model/engine verification
- Real-frame correctness
- Power mode comparison
- TensorRT b1/b2/b4/b8 isolated profiling
- TensorRT jitter diagnostic
- OC3 diagnostic
- 120W sensitivity

## 현재 연구용 main Thor operating point

| Setting | Value |
|---|---|
| Power mode | MAXN / ID 0 |
| DVFS | enabled |
| `jetson_clocks` | OFF |
| OC protection | platform default |

현재 실제 장비 runtime state는 마지막 sensitivity test 때문에 120W일 수 있다. 이 문서 생성 과정에서는 runtime state를 조회하거나 변경하지 않았다. 다음 성능실험 직전에 별도 승인된 절차로 MAXN 복귀를 확인할 예정이다.

## 앞으로의 범위

- H.264 hardware decode-only
- preprocessing-only
- decode + preprocessing
- single-stream local E2E
- multi-stream local scaling
- saturation/backlog
- queue time-series/cross-cycle coupling
- decode/inference contention
- JPEG encode
- local inference + JPEG contention
- RTX 5070 Ti isolated profiling
- shared MEC interference
- Thor-MEC network profiling
- edge batching
- client request-release shaping
- full Local+Edge E2E
- motivation experiments
- problem formulation
- scheduler/controller
- baseline comparison
- final evaluation

이 목록은 향후 측정 순서의 후보이며 최종 연구 질문, architecture, objective 또는 scheduling formulation을 고정하지 않는다.
""", encoding="utf-8")


def write_inventory() -> None:
    lines = []
    for path in sorted(RESULTS.rglob("*.log")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    (RESULTS / "experiment_inventory.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    formal = discover_formal_runs()
    summary = summarize_formal(formal)
    write_csv(RESULTS / "batch_profiling" / "formal_runs.csv", METRIC_COLUMNS, formal)
    summary_columns = list(summary[0].keys())
    write_csv(RESULTS / "batch_profiling" / "summary.csv", summary_columns, summary)
    oc3 = parse_oc3()
    write_csv(RESULTS / "power_validation" / "oc3_summary.csv", list(oc3[0].keys()), oc3)
    plot_batch(summary)
    plot_power(oc3)
    write_batch_readme(summary)
    write_power_readme(oc3)
    write_other_readmes()
    write_inventory()
    print(f"formal_runs={len(formal)}")
    print("formal_counts=" + ",".join(f"b{batch}=3" for batch in (1, 2, 4, 8)))
    print(f"oc3_runs={len(oc3)}")


if __name__ == "__main__":
    main()
