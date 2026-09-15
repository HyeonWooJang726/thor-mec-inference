"""Direct CUDA Event profiling of the official EfficientNetV2-S Edge suffixes.

Run from the repository root with the dedicated CUDA Python environment:
    python -B -m split_inference.scripts.profile_efficientnet_v2_s_edge
Every invocation creates a new timestamp directory, including failed runs.
"""

import csv
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import traceback
import warnings


ROOT = Path(__file__).resolve().parents[2]
SEED, WARMUP, ROUNDS, SAMPLES = 0, 100, 5, 200
EXPECTED_GPU = "NVIDIA GeForce RTX 5070 Ti"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def command(args, required=False):
    try:
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120)
        result = dict(command=args, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        result = dict(command=args, exit_code=None, unavailable=str(error))
    if required:
        require(result["exit_code"] == 0, json.dumps(result))
    return result


def gpu_snapshot():
    return {
        "nvidia_smi": command(["nvidia-smi", "-q"]),
        "compute_processes": command([
            "nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv"]),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def run(output, metadata):
    metadata["stage"] = "environment_validation"
    # Treat warnings as failures, including CUDA architecture incompatibility.
    warnings.simplefilter("error")
    import numpy as np
    import torch
    import torchvision
    from split_inference.src.common.efficientnet_v2_s_partitions import (
        EfficientNetV2SPartitions, MANIFEST_PATH,
    )

    metadata["environment"] = {
        "hostname": platform.node(), "architecture": platform.machine(),
        "platform": platform.platform(), "python": sys.version,
        "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "torch": torch.__version__, "torchvision": torchvision.__version__,
        "cuda_runtime": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "numpy": np.__version__, "docker_image": None,
        "pip_freeze": command([sys.executable, "-m", "pip", "freeze"], required=True),
        "gpu_before_validation": gpu_snapshot(),
        "cpu": command(["lscpu"]),
        "clock_policy": "No power or clock settings changed. Lock status unavailable; snapshots are observations only.",
        "cpu_frequency": {}, "emc_clock": "unavailable: not a Jetson platform",
    }
    for name in ("scaling_governor", "scaling_cur_freq", "scaling_min_freq", "scaling_max_freq"):
        paths = sorted(Path("/sys/devices/system/cpu").glob(f"cpu[0-9]*/cpufreq/{name}"))
        metadata["environment"]["cpu_frequency"][name] = (
            {str(p): p.read_text().strip() for p in paths}
            if paths else "unavailable: CPU cpufreq sysfs entries not exposed")
    require(torch.__version__ == "2.13.0+cu132", "Unexpected torch version")
    require(torchvision.__version__ == "0.28.0+cu132", "Unexpected torchvision version")
    require(torch.cuda.is_available(), "CUDA unavailable")
    require(torch.cuda.get_device_name(0) == EXPECTED_GPU, "Unexpected GPU")
    require(torch.version.cuda == "13.2", "Unexpected CUDA runtime")
    require(torch.backends.cudnn.version() is not None, "cuDNN unavailable")
    metadata["environment"].update({
        "gpu": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "compiled_architectures": torch.cuda.get_arch_list(),
        "gpu_properties": str(torch.cuda.get_device_properties(0)),
    })
    torch.manual_seed(SEED)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = True
    with torch.inference_mode():
        a = torch.arange(16, dtype=torch.float32, device="cuda")
        torch.testing.assert_close(a * 2 + 1, torch.arange(1, 32, 2, device="cuda", dtype=torch.float32))
        torch.cuda.synchronize()
        probe = torchvision.models.efficientnet_v2_s(weights=None).float().cuda().eval()
        probe_output = probe(torch.randn(1, 3, 384, 384, device="cuda", dtype=torch.float32))
        torch.cuda.synchronize()
        require(list(probe_output.shape) == [1, 1000], "CUDA forward shape mismatch")
        require(probe_output.dtype == torch.float32 and torch.isfinite(probe_output).all().item(),
                "CUDA forward invalid output")
        del probe, probe_output, a
    metadata["environment_validation"] = "passed: imports, CUDA tensor, synchronize, FP32 model forward; warnings are errors"
    print("ENVIRONMENT_VALIDATION_PASS", flush=True)

    metadata["stage"] = "existing_cuda_partition_verification"
    verification = command([
        sys.executable, "-B", "-W", "error", "-m",
        "split_inference.scripts.verify_efficientnet_v2_s_partitions",
    ])
    write_json(output / "verification_process.json", verification)
    (output / "verification.stdout.log").write_text(verification.get("stdout", ""))
    (output / "verification.stderr.log").write_text(verification.get("stderr", ""))
    require(verification["exit_code"] == 0, "Existing CUDA verification failed; see verification logs")
    require("ALL_P0_P9_PASS" in verification["stdout"], "Missing verification pass marker")
    manifest = json.loads(MANIFEST_PATH.read_text())
    points = manifest["points"]
    require([p["index"] for p in points] == list(range(10)), "Manifest point indices mismatch")
    require([p["id"] for p in points] == [f"P{i}" for i in range(10)], "Manifest point IDs mismatch")
    records = [json.loads(line.removeprefix("PARTITION "))
               for line in verification["stdout"].splitlines() if line.startswith("PARTITION ")]
    require([r["point"] for r in records] == [p["id"] for p in points], "Verification points missing")
    for r, p in zip(records, points):
        require(r["shape"] == p["expected_shape"], f"{p['id']} verification activation shape mismatch")
        require(r["bytes"] == math.prod(p["expected_shape"]) * 4, f"{p['id']} activation bytes mismatch")
        require(r["output_shape"] == [1, 1000], f"{p['id']} verification output shape mismatch")
        require(all(math.isfinite(r[k]) and r[k] >= 0 for k in ("max_abs_diff", "max_rel_diff")),
                f"{p['id']} invalid correctness errors")
        r.update(tolerance_passed=True, manifest_shape_and_bytes_passed=True)
    metadata["existing_verification"] = {
        "cudnn_benchmark": False, "rtol": 1e-5, "atol": 1e-6,
        "relative_error_floor": 1e-8, "points": records,
        "manifest_bytes_rule": "prod(expected_shape) * 4; manifest contains FP32 shapes, no per-point byte field",
    }
    print("EXISTING_PARTITION_VERIFICATION_PASS", flush=True)

    metadata["stage"] = "measurement_model_correctness"
    torch.manual_seed(SEED)
    model = torchvision.models.efficientnet_v2_s(weights=None).float().cuda().eval()
    partitions = EfficientNetV2SPartitions(model)
    require(all(not m.training for m in model.modules()), "eval required")
    state_hash = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        state_hash.update(json.dumps([name, str(tensor.dtype), list(tensor.shape)],
                                     separators=(",", ":")).encode() + b"\n")
        state_hash.update(tensor.detach().cpu().contiguous().numpy().tobytes(order="C"))
    metadata["state_dict_sha256"] = state_hash.hexdigest()
    metadata["state_hash_method"] = "Sorted state_dict keys; UTF-8 compact JSON [name,dtype,shape] plus LF, then contiguous CPU C-order tensor bytes; SHA-256; host little-endian. No checkpoint committed."
    metadata["config"] = {
        "seed": SEED, "weights": None, "input_shape": [1, 3, 384, 384],
        "input_provenance": "seeded torch.randn on Edge CUDA; benchmark input, not a dataset image",
        "batch_size": 1, "dtype": "torch.float32", "eval": True, "inference_mode": True,
        "tf32_matmul": False, "tf32_cudnn": False, "cudnn_benchmark": True,
        "warmup_per_target": WARMUP, "rounds": ROUNDS, "samples_per_round": SAMPLES,
        "timer": "CUDA Event elapsed_time in milliseconds, same default CUDA stream",
        "std_ddof": 1, "quantile_method": "linear", "outlier_exclusion": "none",
        "scope": "Direct Edge GPU suffix device timeline, not E2E or throughput",
        "excluded": ["prefix activation generation", "network", "serialization", "deserialization",
                     "CPU-GPU copies", "server queue", "request framework", "file IO", "host synchronization wait"],
        "timing_caveat": "Eager CUDA Event intervals may include GPU idle gaps between host kernel launches; not a sum of isolated kernel times.",
    }
    sources = [Path(__file__).resolve(), MANIFEST_PATH,
               ROOT / "split_inference/src/common/efficientnet_v2_s_partitions.py",
               ROOT / "split_inference/scripts/verify_efficientnet_v2_s_partitions.py"]
    metadata["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sources}
    torchvision_source = Path(inspect.getfile(type(model)))
    metadata["torchvision_model_source"] = {"path": str(torchvision_source),
        "sha256": hashlib.sha256(torchvision_source.read_bytes()).hexdigest()}
    (output / "profile_measured.py").write_bytes(Path(__file__).read_bytes())
    metadata["measurement_model_verification"] = []
    metadata["warmup_order"] = list(range(9))
    random.Random(SEED).shuffle(metadata["warmup_order"])
    metadata["round_orders"] = []
    with torch.inference_mode():
        x = torch.randn((1, 3, 384, 384), device="cuda", dtype=torch.float32)
        reference = model(x)
        activations = []
        for p in points:
            i = p["index"]
            activation = partitions.prefix(x, i)
            require(list(activation.shape) == p["expected_shape"], f"P{i} activation shape mismatch")
            require(activation.dtype == torch.float32 and activation.is_cuda, f"P{i} activation type mismatch")
            size = activation.numel() * activation.element_size()
            require(size == math.prod(p["expected_shape"]) * 4, f"P{i} activation bytes mismatch")
            require(torch.isfinite(activation).all().item(), f"P{i} nonfinite activation")
            result = partitions.suffix(activation, i)
            require(list(result.shape) == [1, 1000], f"P{i} output shape mismatch")
            torch.testing.assert_close(result, reference, rtol=1e-5, atol=1e-6)
            diff = (result - reference).abs()
            metadata["measurement_model_verification"].append({
                "point": f"P{i}", "activation_shape": list(activation.shape), "activation_bytes": size,
                "output_shape": list(result.shape), "max_abs_diff": diff.max().item(),
                "max_rel_diff": (diff / reference.abs().clamp_min(1e-8)).max().item(),
                "tolerance_passed": True, "cudnn_benchmark": True,
            })
            activations.append(activation)
        torch.cuda.synchronize()
        metadata["gpu_immediately_before_measurement"] = gpu_snapshot()
        # WSL/WDDM can omit other processes; record raw output, do not claim isolation.
        metadata["process_visibility_limit"] = "nvidia-smi process lists may be incomplete under WSL/WDDM; an empty list does not establish an idle GPU."
        start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        start.record()
        end.record()
        end.synchronize()
        fields = ["partition_point", "phase", "round", "order", "sample", "duration_ms"]
        with (output / "edge_suffix_samples.csv").open("x", newline="", buffering=1) as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()

            def measure_block(i, phase, round_index, order, count):
                metadata["stage"] = f"{phase}/round{round_index}/P{i}"
                metadata["sample_in_progress"] = None
                write_json(output / "metadata.json", metadata)
                for sample in range(count):
                    metadata["sample_in_progress"] = sample
                    start.record()
                    result = partitions.suffix(activations[i], i)
                    end.record()
                    end.synchronize()
                    duration = start.elapsed_time(end)
                    writer.writerow(dict(partition_point=f"P{i}", phase=phase, round=round_index,
                                         order=order, sample=sample, duration_ms=duration))
                    require(math.isfinite(duration) and duration >= 0, f"P{i} invalid time {duration}")
                    require(list(result.shape) == [1, 1000], f"P{i} measured output shape mismatch")
                require(torch.isfinite(result).all().item(), f"P{i} nonfinite measured output")
                torch.testing.assert_close(result, reference, rtol=1e-5, atol=1e-6)

            metadata["measurement_started_utc"] = utc_now()
            for order, i in enumerate(metadata["warmup_order"]):
                measure_block(i, "warmup", -1, order, WARMUP)
                print(f"Warm-up complete: P{i}", flush=True)
            for r in range(ROUNDS):
                order_list = list(range(9))
                random.Random(SEED + r + 1).shuffle(order_list)
                metadata["round_orders"].append(order_list)
                for order, i in enumerate(order_list):
                    measure_block(i, "measurement", r, order, SAMPLES)
                print(f"Round {r + 1}/{ROUNDS} complete", flush=True)
            metadata["measurement_ended_utc"] = utc_now()
    metadata["gpu_after_measurement"] = gpu_snapshot()
    metadata["stage"] = "validate_raw_and_summarize"
    with (output / "edge_suffix_samples.csv").open() as f:
        raw = list(csv.DictReader(f))
    require(len(raw) == 9 * (WARMUP + ROUNDS * SAMPLES), "Raw sample count mismatch")
    require({r["partition_point"] for r in raw} == {f"P{i}" for i in range(9)}, "Raw points mismatch")
    require({r["phase"] for r in raw} == {"warmup", "measurement"}, "Unexpected raw phase")
    summaries = []
    for i in range(10):
        subset = [r for r in raw if r["partition_point"] == f"P{i}"]
        values = []
        if i < 9:
            for phase, rounds, count in (("warmup", [-1], WARMUP), ("measurement", range(ROUNDS), SAMPLES)):
                for r in rounds:
                    block = [v for v in subset if v["phase"] == phase and int(v["round"]) == r]
                    require([int(v["sample"]) for v in block] == list(range(count)), f"P{i}/{phase}/{r} sample IDs/count mismatch")
                    expected_order = (metadata["warmup_order"] if phase == "warmup" else metadata["round_orders"][r]).index(i)
                    require(all(int(v["order"]) == expected_order for v in block), "Block order mismatch")
                    for v in block:
                        duration = float(v["duration_ms"])
                        require(math.isfinite(duration) and duration >= 0, "Invalid raw duration")
                        if phase == "measurement":
                            values.append(duration)
            require(len(values) == ROUNDS * SAMPLES, f"P{i} measured count mismatch")
            require(len(subset) == WARMUP + ROUNDS * SAMPLES, f"P{i} total count mismatch")
            a = np.array(values, dtype=np.float64)
            stats = dict(mean_ms=float(a.mean()), median_ms=float(np.median(a)),
                         p95_ms=float(np.percentile(a, 95, method="linear")),
                         p99_ms=float(np.percentile(a, 99, method="linear")),
                         std_ms=float(a.std(ddof=1)), min_ms=float(a.min()), max_ms=float(a.max()))
        else:
            require(not subset, "P9 must have no samples")
            stats = dict.fromkeys(["mean_ms", "median_ms", "p95_ms", "p99_ms", "std_ms", "min_ms", "max_ms"], 0.0)
        require(all(math.isfinite(v) and v >= 0 for v in stats.values()), "Invalid summary")
        summaries.append(dict(partition_point=f"P{i}", edge_start_group=f"G{i+1}" if i < 9 else "none",
            edge_suffix=f"G{i+1}-G9" if i < 9 else "none",
            activation_shape=json.dumps(points[i]["expected_shape"]),
            activation_bytes=metadata["measurement_model_verification"][i]["activation_bytes"],
            sample_count=len(values), **stats,
            provenance="measured_cuda_event" if i < 9 else "defined_no_edge_processing"))
    with (output / "edge_suffix_summary.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    metadata["summary"] = summaries
    metadata["measured_sample_count"] = 9000
    metadata["warmup_sample_count"] = 900
    metadata["stage"] = "complete"
    print("EDGE_SUFFIX_PROCESSING_PROFILE_PASS", flush=True)


def main():
    output = ROOT / "split_inference/results/edge_processing_profile" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output.mkdir(parents=True, exist_ok=False)
    print(f"RESULT_DIRECTORY={output}", flush=True)
    begin = time.monotonic()
    metadata = {"started_utc": utc_now(), "status": "running", "stage": "initialization",
                "output": str(output), "command": [sys.executable, *sys.argv],
                "git": {key: command(args, required=True) for key, args in {
                    "commit": ["git", "rev-parse", "HEAD"],
                    "branch": ["git", "branch", "--show-current"],
                    "status": ["git", "status", "--short", "--branch"],
                }.items()},
                "runtime_difference": "Thor: torch 2.14.0a0+4fdf77b940.nv26.08 / torchvision 0.29.0a0+0bc41e67.nv26.08; Edge: torch 2.13.0 / torchvision 0.28.0. Deployment-environment profile, not a controlled same-runtime device comparison.",
                "future_e2e_requirement": "Deploy identical model parameters on Thor and Edge, compare state_dict identifiers using the same hash method, and revalidate P0-P9 recombined outputs before E2E. Seed 0 alone does not establish cross-runtime state identity."}
    try:
        run(output, metadata)
        metadata["status"] = "passed"
    except BaseException:
        metadata["status"] = "failed"
        metadata["error"] = traceback.format_exc()
        (output / "failure.log").write_text(metadata["error"])
        raise
    finally:
        metadata["ended_utc"] = utc_now()
        metadata["run_wall_seconds_monotonic"] = time.monotonic() - begin
        write_json(output / "metadata.json", metadata)


if __name__ == "__main__":
    main()
