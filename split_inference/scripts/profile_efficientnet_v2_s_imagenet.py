"""Pretrained ImageNet group characterization; never substitutes random inputs.

Run in the existing NVIDIA PyTorch image with a read-only checkpoint cache and
dataset ZIP, network disabled, and a fresh writable output directory. The host
must first record preflight.json (MAXN/DVFS, GPU/process and Docker inspection).
Only --render uses existing CSVs; it never constructs a model or measures time.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import re
import struct
import sys
import traceback
from datetime import datetime, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = (
    "EfficientNetV2-S | EfficientNet_V2_S_Weights.IMAGENET1K_V1\n"
    "ImageNet-1K validation, 300 distinct images | FP32, batch 1, 384×384\n"
    "Thor MAXN, DVFS ON | Processing-time density: ms/Mbit, not GPU cycles/bit"
)


def dump(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write("\n")


def save_csv(path, rows):
    with path.open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def canonical_hash(state):
    """v1: sorted keys, length-framed JSON headers and little-endian raw bytes.

    For each key: uint64-LE header length, UTF-8 JSON [key,dtype,shape]
    (compact separators, ensure_ascii=True), uint64-LE payload length, then
    contiguous C-order little-endian CPU tensor bytes. Include every buffer.
    """
    assert sys.byteorder == "little"
    h = hashlib.sha256()
    for key in sorted(state):
        tensor = state[key].detach().cpu().contiguous()
        header = json.dumps([key, str(tensor.dtype), list(tensor.shape)],
                            separators=(",", ":"), ensure_ascii=True).encode()
        payload = tensor.numpy().tobytes(order="C")
        h.update(struct.pack("<Q", len(header)))
        h.update(header)
        h.update(struct.pack("<Q", len(payload)))
        h.update(payload)
    return h.hexdigest()


def render(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    rows = list(csv.DictReader((output / "group_summary.csv").open()))
    assert [r["group"] for r in rows] == [f"G{i}" for i in range(1, 10)]
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.labelsize": 13,
                         "xtick.labelsize": 11, "ytick.labelsize": 11,
                         "legend.fontsize": 10, "axes.linewidth": .7,
                         "pdf.fonttype": 42, "svg.fonttype": "none"})
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), facecolor="white")
    fig.subplots_adjust(left=.08, right=.92, top=.96, bottom=.37, wspace=.52)
    specs = [
        ("mean_ms", "output_mib", "Mean processing time (ms)", "Output data size (MiB)",
         "Mean processing time", "Output data size"),
        ("processing_time_density_ms_per_mbit", "bit_conversion_ratio",
         "Processing-time density (ms/Mbit)", "Bit conversion ratio (bits/bit)",
         "Processing-time density", "Bit conversion ratio"),
    ]
    x, width = np.arange(9), .36
    artists = []
    for ax, spec, panel in zip(axes, specs, ("(a)", "(b)")):
        other = ax.twinx()
        lk, rk, ll, rl, ln, rn = spec
        lv, rv = [float(r[lk]) for r in rows], [float(r[rk]) for r in rows]
        bars = ax.bar(x-width/2, lv, width, color="#0072B2", edgecolor="black", linewidth=.5)
        sizes = other.bar(x+width/2, rv, width, color="#E69F00", edgecolor="black", linewidth=.5)
        assert [b.get_height() for b in bars] == lv
        assert [b.get_height() for b in sizes] == rv
        ax.set_xticks(x, [r["group"] for r in rows])
        ax.set_xlabel("Layer group index", labelpad=8)
        ax.set_ylabel(ll, color="#0072B2", labelpad=8)
        other.set_ylabel(rl, color="#E69F00", labelpad=8)
        ax.tick_params(axis="y", colors="#0072B2")
        other.tick_params(axis="y", colors="#E69F00")
        ax.set_ylim(0, max(lv)*1.32)
        other.set_ylim(0, max(rv)*1.32)
        ax.grid(axis="y", color=".90", linewidth=.5)
        ax.set_axisbelow(True)
        artists.append(ax.legend([bars, sizes], [ln, rn], loc="upper right", frameon=False))
        artists.append(ax.text(.5, -.24, panel, transform=ax.transAxes, ha="center", va="top", fontsize=12))
    artists.append(fig.text(.5, .035, CONDITIONS, ha="center", va="bottom", fontsize=10, linespacing=1.5))
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for artist in artists + [a.xaxis.label for a in fig.axes] + [a.yaxis.label for a in fig.axes]:
        box = artist.get_window_extent(renderer)
        assert fig.bbox.contains(box.x0, box.y0) and fig.bbox.contains(box.x1, box.y1), str(artist)
    for ext in ("png", "pdf", "svg"):
        path = output / f"efficientnetv2s_imagenet_group_characteristics.{ext}"
        if path.exists():
            raise FileExistsError(path)
        fig.savefig(path, dpi=600, facecolor="white")
    plt.close(fig)


def profile(args, metadata):
    import numpy as np
    import PIL
    from PIL import Image
    import torch
    import torchvision
    from torchvision.models import EfficientNet_V2_S_Weights, efficientnet_v2_s
    from split_inference.src.common.efficientnet_v2_s_partitions import EfficientNetV2SPartitions, MANIFEST_PATH

    out = args.output
    preflight = json.loads((out / "preflight.json").read_text())
    assert preflight["safe_to_measure"] is True
    metadata.update(preflight=preflight, conditions=CONDITIONS,
                    seed=0, image_selection="Random(0).sample(sorted JPEG members, 300)",
                    rounds=5, images_per_round=300, warmup_per_group=100,
                    fixed_order=args.fixed_order, skip_render=args.skip_render,
                    corrupt_image_policy="Abort and record member/error; no skipping or replacement",
                    timer="CUDA events, end.synchronize per group; default stream",
                    excluded=["ZIP read", "JPEG decode", "preprocessing", "H2D", "CSV writes", "host wait"],
                    timing_caveat="Eager device timeline may include GPU idle gaps between launches",
                    canonical_hash_format=canonical_hash.__doc__,
                    versions={"python": sys.version, "torch": torch.__version__,
                              "torchvision": torchvision.__version__, "PIL": PIL.__version__,
                              "numpy": np.__version__, "cuda": torch.version.cuda,
                              "cudnn": torch.backends.cudnn.version()},
                    source_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in
                                   (Path(__file__).resolve(), MANIFEST_PATH,
                                    ROOT / "src/common/efficientnet_v2_s_partitions.py")})
    assert os.environ.get("TORCH_ALLOW_TF32_CUBLAS_OVERRIDE") == "0"
    assert os.environ.get("NVIDIA_TF32_OVERRIDE") == "0"
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = True
    assert not torch.backends.cuda.matmul.allow_tf32 and not torch.backends.cudnn.allow_tf32
    metadata.update(tf32=False, tf32_environment={k: os.environ[k] for k in
                    ("TORCH_ALLOW_TF32_CUBLAS_OVERRIDE", "NVIDIA_TF32_OVERRIDE")},
                    cudnn_benchmark=True, dtype="torch.float32", eval=True, inference_mode=True)
    assert torch.cuda.is_available() and torch.cuda.device_count() == 1
    metadata["gpu"] = torch.cuda.get_device_name(0)
    weights = EfficientNet_V2_S_Weights.IMAGENET1K_V1
    checkpoint = Path(torch.hub.get_dir()) / "checkpoints" / weights.url.rsplit("/", 1)[1]
    metadata["stage"] = "official_checkpoint_validation"
    assert checkpoint.is_file(), f"Official checkpoint missing: {checkpoint}; download separately, never fall back"
    checksum = file_hash(checkpoint)
    assert checksum.startswith(checkpoint.stem.rsplit("-", 1)[1]), checksum
    expected_hash = canonical_hash(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model = efficientnet_v2_s(weights=weights).float().eval()
    actual_hash = canonical_hash(model.state_dict())
    assert actual_hash == expected_hash
    metadata.update(weight_enum=str(weights), checkpoint_filename=checkpoint.name,
                    checkpoint_url=weights.url, checkpoint_sha256=checksum,
                    canonical_state_dict_sha256=actual_hash,
                    checkpoint_state_dict_sha256=expected_hash)
    model.cuda()
    parts = EfficientNetV2SPartitions(model)
    assert parts.model is model and all(not m.training for m in model.modules())
    transform = weights.transforms()
    metadata["preprocessing"] = repr(transform)
    metadata["manifest_note"] = "Unchanged project group/point structure; historical weights:null does not describe this run"
    points = parts.manifest["points"]

    def info(tensor, i):
        assert list(tensor.shape) == points[i]["expected_shape"]
        assert tensor.dtype == torch.float32
        size = tensor.numel() * tensor.element_size()
        assert size == math.prod(points[i]["expected_shape"]) * 4
        return dict(shape=list(tensor.shape), dtype=str(tensor.dtype), bytes=size)

    metadata["stage"] = "zip_structure_and_decode"
    tensors, evidence = [], []
    with zipfile.ZipFile(args.zip) as archive:
        members = sorted(archive.namelist())
        assert len(members) == len(set(members)), "Duplicate ZIP names"
        images = [n for n in members if n.lower().endswith((".jpeg", ".jpg", ".png"))]
        assert len(images) == 50000
        assert all(re.fullmatch(r"n\d{8}/ILSVRC2012_val_\d{8}\.JPEG", n) for n in images)
        assert len({Path(n).name for n in images}) == 50000
        assert len({n.split('/')[0] for n in images}) == 1000
        if args.fixed_order:
            selection_path = ROOT / "docs/imagenet_profile/20260915T112015Z/selected_imagenet_members.txt"
            selected = selection_path.read_text().splitlines()
            assert len(selected) == 300 and all(member in images for member in selected)
            metadata["image_selection"] = str(selection_path)
            metadata["input_order_sha256"] = file_hash(selection_path)
        else:
            selected = random.Random(0).sample(images, 300)
        assert len(set(selected)) == 300
        (out / "selected_imagenet_members.txt").write_text("\n".join(selected)+"\n")
        metadata["dataset"] = dict(path=str(args.zip), zip_bytes=args.zip.stat().st_size,
                                   zip_members=len(members), jpeg_count=len(images), classes=1000,
                                   sorted_members_sha256=hashlib.sha256("\n".join(members).encode()).hexdigest(),
                                   selected_members_sha256=file_hash(out / "selected_imagenet_members.txt"))
        for sample_id, member in enumerate(selected):
            metadata["current_member"] = member
            payload = archive.read(member)  # zipfile checks each selected entry's CRC.
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                image = image.convert("RGB")
                tensor = transform(image).unsqueeze(0).contiguous()
            info(tensor, 0)
            assert torch.isfinite(tensor).all()
            tensors.append(tensor)
            evidence.append(dict(sample_id=sample_id, member=member,
                                 jpeg_sha256=hashlib.sha256(payload).hexdigest(),
                                 preprocessed_fp32_sha256=hashlib.sha256(tensor.numpy().tobytes()).hexdigest()))
    save_csv(out / "selected_image_evidence.csv", evidence)
    print("Decoded 300 distinct ImageNet images; official state_dict", actual_hash, flush=True)

    metadata["stage"] = "pretrained_correctness"
    validation = []
    activation_info = None
    rtol, atol = 1e-5, 1e-6

    def compare(result, reference, sid, label):
        assert list(result.shape) == list(reference.shape) == [1, 1000]
        assert torch.isfinite(result).all() and torch.isfinite(reference).all()
        difference = (result-reference).abs()
        record = dict(sample_id=sid, member=selected[sid], execution=label,
                      output_shape="[1, 1000]", max_abs_diff=difference.max().item(),
                      max_rel_diff=(difference/reference.abs().clamp_min(1e-8)).max().item())
        validation.append(record)
        torch.testing.assert_close(result, reference, rtol=rtol, atol=atol)

    with torch.inference_mode():
        for sid, cpu in enumerate(tensors):
            metadata["current_member"] = selected[sid]
            x = cpu.cuda()
            reference = model(x)
            sequential = x
            current_info = [info(x, 0)]
            for i in range(9):
                sequential = parts._run(sequential, i, i+1)
                current_info.append(info(sequential, i+1))
            if activation_info is None:
                activation_info = current_info
            assert current_info == activation_info
            compare(sequential, reference, sid, "G1-G9")
            for point in range(10):
                compare(parts.suffix(parts.prefix(x, point), point), reference, sid, f"P{point}")
            if (sid+1) % 50 == 0:
                print(f"Correctness {sid+1}/300 passed", flush=True)
        torch.cuda.synchronize()
        save_csv(out / "validation.csv", validation)
        metadata["validation"] = dict(images=300, comparisons=len(validation), rtol=rtol, atol=atol,
                                      relative_error_floor=1e-8,
                                      max_abs_diff=max(r["max_abs_diff"] for r in validation),
                                      max_rel_diff=max(r["max_rel_diff"] for r in validation), passed=True)
        metadata["activations"] = activation_info
        print("All pretrained G1-G9 and P0-P9 comparisons passed", flush=True)

        start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        start.record()
        end.record()
        end.synchronize()
        raw_fields = ["phase", "round", "order", "sample_id", "imagenet_member", "group", "elapsed_ms"]
        metadata["round_seeds"] = [None] * 5 if args.fixed_order else list(range(1, 6))
        metadata["round_orders"] = []
        with (out / "raw_group_timing.csv").open("x", newline="", buffering=1) as f:
            writer = csv.DictWriter(f, fieldnames=raw_fields)
            writer.writeheader()

            def run_image(sid, phase, round_id, order):
                metadata["current_member"] = selected[sid]
                x = tensors[sid].cuda()
                torch.cuda.synchronize()  # H2D is outside all group event intervals.
                records = []
                for i in range(9):
                    assert info(x, i) == activation_info[i]
                    start.record()
                    result = parts._run(x, i, i+1)
                    end.record()
                    end.synchronize()
                    elapsed = start.elapsed_time(end)
                    assert math.isfinite(elapsed) and elapsed > 0
                    assert info(result, i+1) == activation_info[i+1]
                    records.append(dict(phase=phase, round=round_id, order=order, sample_id=sid,
                                        imagenet_member=selected[sid], group=f"G{i+1}", elapsed_ms=elapsed))
                    x = result
                assert torch.isfinite(x).all()
                writer.writerows(records)  # Never inside a CUDA event interval.

            metadata["stage"] = "warmup"
            metadata["warmup_sample_ids"] = list(range(100))
            for order in range(100):
                run_image(order, "warmup", -1, order)
            print("Actual-image warm-up: 100 per group complete", flush=True)
            for round_id, seed in enumerate(metadata["round_seeds"]):
                metadata["stage"] = f"measurement_round_{round_id}"
                order = list(range(300))
                if not args.fixed_order:
                    random.Random(seed).shuffle(order)
                metadata["round_orders"].append(order)
                for position, sid in enumerate(order):
                    run_image(sid, "measurement", round_id, position)
                print(f"Measurement round {round_id+1}/5 complete", flush=True)

    metadata["stage"] = "raw_validation_and_summary"
    raw = list(csv.DictReader((out / "raw_group_timing.csv").open()))
    assert len(raw) == 9*(100+5*300)
    summaries, shapes = [], []
    for i in range(9):
        group = f"G{i+1}"
        records = [r for r in raw if r["group"] == group]
        assert len([r for r in records if r["phase"] == "warmup"]) == 100
        measured = [r for r in records if r["phase"] == "measurement"]
        assert len(measured) == 1500
        for round_id in range(5):
            current = [r for r in measured if int(r["round"]) == round_id]
            assert [int(r["sample_id"]) for r in current] == metadata["round_orders"][round_id]
            assert [int(r["order"]) for r in current] == list(range(300))
            assert all(r["imagenet_member"] == selected[int(r["sample_id"])] for r in current)
        values = np.array([float(r["elapsed_ms"]) for r in measured])
        assert np.isfinite(values).all() and (values > 0).all()
        a, b = activation_info[i:i+2]
        row = dict(group=group, input_shape=json.dumps(a["shape"]), output_shape=json.dumps(b["shape"]),
                   dtype=a["dtype"], input_bytes=a["bytes"], output_bytes=b["bytes"],
                   input_mib=a["bytes"]/2**20, output_mib=b["bytes"]/2**20,
                   bit_conversion_ratio=b["bytes"]/a["bytes"])
        shapes.append(row)
        summaries.append(dict(group=group, n=len(values), mean_ms=float(values.mean()),
                              median_ms=float(np.median(values)), p95_ms=float(np.percentile(values,95)),
                              p99_ms=float(np.percentile(values,99)), std_ms=float(values.std(ddof=1)),
                              min_ms=float(values.min()), max_ms=float(values.max()),
                              **{k:v for k,v in row.items() if k != "group"},
                              processing_time_density_ms_per_mbit=float(values.mean())/(a["bytes"]*8/1e6)))
    assert canonical_hash(model.state_dict()) == actual_hash, "Model state changed"
    save_csv(out / "activation_shapes_bytes.csv", shapes)
    save_csv(out / "group_summary.csv", summaries)
    metadata["raw_validation"] = dict(passed=True, rows=len(raw), measured_per_group=1500,
                                      warmup_per_group=100, excluded_samples=0)
    metadata["artifact_sha256"] = {p.name: file_hash(p) for p in out.glob("*.csv")}
    if not args.skip_render:
        metadata["stage"] = "render"
        render(out)
    metadata["status"] = "passed"
    metadata["stage"] = "complete"
    print("ALL_PRETRAINED_IMAGENET_GROUP_PROFILE_PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=Path("/dataset/imagenet-val.zip"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixed-order", action="store_true",
                        help="Use the committed 300-member selection in file order in every round")
    render_options = parser.add_mutually_exclusive_group()
    render_options.add_argument("--render", action="store_true")
    render_options.add_argument("--skip-render", action="store_true",
                                help="Skip figure generation; matplotlib is not required")
    args = parser.parse_args()
    if args.render:
        render(args.output)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "metadata.json").exists():
        raise FileExistsError("Existing run: use a new output directory")
    metadata = dict(status="running", started_utc=datetime.now(timezone.utc).isoformat())
    try:
        profile(args, metadata)
    except BaseException:
        metadata["status"] = "failed"
        metadata["traceback"] = traceback.format_exc()
        raise
    finally:
        metadata["ended_utc"] = datetime.now(timezone.utc).isoformat()
        dump(args.output / "metadata.json", metadata)


if __name__ == "__main__":
    main()
