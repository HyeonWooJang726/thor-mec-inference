"""Plot pretrained ImageNet group time/size and time density/conversion ratio.

Uses the committed, lossless summary copy from run 20260915T112015Z; no model,
CUDA execution, or dataset access. Writes only PNG/PDF/SVG. Existing files at
--output are rejected so a reviewed new rendering can replace them explicitly.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.container import BarContainer
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/imagenet_profile/20260915T112015Z/group_summary.csv"
MANIFEST = ROOT / "manifests/efficientnet_v2_s_p0_p9.json"
NAME = "efficientnetv2s_layer_group_characteristics"
DEFAULT_OUTPUT = ROOT / "results/thor_processing_profile/20260915T181507/layer_group_characteristics"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = [args.output / f"{NAME}.{ext}" for ext in ("png", "pdf", "svg")]
    if any(p.exists() for p in paths):
        raise FileExistsError("Render into a fresh directory before replacing existing figures")
    rows = list(csv.DictReader(SOURCE.open()))
    manifest = json.loads(MANIFEST.read_text())
    assert [r["group"] for r in rows] == [f"G{i}" for i in range(1, 10)]
    values = []
    for i, row in enumerate(rows, 1):
        assert int(row["n"]) == 1500 and row["dtype"] == "torch.float32"
        shape = json.loads(row["output_shape"])
        assert shape == manifest["points"][i]["expected_shape"]
        size = math.prod(shape) * 4
        assert size == int(row["output_bytes"])
        assert size / 2**20 == float(row["output_mib"])
        input_size = math.prod(manifest["points"][i-1]["expected_shape"]) * 4
        assert input_size == int(row["input_bytes"])
        assert json.loads(row["input_shape"]) == manifest["points"][i-1]["expected_shape"]
        mean = float(row["mean_ms"])
        assert math.isfinite(mean) and mean > 0
        density = mean / (input_size * 8 / 1e6)
        sigma = size / input_size
        assert math.isclose(density, float(row["processing_time_density_ms_per_mbit"]), rel_tol=1e-14)
        assert sigma == float(row["bit_conversion_ratio"])
        values.append(dict(group=row["group"], mean_ms=mean,
                           input_bytes=input_size, output_bytes=size, output_mib=size / 2**20,
                           processing_time_density_ms_per_mbit=density, bit_conversion_ratio=sigma))

    # When local run evidence is available, require agreement with the original
    # validated measurement. CSV line endings may differ in the committed copy.
    run = ROOT / "results/thor_imagenet_profile/20260915T112015Z"
    if (run / "metadata.json").exists():
        metadata = json.loads((run / "metadata.json").read_text())
        assert metadata["status"] == "passed"
        assert metadata["weight_enum"] == "EfficientNet_V2_S_Weights.IMAGENET1K_V1"
        assert metadata["validation"]["passed"] is True
        raw_summary = run / "group_summary.csv"
        assert hashlib.sha256(raw_summary.read_bytes()).hexdigest() == metadata["artifact_sha256"]["group_summary.csv"]
        assert rows == list(csv.DictReader(raw_summary.open()))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.labelsize": 13, "xtick.labelsize": 11,
                         "ytick.labelsize": 11, "legend.fontsize": 10,
                         "axes.linewidth": .7, "pdf.fonttype": 42,
                         "svg.fonttype": "none", "svg.hashsalt": "pretrained-imagenet-300",
                         "figure.facecolor": "white", "axes.facecolor": "white"})
    teal, rust = "#167D8D", "#C95D4B"
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.5))
    fig.subplots_adjust(left=.085, right=.915, bottom=.24, top=.95, wspace=.55)
    x, width = np.arange(9), .36
    specs = [
        ("mean_ms", "output_mib", "Processing time (ms)", "Output data size (MiB)",
         "Processing time", "Output data size"),
        ("processing_time_density_ms_per_mbit", "bit_conversion_ratio",
         "Processing-time density (ms/Mbit)", "Bit conversion ratio (bits/bit)",
         "Processing-time density", "Bit conversion ratio"),
    ]
    measured_heights = {}
    texts, legends, secondary = [], [], []
    for left, spec, panel in zip(axes, specs, ("(a)", "(b)")):
        right = left.twinx()
        secondary.append(right)
        lk, rk, ll, rl, ln, rn = spec
        lv, rv = [v[lk] for v in values], [v[rk] for v in values]
        lb = left.bar(x-width/2, lv, width, color=teal, edgecolor="black", linewidth=.5)
        rb = right.bar(x+width/2, rv, width, color=rust, edgecolor="black", linewidth=.5)
        for bars, expected, metric in ((lb, lv, lk), (rb, rv, rk)):
            actual = [p.get_height() for p in bars]
            assert actual == expected
            measured_heights[metric] = actual
            for i, patch in enumerate(bars, 1):
                patch.set_gid(f"{metric}-G{i}")
        left.set_xlim(-.65, 8.65)
        left.set_xticks(x, [r["group"] for r in rows])
        left.set_xlabel("Layer group index", labelpad=8)
        left.set_ylabel(ll, color=teal, labelpad=8)
        right.set_ylabel(rl, color=rust, labelpad=8)
        left.tick_params(axis="y", colors=teal)
        right.tick_params(axis="y", colors=rust)
        left.set_ylim(0, max(lv)*1.38)
        right.set_ylim(0, max(rv)*1.38)
        left.grid(axis="y", color="#dedede", linewidth=.5, alpha=.65)
        left.set_axisbelow(True)
        legend = right.legend([lb, rb], [ln, rn], loc="upper right", frameon=False)
        legends.append(legend)
        texts.append(left.text(.5, -.205, panel, transform=left.transAxes,
                               ha="center", va="top", fontsize=12))
        texts.extend([left.xaxis.label, left.yaxis.label, right.yaxis.label])
        for ax in (left, right):
            assert not ax.lines and not ax.collections
            assert all(isinstance(c, BarContainer) and c.errorbar is None for c in ax.containers)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for left, right, legend in zip(axes, secondary, legends):
        texts.extend(legend.get_texts())
        texts.extend(left.get_xticklabels())
        for ax in (left, right):
            texts.extend(t for t in ax.get_yticklabels()
                         if ax.get_ylim()[0] <= t.get_position()[1] <= ax.get_ylim()[1])
            for container in ax.containers:
                for patch in container:
                    assert not legend.get_window_extent(renderer).overlaps(patch.get_window_extent(renderer)), "Legend overlaps bars"
    for i, text in enumerate(texts):
        assert not any(token in text.get_text().lower() for token in
                       ("mean", "p95", "p99", "sample", "thor", "jetson", "cycles/bit"))
        box = text.get_window_extent(renderer)
        assert fig.bbox.contains(box.x0, box.y0) and fig.bbox.contains(box.x1, box.y1), ("clipped", text.get_text())
        for other in texts[i+1:]:
            assert not box.overlaps(other.get_window_extent(renderer)), ("overlap", text.get_text(), other.get_text())
    assert math.isclose(axes[0].get_position().width, axes[1].get_position().width)
    assert math.isclose(axes[0].get_position().height, axes[1].get_position().height)
    args.output.mkdir(parents=True, exist_ok=True)
    fig.savefig(paths[0], dpi=600)
    fig.savefig(paths[1], metadata={"CreationDate": None, "ModDate": None, "Creator": None})
    fig.savefig(paths[2], metadata={"Date": None, "Creator": None})
    # Keep generated SVG text suitable for git diff --check; path tokens unchanged.
    paths[2].write_text("\n".join(line.rstrip() for line in paths[2].read_text().splitlines())+"\n")
    plt.close(fig)
    print(json.dumps(dict(status="passed", source=str(SOURCE),
                          source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                          weight_enum="EfficientNet_V2_S_Weights.IMAGENET1K_V1",
                          values=values, rendered_bar_heights=measured_heights,
                          output_units={"time": "ms", "activation_size": "MiB",
                                        "density": "ms/Mbit", "conversion_ratio": "bits/bit"},
                          density_definition="mean_ms / (input_bytes * 8 / 1e6)",
                          frequency_status="MAXN+DVFS; no measured frequency; cycles not derived",
                          colors={"processing": teal, "data": rust},
                          png_dpi=600, text_clipping_or_overlap=False), indent=2))


if __name__ == "__main__":
    main()
