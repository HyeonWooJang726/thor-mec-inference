#!/usr/bin/env python3
"""Render Figure 4 from existing five-run aggregate CSVs; no analysis rerun."""

import csv
import math
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "analysis/figures/figure_4_capacity_deadline_gap.png"


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def main():
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    demand_rows = read_csv(ROOT / "analysis/temporal_queue/period_service_demand_summary.csv")
    formal_rows = read_csv(ROOT / "motivation_summary.csv")

    def demand(k, statistic):
        matches = [r for r in demand_rows if int(r["K"]) == k and r["row_type"] == statistic]
        assert len(matches) == 1 and int(matches[0]["run_count"]) == 5
        return float(matches[0]["period_inference_service_sum_mean_ms"])

    formal = {int(r["K"]): r for r in formal_rows}
    left_ks, right_ks = [4, 5, 6, 7], [4, 5, 6]
    means = [demand(k, "mean") for k in left_ks]
    deviations = [demand(k, "sample_sd") for k in left_ks]
    components = [
        ("frame_start_lag_mean_ms", "Start lag", "#999999"),
        ("front_end_mean_ms", "Front end", "#56B4E9"),
        ("inference_queue_wait_mean_ms", "Inference queue wait", "#D55E00"),
        ("inference_mean_ms", "Inference service", "#009E73"),
    ]
    period = 1000 / 30
    assert means[2] < period < means[3]
    for k in right_ks:
        assert int(formal[k]["run_count"]) == 5
        total = sum(float(formal[k][field]) for field, _, _ in components)
        e2e = float(formal[k]["e2e_mean_ms"])
        # Floating-point CSV serialization can differ by a few last-place bits.
        assert math.isclose(total, e2e, rel_tol=0, abs_tol=1e-10)
        print(f"K{k}: stack={total:.12f} ms; E2E={e2e:.12f} ms; error={total-e2e:.3g} ms")
    assert f"{float(formal[6]['inference_queue_wait_mean_ms']):.2f}" == "25.78"
    assert f"{float(formal[6]['e2e_mean_ms']):.2f}" == "43.62"
    miss_labels = [f"Miss {float(formal[k]['deadline_miss_pct']):.2f}%" for k in right_ks]
    assert miss_labels == ["Miss 0.85%", "Miss 4.91%", "Miss 35.05%"]
    assert all(math.isfinite(v) for v in means + deviations)

    # Keep Matplotlib's cache outside the preserved analysis artifacts.
    import os
    with tempfile.TemporaryDirectory(prefix="capacity-deadline-mpl-") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.rcParams.update({
            "font.family": "DejaVu Sans", "font.size": 10, "axes.labelsize": 10,
            "xtick.labelsize": 9, "ytick.labelsize": 9, "legend.fontsize": 8.5,
            "axes.spines.top": False, "axes.spines.right": False,
            "axes.grid": False, "savefig.dpi": 350,
        })
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.5), layout="constrained")
        left, right = axes
        left.bar(left_ks, means, yerr=deviations, color="#0072B2", width=.6,
                 capsize=3, error_kw={"elinewidth": 1})
        left.set_ylabel("Average total inference time\nper period (ms)")
        left.set_ylim(0, 42)
        left.axhline(period, color="black", ls="--", lw=1,
                     label="Frame period (33.33 ms)")

        bottom = [0.0] * len(right_ks)
        component_handles = []
        for field, label, color in components:
            values = [float(formal[k][field]) for k in right_ks]
            bars = right.bar(right_ks, values, bottom=bottom, color=color,
                             label=label, width=.6)
            component_handles.append(bars)
            bottom = [b + v for b, v in zip(bottom, values)]
        right.set_ylabel("Mean E2E latency (ms)")
        right.set_ylim(0, 50)
        deadline = right.axhline(period, color="black", ls="--", lw=1,
                                 label="Candidate deadline (33.33 ms)")
        for k, total, label in zip(right_ks, bottom, miss_labels):
            right.annotate(label, (k, total), xytext=(0, 5), textcoords="offset points",
                           ha="center", va="bottom", fontsize=8.5)
        for ax, ks in zip(axes, [left_ks, right_ks]):
            ax.set_xticks(ks)
            ax.set_xlabel("Streams K")
        left.legend(loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False,
                    borderaxespad=0)
        right.legend(handles=[deadline], loc="lower left", bbox_to_anchor=(0, 1.01),
                     frameon=False, borderaxespad=0)
        fig.legend(component_handles, [label for _, label, _ in components],
                   loc="outside lower center", ncol=4, frameon=False,
                   columnspacing=1.2, handlelength=1.5)

        assert all(not ax.get_title() for ax in axes)
        assert not any(t.get_text() in {"(a)", "(b)", "(c)"}
                       for t in fig.findobj(matplotlib.text.Text))
        # Exclusive creation protects existing figures, including this one.
        with OUTPUT.open("xb") as destination:
            fig.savefig(destination, format="png", dpi=350, bbox_inches="tight", facecolor="white")
        plt.close(fig)
    print("Service demand means (ms):", dict(zip(left_ks, means)))
    print("PASS: five-run aggregates, four-component E2E sums, deadline annotations; PNG only.")
    print(OUTPUT)


if __name__ == "__main__":
    main()
