"""Measure Thor GPU groups and cumulative ranges with CUDA Events only."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import traceback

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torchvision

from split_inference.src.common.efficientnet_v2_s_partitions import (
    EfficientNetV2SPartitions,
    MANIFEST_PATH,
)


SEED, WARMUP, ROUNDS, SAMPLES = 0, 100, 5, 200
ROOT = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tensor_info(tensor, point):
    shape = list(tensor.shape)
    assert shape == point["expected_shape"], (point["id"], shape)
    assert tensor.dtype == torch.float32 and tensor.is_cuda
    size = tensor.numel() * tensor.element_size()
    assert size == math.prod(point["expected_shape"]) * 4
    assert torch.isfinite(tensor).all().item(), point["id"]
    return {"shape": shape, "bytes": size, "dtype": str(tensor.dtype)}


def statistics(values):
    a = np.asarray(values, dtype=np.float64)
    assert len(a) == ROUNDS * SAMPLES
    assert np.isfinite(a).all() and (a >= 0).all()
    return {
        "n": len(a), "mean_ms": float(a.mean()),
        "median_ms": float(np.median(a)),
        "p95_ms": float(np.percentile(a, 95, method="linear")),
        "std_ms": float(a.std(ddof=1)),
    }


def save_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_groups(output, rows):
    labels = [r["group"] for r in rows]
    positions = np.arange(len(rows))
    fig, left = plt.subplots(figsize=(10, 5), constrained_layout=True)
    right = left.twinx()
    bars = left.bar(positions, [r["mean_ms"] for r in rows], width=0.58,
                    color="#0072B2", label="Thor processing time")
    line, = right.plot(positions, [r["output_bytes"] / 1_000_000 for r in rows],
                       color="#D55E00", marker="o", label="Output data size")
    left.set_xticks(positions, labels)
    left.set_xlabel("Layer group")
    left.set_ylabel("Processing time (ms)")
    right.set_ylabel("Output data size (MB)")
    left.set_ylim(bottom=0)
    right.set_ylim(bottom=0)
    left.grid(axis="y", alpha=0.2)
    left.set_axisbelow(True)
    left.legend([bars, line], ["Thor processing time", "Output data size"],
                loc="upper center")
    fig.savefig(output / "group_processing_output_size.png", dpi=300)
    fig.savefig(output / "group_processing_output_size.pdf")
    plt.close(fig)


def run(args, metadata):
    verification = Path(args.verification_log).read_text()
    assert "ALL_P0_P9_PASS" in verification, "Prior partition verification required"
    preflight = json.loads(Path(args.preflight).read_text())
    for name in ("nvidia_smi", "gpu_list", "mig", "cuda_processes", "image"):
        assert preflight[name]["exit_code"] == 0, name
    assert len(preflight["cuda_processes"]["stdout"].strip().splitlines()) == 1, "Other CUDA workload"
    assert "MIG " not in preflight["gpu_list"]["stdout"], "Active MIG instance"
    image = json.loads(preflight["image"]["stdout"])[0]
    assert args.image in image["RepoDigests"], "Local image digest mismatch"
    metadata.update({"preflight": preflight, "host_command": Path(args.host_command).read_text(),
                     "image": args.image, "verification_log_sha256": hashlib.sha256(
                         verification.encode()).hexdigest()})
    torch.manual_seed(SEED)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = True
    assert torch.cuda.is_available(), "CUDA unavailable"
    metadata.update({
        "python": sys.version, "torch": torch.__version__,
        "torchvision": torchvision.__version__, "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(), "numpy": np.__version__,
        "matplotlib": matplotlib.__version__, "gpu": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
        "seed": SEED, "warmup_per_target": WARMUP, "rounds": ROUNDS,
        "samples_per_round": SAMPLES, "tf32": False, "cudnn_benchmark": True,
        "dtype": "torch.float32", "batch_size": 1, "weights": None,
        "eval": True, "inference_mode": True, "compile": False,
        "timer": "CUDA Event elapsed_time, default stream, milliseconds",
        "timing_scope": "Thor GPU device timeline; not network/server/E2E",
        "excluded": ["input preparation", "copies", "file IO", "host synchronize wait"],
        "caveat": "CUDA Event intervals may include device idle gaps between eager kernel launches; not a sum of isolated kernel durations.",
        "p0": {"provenance": "defined_no_thor_work", "n": 0, "ms": 0.0},
        "quantile_method": "linear", "std_ddof": 1, "mb_divisor": 1_000_000,
        "source_sha256": {}, "round_orders": [],
    })
    for path in (Path(__file__).resolve(), MANIFEST_PATH,
                 ROOT / "src/common/efficientnet_v2_s_partitions.py"):
        metadata["source_sha256"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    model = torchvision.models.efficientnet_v2_s(weights=None).float().cuda().eval()
    partitions = EfficientNetV2SPartitions(model)
    assert all(not m.training for m in model.modules())
    points = partitions.manifest["points"]
    assert [p["index"] for p in points] == list(range(10))
    targets = [(kind, i) for kind in ("group", "partition") for i in range(1, 10)]
    elapsed = {f"{kind}:{i}": [] for kind, i in targets}
    with torch.inference_mode():
        # Produce each group's input once, before any event measurements.
        x = torch.randn((1, 3, 384, 384), device="cuda", dtype=torch.float32)
        activations = [x]
        for i in range(9):
            activations.append(partitions._run(activations[-1], i, i + 1))
        info = [tensor_info(a, p) for a, p in zip(activations, points)]
        assert info[9]["shape"] == [1, 1000]
        torch.cuda.synchronize()
        metadata["activations"] = info
        start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        # Materialize events outside all warm-up and measured intervals.
        start.record()
        end.record()
        end.synchronize()

        def execute(kind, i):
            if kind == "group":
                return partitions._run(activations[i - 1], i - 1, i)
            return partitions.prefix(x, i)

        fields = ["phase", "kind", "target", "round", "order", "sample", "duration_ms"]
        with (args.output / "raw_samples.csv").open("w", newline="", buffering=1) as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()

            def measure_block(kind, i, phase, round_index, order, count):
                name = f"{'G' if kind == 'group' else 'P'}{i}"
                metadata["stage"] = f"{phase}/{round_index}/{name}"
                for sample in range(count):
                    start.record()
                    result = execute(kind, i)
                    end.record()
                    # Host waiting and reading elapsed time happen after the end event.
                    end.synchronize()
                    duration = start.elapsed_time(end)
                    writer.writerow(dict(phase=phase, kind=kind, target=name,
                                         round=round_index, order=order, sample=sample,
                                         duration_ms=duration))
                    assert math.isfinite(duration) and duration >= 0, (name, duration)
                    assert list(result.shape) == points[i]["expected_shape"], name
                    if phase == "measurement":
                        elapsed[f"{kind}:{i}"].append(duration)
                assert tensor_info(result, points[i]) == info[i]

            warmup_order = targets.copy()
            random.Random(SEED).shuffle(warmup_order)
            metadata["warmup_order"] = warmup_order
            for order, (kind, i) in enumerate(warmup_order):
                measure_block(kind, i, "warmup", -1, order, WARMUP)
                print(f"Warm-up complete: {kind} {i}", flush=True)
            for round_index in range(ROUNDS):
                order_list = targets.copy()
                random.Random(SEED + round_index + 1).shuffle(order_list)
                metadata["round_orders"].append(order_list)
                for order, (kind, i) in enumerate(order_list):
                    measure_block(kind, i, "measurement", round_index, order, SAMPLES)
                print(f"Round {round_index + 1}/{ROUNDS} complete", flush=True)

    metadata["stage"] = "validation_and_summary"
    # Independently re-read raw data; warm-up observations remain in the same file.
    with (args.output / "raw_samples.csv").open() as f:
        raw = list(csv.DictReader(f))
    assert len(raw) == 18 * (WARMUP + ROUNDS * SAMPLES)
    for kind, i in targets:
        name = f"{'G' if kind == 'group' else 'P'}{i}"
        subset = [r for r in raw if r["kind"] == kind and r["target"] == name]
        warm = [r for r in subset if r["phase"] == "warmup"]
        assert len(warm) == WARMUP
        measured = [r for r in subset if r["phase"] == "measurement"]
        assert len(measured) == ROUNDS * SAMPLES
        for round_index in range(ROUNDS):
            samples = [int(r["sample"]) for r in measured if int(r["round"]) == round_index]
            assert samples == list(range(SAMPLES))
        assert [float(r["duration_ms"]) for r in measured] == elapsed[f"{kind}:{i}"]
        assert all(math.isfinite(float(r["duration_ms"])) and float(r["duration_ms"]) >= 0 for r in subset)

    groups = [{"group": f"G{i}", **statistics(elapsed[f"group:{i}"]),
               "output_shape": json.dumps(info[i]["shape"]), "output_bytes": info[i]["bytes"]}
              for i in range(1, 10)]
    cumulative = [{"partition_point": "P0", "n": 0, "mean_ms": 0.0, "median_ms": 0.0,
                   "p95_ms": 0.0, "std_ms": 0.0, "activation_shape": json.dumps(info[0]["shape"]),
                   "activation_bytes": info[0]["bytes"]}]
    cumulative += [{"partition_point": f"P{i}", **statistics(elapsed[f"partition:{i}"]),
                    "activation_shape": json.dumps(info[i]["shape"]), "activation_bytes": info[i]["bytes"]}
                   for i in range(1, 10)]
    metadata["p99_ms"] = {k: float(np.percentile(v, 99, method="linear")) for k, v in elapsed.items()}
    group_sum = sum(r["mean_ms"] for r in groups)
    p9 = cumulative[-1]["mean_ms"]
    metadata["group_sum_vs_p9"] = {
        "group_mean_sum_ms": group_sum, "p9_direct_mean_ms": p9,
        "group_sum_minus_p9_ms": group_sum - p9,
        "difference_percent_of_p9": (group_sum - p9) / p9 * 100,
    }
    save_csv(args.output / "group_summary.csv", groups)
    save_csv(args.output / "partition_summary.csv", cumulative)
    metadata["stage"] = "plot"
    plot_groups(args.output, groups)
    print(json.dumps(metadata["group_sum_vs_p9"]), flush=True)
    print("THOR_PROCESSING_PROFILE_PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--verification-log", required=True)
    parser.add_argument("--host-command", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assert not list(args.output.iterdir()), "Output directory must be empty; preserve previous runs"
    metadata = {"started_utc": utc_now(), "status": "running", "stage": "initialization"}
    try:
        run(args, metadata)
        metadata["status"] = "passed"
    except BaseException:
        metadata["status"] = "failed"
        metadata["error"] = traceback.format_exc()
        raise
    finally:
        metadata["ended_utc"] = utc_now()
        (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
