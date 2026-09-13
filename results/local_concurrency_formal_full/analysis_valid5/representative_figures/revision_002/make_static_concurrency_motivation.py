#!/usr/bin/env python3
"""CPU-only plot from saved valid5 metrics. Never overwrites any figure.

K5 queue/service rendering is adapted from the validated revision_001 plotting
block (same means, ddof=1 SD, markers, styles, shading, and shared linear axis).
Only this new main figure is rendered; the supplementary heatmap is referenced.
"""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import tempfile

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='motivation_mpl_'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    script = Path(__file__).resolve()
    root = next(p for p in script.parents if (p / '.git').exists())
    base = root / 'results/local_concurrency_formal_full'
    parent = base / 'analysis_valid5/representative_figures'
    old = parent / 'revision_001'
    out = script.parent
    if any(p.name != script.name for p in out.iterdir()):
        out = next(parent / f'revision_{i:03d}' for i in range(2, 10000)
                   if not (parent / f'revision_{i:03d}').exists())
        out.mkdir()
        (out / script.name).write_bytes(script.read_bytes())
    source = base / 'formal_per_run_summary_valid5.csv'
    aggregate = base / 'formal_kc_aggregate_valid5.csv'
    protected = [source, aggregate, base / 'campaign_status.json', base / 'valid5_integrity.json',
                 base / 'analysis_valid5/kc_full_summary.csv', root / '.gitignore',
                 root / 'scripts/profile_tcp_throughput.py', root / 'scripts/profile_edge_realtime.py']
    for folder in [old, base / 'analysis_valid5/figures', root / 'scripts/partitioning']:
        protected.extend(p for p in folder.rglob('*') if p.is_file())
    before = {p: sha(p) for p in protected}
    status = subprocess.check_output(['git', 'status', '--short'], cwd=root)
    rows = read(source)
    assert len(rows) == 280 and all(r['status'] == 'PASS' for r in rows)
    assert len({r['source_artifact'] for r in rows}) == 280
    assert sum(int(r['completed_frames']) for r in rows) == 2016000
    groups = {(k, c): [r for r in rows if int(r['K']) == k and int(r['C']) == c]
              for k in range(1, 8) for c in range(1, 9)}
    assert all(len(g) == 5 for g in groups.values())
    assert {r['run_id'] for r in groups[2, 1]} == {'run01', 'run02', 'run03', 'run05', 'replacement01'}
    replacement = next(r for r in groups[2, 1] if r['run_id'] == 'replacement01')
    assert replacement['acquisition_phase'] == 'POST_CAMPAIGN_REPLACEMENT'
    assert replacement['actual_round_id'] == ''
    reference = {(int(r['K']), int(r['C']), r['metric']): r for r in read(aggregate)}
    requests = [('a', k, c, 'deadline_miss_percent') for k in [5, 6, 7] for c in range(1, 9)]
    requests += [('b', 5, c, m) for c in range(1, 9) for m in ['queue_mean_ms', 'service_mean_ms']]
    stats, records = {}, []
    for panel, k, c, metric in requests:
        group = groups[k, c]
        values = [float(r[metric]) for r in group]
        mean, sd = statistics.mean(values), statistics.stdev(values)
        ref = reference[k, c, metric]
        assert int(ref['n_valid']) == 5
        assert math.isclose(mean, float(ref['mean']), rel_tol=1e-12, abs_tol=1e-12)
        assert math.isclose(sd, float(ref['sample_SD']), rel_tol=1e-12, abs_tol=1e-12)
        stats[k, c, metric] = mean, sd
        records.append(dict(panel=panel, K=k, C=c, metric=metric, mean=mean, sample_SD=sd, n=5,
                            unit='percent' if panel == 'a' else 'ms', source_csv=str(source.relative_to(root)),
                            source_column=metric, source_sha256=before[source],
                            run_values=json.dumps(values), run_ids=json.dumps([r['run_id'] for r in group]),
                            actual_round_ids=json.dumps([r['actual_round_id'] for r in group]),
                            acquisition_phases=json.dumps([r['acquisition_phase'] for r in group]),
                            source_artifacts=json.dumps([r['source_artifact'] for r in group])))
    # Independently retain consistency with the existing K5 plotted source data.
    for row in read(old / 'figure_source_data.csv'):
        if row['record_type'] == 'condition_summary' and row['panel'] == 'a':
            key = int(row['K']), int(row['C']), row['metric']
            mean, sd = stats[key]
            assert math.isclose(mean, float(row['mean']), rel_tol=1e-12, abs_tol=1e-12)
            assert math.isclose(sd, float(row['sample_SD']), rel_tol=1e-12, abs_tol=1e-12)

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                         'axes.labelsize': 9, 'axes.titlesize': 9, 'xtick.labelsize': 8.5,
                         'ytick.labelsize': 8.5, 'legend.fontsize': 8.5,
                         'axes.linewidth': .7, 'lines.linewidth': 1.6,
                         'lines.markersize': 4.5, 'pdf.fonttype': 42,
                         'figure.facecolor': 'white', 'axes.facecolor': 'white'})
    fig, (left, right) = plt.subplots(1, 2, figsize=(7.1, 3.45))
    fig.subplots_adjust(left=.09, right=.975, bottom=.18, top=.90, wspace=.37)
    for ax in [left, right]:
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(axis='y', color='.90', linewidth=.5)
        ax.set_axisbelow(True)
    cs = list(range(1, 9))
    left.set_title('(a) Deadline response by workload', loc='left', pad=9)
    for k, color, marker, style in [(5, '#009E73', 'o', '-'),
                                     (6, '#0072B2', 's', '--'),
                                     (7, '#D55E00', '^', '-.')]:
        means, sds = zip(*(stats[k, c, 'deadline_miss_percent'] for c in cs))
        left.errorbar(cs, means, yerr=sds, color=color, marker=marker, linestyle=style,
                      capsize=2.5, elinewidth=1, label=f'K = {k}', zorder=3, clip_on=False)
    left.set(xlim=(.7, 8.3), ylim=(0, 100), xticks=cs,
             xlabel='Request concurrency cap C', ylabel='Deadline miss rate (%)')
    left.legend(loc='center right', bbox_to_anchor=(.99, .48), frameon=False, borderaxespad=.2)

    # Reused revision_001 K5 plotting logic; only panel position/title changes.
    right.set_title('(b) Queue and service at K = 5', loc='left', pad=9)
    right.axvspan(4, 5, color='.90', zorder=0)
    tops = []
    for metric, label, color, marker, style in [
            ('queue_mean_ms', 'Queue waiting', '#0072B2', 'o', '-'),
            ('service_mean_ms', 'Service time', '#D55E00', 's', '--')]:
        means, sds = zip(*(stats[5, c, metric] for c in cs))
        right.errorbar(cs, means, yerr=sds, color=color, marker=marker, linestyle=style,
                       capsize=2.5, elinewidth=1, label=label, zorder=3)
        tops.extend(m + s for m, s in zip(means, sds))
    right.set(xlim=(.7, 8.3), ylim=(0, max(tops) * 1.25), xticks=cs,
              xlabel='Request concurrency cap C', ylabel='Mean time (ms)')
    right.legend(loc='upper left', frameon=False, borderaxespad=.25)
    name = 'fig_main_static_concurrency_motivation'
    for ext in ['pdf', 'png']:
        target = out / f'{name}.{ext}'
        assert not target.exists()
        fig.savefig(target, dpi=300, facecolor='white')
    plt.close(fig)
    with (out / 'figure_source_data.csv').open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    q4, q5 = (stats[5, c, 'queue_mean_ms'][0] for c in [4, 5])
    s4, s5 = (stats[5, c, 'service_mean_ms'][0] for c in [4, 5])
    caption = f'''# Main manuscript figure: static concurrency response

## 한국어 설명

(a)는 K5·K6·K7의 C=1..8 전체 DMR을 동일한 선형 0–100% 축에서 비교한다. Workload에 따라 관측상 유리한 C가 달라지고, C 증가가 항상 DMR을 개선하지는 않는다. 이는 같은 데이터에서 관측한 static configuration 비교이며, 모든 조건에서 하나의 C가 명확한 winner라는 의미가 아니다. (b)는 K5의 queue waiting과 system-level service time을 함께 보여준다. 강조한 C4–C5 구간에서 queue mean은 {q4:.3f}→{q5:.3f} ms로 감소하고 service mean은 {s4:.3f}→{s5:.3f} ms로 증가한다. 이 동반 변화만으로 DMR 변화의 원인이 입증되지는 않는다. Dynamic-C의 필요성·우월성 또는 실제 개선량을 입증한 그림이 아니다.

## English manuscript caption

**Workload-dependent responses to static application-level request-concurrency caps.** (a) Deadline miss rate (DMR) versus cap C for K=5, 6, and 7 input streams, displayed on a common linear 0–100% scale. Observationally favorable static caps differ with workload, and increasing C does not consistently improve deadline performance. (b) Mean inference-ready queue waiting (s−r) and system-level request service time (c−s) at K=5 share a linear time axis. The shaded C4–C5 interval highlights a concurrent decrease in queue waiting ({q4:.3f} to {q5:.3f} ms) and increase in service time ({s4:.3f} to {s5:.3f} ms). Points are means of five repeated runs (n=5); error bars are run-level sample standard deviations (ddof=1), not confidence intervals. The same video content is repeated, with 30 FPS offered per active stream for 60 s and a deadline of exactly 1/30 s after logical arrival. All startup and drain frames are retained. Lines connect separate static acquisitions, not dynamic cap transitions or a time sequence. Queue and service changes do not alone establish the cause of DMR changes, nor do these measurements establish the necessity or superiority of Dynamic-C control.

## Data and statistical definitions

- Primary valid5 inclusion is unchanged: 56 conditions, five valid runs each, 280 runs and 2,016,000 frames. K2/C1 uses replacement01 instead of failed original run04; the post-campaign replacement is never treated as original Round 4. The plotted K5–K7 data use their original valid acquisitions.
- Experimental unit: run, not frame. Five repetitions of identical video content measure run-to-run system variability, not five independent workload samples. No outliers or startup frames are excluded.
- Deadline miss: `(c_ns−a_ns)*30 > 1_000_000_000`; DMR = `100*miss_frames/completed_frames`. Queue waiting = s−r; service = c−s. Service is host-observed system-level request time, not isolated GPU kernel time. Queue plus service is not complete local latency.
- All plotted values are computed from the original per-run CSV at stored precision, using `statistics.mean` and `statistics.stdev` (n−1 denominator), then checked against the stored valid5 aggregate. The K5 queue/service values are additionally checked against revision_001 source data. Only displayed text is rounded. The 40 source-data rows retain all five run values, source paths, actual rounds and SHA256 provenance.
- C is an application admission cap on in-flight frame requests, not batch size, stream count K, CUDA thread count, or physical GPU parallelism. Both panels compare fixed-C runs. No smoothing, double y-axis, significance symbols or optimal-cap labels are used. The Formal counterexamples, including DMR increases despite lower mean service, remain valid.
- This focused main figure uses the requested K5–K7 workloads. The unmodified supplementary heatmap in revision_001 retains the full K1–K7 grid on the common 0–100% scale. It is linked, never regenerated. The existing two-panel representative Figure 2 is also preserved.
- Rendering reuses the validated revision_001 K5 queue/service plotting block with the panel relocated. Width: 7.1 inches; embedded TrueType vector PDF and 300 dpi PNG. Fonts ≥8.5 pt; markers and line styles distinguish curves independently of color. The full-scale K5 curve remains visible without an inset.

## Reproduction

Run `python3 make_static_concurrency_motivation.py` with the repository's existing Matplotlib installation. If output files exist, a new unused sibling revision is selected. The script never calls a GPU runtime, profiling tool or prior analysis generator. Matplotlib cache is outside the repository. No raw trace is parsed.

Input SHA256:

'''
    for p in [source, aggregate, old / 'make_representative_figures.py', old / 'figure_source_data.csv']:
        caption += f'- `{p.relative_to(root)}`: `{sha(p)}`\n'
    assert all(sha(p) == h for p, h in before.items())
    assert subprocess.check_output(['git', 'status', '--short'], cwd=root) == status
    caption += f'\nPreservation check: PASS; {len(before)} protected files, SHA256 mismatches=0. Entire revision_001 preserved. GPU executions=0; commit/push=NO.\n'
    with (out / 'captions.md').open('x') as f:
        f.write(caption)
    index = '# Manuscript figure selection\n\n'
    for role, folder, stem in [('Main text', out, name),
                               ('Final supplementary heatmap (unchanged)', old, 'fig_main01_static_dmr_map')]:
        index += f'## {role}\n\n'
        for ext in ['png', 'pdf']:
            target = folder / f'{stem}.{ext}'
            rel = os.path.relpath(target, out)
            index += f'- [{ext.upper()}]({rel}) — `{target.relative_to(root)}`\n'
    index += '\nThe existing revision_001 Figure 2 is retained unchanged. Only the new main-text figure is generated in this revision.\n'
    with (out / 'figure_list.md').open('x') as f:
        f.write(index)
    print(json.dumps({'output': str(out), 'source_records': len(records),
                      'K5_queue_C4_C5_ms': [q4, q5], 'K5_service_C4_C5_ms': [s4, s5],
                      'protected_files': len(before), 'preservation': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()
