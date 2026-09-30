#!/usr/bin/env python3
"""Draw Grid03-mini paper figures from frozen schedules and measured CSVs.

No runtime/analyzer imports, inference, network access, or source-data writes.
Default: threshold-independent Figures A--C. --eta adds a separate variant.
Existing outputs are never overwritten; --output-dir can select a fresh folder.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
import xml.etree.ElementTree as ET

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='grid03-paper-mpl-'))
import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.text import Text
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'results/timely_capacity_campaign/v2_2/grid03_mini01'
DEFAULT_OUTPUT = ROOT / 'paper/figures/grid03_mini'
RATES = (208, 216, 224, 232)
PATTERNS = ('ALIGNED', 'STAGGERED')
LABELS = {'ALIGNED': 'Concentrated', 'STAGGERED': 'Dispersed'}
INPUT_NAMES = (
    'assignment_manifest.json', 'assignment_table.csv', 'ASSIGNMENT_PHASE_AUDIT.md',
    'GRID03_MINI_PREREGISTRATION.md', 'ANALYSIS_SPECIFICATION.md',
    'analysis01/per_run.csv', 'analysis01/paired_comparison.csv',
    'analysis01/per_stream.csv', 'analysis01/per_path.csv',
    'analysis01/validity_summary.json', 'analysis01/grid03_mini_verdict.json',
)
LOCAL = '#cdd2d4'
EDGE = '#0072b2'
INK = '#343a40'
MIN_FONT = 8.5
FORMATS = ('pdf', 'svg', 'png')
STEMS = ('fig_temporal_placement_structure', 'fig_temporal_placement_results',
         'fig_pathwise_temporal_effect')


def require(ok, message):
    if not ok:
        raise ValueError('Figure validation failed: ' + message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(name):
    with (SOURCE / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def near(a, b):
    # Round-off tolerance for cross-file arithmetic only, never a TIR threshold.
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)


def load_validate():
    missing = [name for name in INPUT_NAMES if not (SOURCE / name).is_file()]
    require(not missing, f'missing canonical inputs: {missing}')
    before = {name: sha(SOURCE / name) for name in INPUT_NAMES}
    documents = {name: (SOURCE / name).read_text() for name in INPUT_NAMES if name.endswith('.md')}
    require(all(documents.values()), 'empty frozen documentation')
    assignment = json.loads((SOURCE / 'assignment_manifest.json').read_text())
    table = csv_rows('assignment_table.csv')
    require(len(table) == 8 * 30 * 8, 'assignment table cardinality')
    schedules = {}
    for rate in RATES:
        for pattern in PATTERNS:
            rows = [r for r in table if int(r['Local_FPS']) == rate and r['placement'] == pattern]
            keys = [(int(r['stream_id']), int(r['source_slot'])) for r in rows]
            require(len(keys) == 240 and set(keys) == {(k, n) for k in range(8) for n in range(30)},
                    f'{rate}/{pattern}: exact stream/slot identities and uniqueness')
            manifest = assignment[f'L{rate}{pattern}']
            local = np.empty((8, 30), dtype=int)
            offsets = np.empty((8, 30), dtype=np.int64)
            for row in rows:
                k, n = int(row['stream_id']), int(row['source_slot'])
                require(row['assignment'] in ('LOCAL', 'EDGE'), 'unknown destination')
                require(int(row['Edge_FPS']) == 240 - rate, 'split total')
                require(int(row['phase']) == manifest['phase_vector'][k], 'phase vector')
                local[k, n] = int(row['assignment'] == 'LOCAL')
                offsets[k, n] = int(row['scheduled_source_offset_ns'])
            edge = 1 - local
            ml, me = local.sum(axis=0), edge.sum(axis=0)
            require(local.tolist() == manifest['local_masks'] and edge.tolist() == manifest['edge_masks'],
                    f'{rate}/{pattern}: table/manifest cell equality')
            require(ml.tolist() == manifest['m_L'] and me.tolist() == manifest['m_E'], 'per-slot load')
            require(local.sum(axis=1).tolist() == manifest['local_count_per_stream_per_30'], 'Local counts')
            require(edge.sum(axis=1).tolist() == manifest['edge_count_per_stream_per_30'], 'Edge counts')
            require(int(local.sum()) == rate and int(edge.sum()) == 240 - rate, 'one-second total')
            require(int(me.max()) == manifest['edge_peak'] and int(ml.max()) == manifest['local_peak'],
                    'assignment peaks')
            require(all(int(r['m_E']) == me[int(r['source_slot'])] and
                        int(r['m_L']) == ml[int(r['source_slot'])] for r in rows), 'table load columns')
            schedules[rate, pattern] = dict(local=local, edge=edge, ml=ml, me=me,
                                           offsets=offsets, phase=manifest['phase_vector'])
        a, b = (schedules[rate, p] for p in PATTERNS)
        require(np.array_equal(a['local'].sum(axis=1), b['local'].sum(axis=1)) and
                np.array_equal(a['edge'].sum(axis=1), b['edge'].sum(axis=1)), 'placement count equality')
        require(np.array_equal(a['offsets'], b['offsets']), 'source timestamps unchanged')
    require(schedules[224, 'ALIGNED']['phase'] == [0] * 8, 'representative concentrated phases')
    require(schedules[224, 'STAGGERED']['phase'] == [0, 2, 4, 6, 8, 9, 11, 13], 'dispersed phases')
    require(schedules[224, 'ALIGNED']['me'].max() == 8 and
            schedules[224, 'STAGGERED']['me'].max() == 1, 'representative Edge peaks')

    runs = csv_rows('analysis01/per_run.csv')
    expected = {(r, p, j) for r in RATES for p in PATTERNS for j in (1, 2, 3)}
    keys = [(int(x['rate_local']), x['pattern'], int(x['round'])) for x in runs]
    require(len(keys) == 24 and len(set(keys)) == 24 and set(keys) == expected, '24 measured conditions')
    require(len({r['run_id'] for r in runs}) == 24, 'unique measured run IDs')
    by = {key: row for key, row in zip(keys, runs)}
    for (rate, pattern, repeat), row in by.items():
        require(row['integrity_status'] == 'VALID', f"{row['run_id']}: invalid measured run")
        require([int(row[k]) for k in ('C_L', 'C_E', 'B')] == [3, 1, 1], 'mini runtime cardinality')
        require(int(row['rate_edge']) + rate == 240, 'measured split')
        for key in ('worst_stream_TIR', 'TIR_total', 'Local_assigned_TIR', 'Edge_assigned_TIR'):
            require(math.isfinite(float(row[key])) and 0 <= float(row[key]) <= 1, 'finite measured TIR')
    validity = json.loads((SOURCE / 'analysis01/validity_summary.json').read_text())
    verdict = json.loads((SOURCE / 'analysis01/grid03_mini_verdict.json').read_text())
    require(validity['valid_count'] == validity['planned'] == 24 and not validity['errors'], 'validity summary')
    require(verdict['primary_verdict'] != 'GRID03_MINI_INVALID', 'invalid analyzer dataset')

    streams = csv_rows('analysis01/per_stream.csv')
    paths = csv_rows('analysis01/per_path.csv')
    require(len(streams) == 24 * 8 and len(paths) == 24 * 2, 'stream/path cardinality')
    for row in runs:
        ss = [s for s in streams if s['run_id'] == row['run_id']]
        pp = [p for p in paths if p['run_id'] == row['run_id']]
        require(len(ss) == 8 and {int(s['value']) for s in ss} == set(range(8)), 'stream identities')
        require(len(pp) == 2 and {p['value'] for p in pp} == {'LOCAL', 'EDGE'}, 'path identities')
        for s in ss + pp:
            require(int(s['admitted']) == sum(int(s[k]) for k in ('timely', 'late', 'expired')), 'terminal accounting')
            require(near(s['TIR'], int(s['timely']) / int(s['admitted'])), 'TIR denominator')
        require(near(row['worst_stream_TIR'], min(float(s['TIR']) for s in ss)), 'R_min/per-stream agreement')
        require(near(row['total_timely_FPS'], sum(float(s['timely_FPS']) for s in ss)), 'aggregate timely FPS')
        for p in pp:
            prefix = 'Local' if p['value'] == 'LOCAL' else 'Edge'
            require(near(row[f'{prefix}_timely_FPS'], p['timely_FPS']), 'path timely FPS')
            require(near(row[f'{prefix}_assigned_TIR'], p['TIR']), 'path assigned TIR')

    pairs = csv_rows('analysis01/paired_comparison.csv')
    metrics = ('worst_stream_TIR', 'total_timely_FPS', 'Local_timely_FPS', 'Edge_timely_FPS')
    pair_keys = [(int(p['rate_local']), p['metric']) for p in pairs]
    require(len(pair_keys) == 16 and len(set(pair_keys)) == 16 and
            set(pair_keys) == {(r, m) for r in RATES for m in metrics}, 'paired table coverage')
    paired = {key: value for key, value in zip(pair_keys, pairs)}
    for (rate, metric), row in paired.items():
        values = [float(row[f'R{j}']) for j in (1, 2, 3)]
        require(all(near(v, float(by[rate, 'STAGGERED', j][metric]) -
                         float(by[rate, 'ALIGNED', j][metric])) for j, v in enumerate(values, 1)), 'paired direction')
        require(near(row['mean'], statistics.mean(values)), 'paired mean')

    # Supplied rounded values are validation checks only; never plot coordinates.
    references = {
        'ALIGNED': ((.8667, .8667, .8667), (.9000, .9000, .9000),
                    (.9322, .9333, .9333), (.7972, .8339, .8100)),
        'STAGGERED': ((.9933, .9994, .9989), (.9967, .9950, .9994),
                     (1., .9983, .9967), (.7850, .7400, .7339)),
    }
    for pattern, rows in references.items():
        for rate, values in zip(RATES, rows):
            require(all(abs(float(by[rate, pattern, j]['worst_stream_TIR']) - value) <= .000051
                        for j, value in enumerate(values, 1)), 'supplied four-decimal reference')
    return schedules, by, paired, verdict, before


def style():
    font_path = font_manager.findfont('Liberation Sans', fallback_to_default=False)
    plt.rcParams.update({
        'font.family': 'Liberation Sans', 'font.size': 9,
        'axes.labelsize': 9, 'axes.titlesize': 10, 'axes.linewidth': .65,
        'xtick.labelsize': MIN_FONT, 'ytick.labelsize': MIN_FONT,
        'xtick.major.width': .65, 'ytick.major.width': .65,
        'xtick.major.size': 3, 'ytick.major.size': 3,
        'legend.fontsize': 9, 'legend.frameon': False,
        'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
        'svg.hashsalt': 'grid03-mini-paper-figures01',
        'savefig.facecolor': 'white', 'figure.facecolor': 'white',
        'hatch.linewidth': .45, 'text.usetex': False,
    })
    return font_path


def clean_axes(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis='y', color='#dddddd', linewidth=.45)


def structure(schedules):
    fig = plt.figure(figsize=(7.16, 4.2))
    matrix_axes, load_axes = [], []
    artists = []
    for i, pattern in enumerate(PATTERNS):
        x = .078 if i == 0 else .585
        ax = fig.add_axes([x, .46, .385, .36])
        load = fig.add_axes([x, .13, .385, .245])
        matrix_axes.append(ax)
        load_axes.append(load)
        data = schedules[224, pattern]
        for k in range(8):
            for n in range(30):
                edge = bool(data['edge'][k, n])
                cell = Rectangle((n, k), 1, 1, facecolor=EDGE if edge else LOCAL,
                                 edgecolor='white', linewidth=.35, hatch='///' if edge else None)
                ax.add_patch(cell)
                artists.append((cell, edge, bool(data['edge'][k, n])))
        ax.set(xlim=(0, 30), ylim=(8, 0), yticks=np.arange(8) + .5,
               yticklabels=[str(k) for k in range(8)], ylabel='Stream',
               xticks=np.array([0, 5, 10, 15, 20, 25, 29]) + .5,
               xticklabels=['0', '5', '10', '15', '20', '25', '29'])
        ax.tick_params(axis='x', labelbottom=False, bottom=False)
        ax.tick_params(axis='y', length=0)
        ax.set_title(f"({'ab'[i]}) {LABELS[pattern]}", loc='left', pad=9, fontweight='bold')
        for spine in ax.spines.values():
            spine.set_color('#999999')
        slots = np.arange(30) + .5
        load.step(slots, data['ml'], where='mid', color=INK, linestyle='--', linewidth=1,
                  marker='s', markersize=2.5, label='Local')
        load.step(slots, data['me'], where='mid', color=EDGE,
                  linestyle='-' if i == 0 else ':', linewidth=1.1,
                  marker='o' if i == 0 else '^', markersize=3, label='Edge')
        load.set(xlim=(0, 30), ylim=(-.6, 10.4), yticks=[0, 4, 8],
                 xticks=np.array([0, 5, 10, 15, 20, 25, 29]) + .5,
                 xticklabels=['0', '5', '10', '15', '20', '25', '29'],
                 ylabel='Assignments\nper slot', xlabel='Source slot n')
        clean_axes(load)
        arrow = dict(arrowstyle='->', color=INK, linewidth=.65, shrinkA=2, shrinkB=2)
        if i == 0:
            load.annotate('Edge burst', xy=(.5, 8), xytext=(4, 4.8), arrowprops=arrow,
                          fontsize=MIN_FONT)
            load.annotate('Local relief slot', xy=(15.5, 0), xytext=(17, 3), arrowprops=arrow,
                          fontsize=MIN_FONT)
        else:
            load.annotate('Smoothed Edge arrivals', xy=(11.5, 1), xytext=(5, 3.2),
                          arrowprops=arrow, fontsize=MIN_FONT)
            load.annotate('Continuous Local load', xy=(19.5, 8), xytext=(4, 9.3),
                          arrowprops=arrow, fontsize=MIN_FONT)
    legend = fig.legend(handles=[Patch(facecolor=LOCAL, edgecolor=INK, linewidth=.5, label='Local'),
                                 Patch(facecolor=EDGE, edgecolor=INK, linewidth=.5, hatch='///', label='Edge')],
                        loc='upper center', bbox_to_anchor=(.5, .995), ncol=2, columnspacing=2)
    fig.text(.5, .905, 'L224/E16  ·  8 streams  ·  30 FPS per stream', ha='center', fontsize=9)
    fig.text(.5, .025, 'Same average split, different temporal load shapes.', ha='center', fontsize=9)
    require(all(edge == reference for _, edge, reference in artists), 'plotted assignment cells')
    for i, pattern in enumerate(PATTERNS):
        require(np.array_equal(load_axes[i].lines[0].get_ydata(), schedules[224, pattern]['ml']) and
                np.array_equal(load_axes[i].lines[1].get_ydata(), schedules[224, pattern]['me']), 'plotted load traces')
    return fig, [legend], matrix_axes + load_axes


def results(by, eta=None):
    fig = plt.figure(figsize=(7.16, 3.15))
    ax = fig.add_axes([.09, .22, .885, .53])
    legends = []
    data = []
    for pattern, color, marker, line, offsets in (
        ('ALIGNED', INK, 'o', '--', [-1.05, -.70, -.35]),
        ('STAGGERED', EDGE, '^', '-', [.35, .70, 1.05]),
    ):
        means = []
        for rate in RATES:
            values = [float(by[rate, pattern, j]['worst_stream_TIR']) for j in (1, 2, 3)]
            points = ax.scatter(np.array(offsets) + rate, values, marker=marker, s=14,
                                facecolors='white' if pattern == 'ALIGNED' else color,
                                edgecolors=color, linewidths=.7, zorder=4)
            require(np.array_equal(np.asarray(points.get_offsets())[:, 1], values), 'raw repeat y coordinates')
            means.append(statistics.mean(values))
            data.extend(dict(run_id=by[rate, pattern, j]['run_id'], local_FPS=rate, edge_FPS=240-rate,
                             placement=LABELS[pattern], repeat=j, worst_stream_TIR=v,
                             display_x_offset_FPS=offsets[j-1]) for j, v in enumerate(values, 1))
        curve, = ax.plot(RATES, means, color=color, linestyle=line, linewidth=1.25,
                         marker=marker, markersize=6,
                         markerfacecolor='white' if pattern == 'ALIGNED' else color,
                         markeredgewidth=.85, zorder=3,
                         label='Temporally ' + LABELS[pattern].lower())
        require(np.array_equal(curve.get_ydata(), means), 'condition mean coordinates')
    ax.set(xlim=(206.2, 233.8), ylim=(.70, 1.022), xticks=RATES,
           yticks=np.arange(.70, 1.001, .05), xlabel='Local assigned rate [FPS]', ylabel='Worst-stream TIR')
    clean_axes(ax)
    top = ax.secondary_xaxis('top')
    top.set_xticks(RATES)
    top.set_xticklabels([str(240-rate) for rate in RATES])
    top.set_xlabel('Edge assigned rate [FPS]', labelpad=6)
    handles, labels = ax.get_legend_handles_labels()
    if eta is not None:
        ax.axhline(eta, color='#777777', linestyle=(0, (3, 3)), linewidth=.85, zorder=1)
        handles.append(Line2D([], [], color='#777777', linestyle='--', linewidth=.85))
        labels.append(f'Screening target η = {eta:g}')
    legend = fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5, .998),
                        ncol=3 if eta is not None else 2, columnspacing=1.3, handlelength=2.4,
                        fontsize=MIN_FONT if eta is not None else 9)
    legends.append(legend)
    fig.text(.5, .032, 'Small markers: all 3 repeats (horizontal offsets for visibility).  Large markers and lines: means.',
             ha='center', fontsize=MIN_FONT)
    return fig, legends, [ax], data


def pathwise(paired):
    fig = plt.figure(figsize=(7.16, 2.95))
    ax = fig.add_axes([.09, .22, .885, .60])
    positions = np.arange(4)
    data = []
    for offset, (metric, label, color, hatch) in zip((-.26, 0, .26), (
        ('Local_timely_FPS', 'Local', LOCAL, '///'),
        ('Edge_timely_FPS', 'Edge', EDGE, None),
        ('total_timely_FPS', 'Total', 'white', '...'),
    )):
        values = [float(paired[rate, metric]['mean']) for rate in RATES]
        bars = ax.bar(positions + offset, values, width=.23, color=color, edgecolor=INK,
                      linewidth=.7, hatch=hatch, label=label, zorder=2)
        require([bar.get_height() for bar in bars] == values, 'paired CSV bar heights')
        for i, rate in enumerate(RATES):
            row = paired[rate, metric]
            repeats = [float(row[f'R{j}']) for j in (1, 2, 3)]
            points = ax.scatter(positions[i] + offset + np.array([-.05, 0, .05]), repeats,
                                s=10, color=INK, marker='o', edgecolors='white', linewidths=.25, zorder=4)
            require(np.array_equal(np.asarray(points.get_offsets())[:, 1], repeats), 'paired repeat coordinates')
            data.append(dict(local_FPS=rate, edge_FPS=240-rate, path=label,
                             R1=repeats[0], R2=repeats[1], R3=repeats[2], mean=values[i]))
    ax.axhline(0, color=INK, linewidth=.7, zorder=3)
    ax.set(xticks=positions, xticklabels=[str(rate) for rate in RATES], xlim=(-.6, 3.6),
           xlabel='Local assigned rate [FPS]', ylabel='Δ timely FPS\n(Dispersed − Concentrated)')
    clean_axes(ax)
    legend = fig.legend(*ax.get_legend_handles_labels(), loc='upper center', bbox_to_anchor=(.5, .997),
                        ncol=3, columnspacing=2)
    fig.text(.5, .035, 'Bars: mean of 3 paired repeat differences.  Small markers: individual paired differences.',
             ha='center', fontsize=MIN_FONT)
    return fig, [legend], [ax], data


def validate_layout(fig, legends, axes):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    text_items = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text()]
    require(all(t.get_fontsize() >= MIN_FONT for t in text_items), 'minimum font size')
    for item in text_items:
        bbox = item.get_window_extent(renderer)
        require(canvas.x0 - .5 <= bbox.x0 and bbox.x1 <= canvas.x1 + .5 and
                canvas.y0 - .5 <= bbox.y0 and bbox.y1 <= canvas.y1 + .5,
                f'clipped text: {item.get_text()}')
    for legend in legends:
        bbox = legend.get_window_extent(renderer)
        require(all(not bbox.overlaps(ax.bbox) for ax in axes), 'legend overlaps data axes')
    return dict(minimum_text_font_pt=min(t.get_fontsize() for t in text_items),
                unclipped_text=True, legends_outside_data_axes=True,
                width_inches=float(fig.get_figwidth()), height_inches=float(fig.get_figheight()))


def save(fig, stem, output, legends, axes):
    layout = validate_layout(fig, legends, axes)
    generated = {}
    for extension in FORMATS:
        path = output / f'{stem}.{extension}'
        metadata = {'Creator': 'Grid03-mini paper plotting script', 'CreationDate': None, 'ModDate': None}
        if extension == 'svg':
            metadata = {'Creator': 'Grid03-mini paper plotting script', 'Date': None}
        elif extension == 'png':
            metadata = {'Software': 'Grid03-mini paper plotting script'}
        with path.open('xb') as stream:
            fig.savefig(stream, format=extension, dpi=600, metadata=metadata)
        if extension == 'pdf':
            require(path.read_bytes().startswith(b'%PDF-'), 'PDF output')
            require(b'/Subtype /Image' not in path.read_bytes(), 'PDF raster image embedded')
        elif extension == 'svg':
            root = ET.parse(path).getroot()
            require(not list(root.iter('{http://www.w3.org/2000/svg}image')), 'SVG raster image embedded')
            require(bool(list(root.iter('{http://www.w3.org/2000/svg}text'))), 'SVG editable vector text')
        else:
            with Image.open(path) as image:
                require(abs(image.info['dpi'][0] - 600) < .1, 'PNG 600 dpi metadata')
                require(abs(image.size[0] - 600 * fig.get_figwidth()) <= 1 and
                        abs(image.size[1] - 600 * fig.get_figheight()) <= 1, 'PNG dimensions')
                layout['png_pixels'] = list(image.size)
                layout['png_dpi'] = list(image.info['dpi'])
        generated[path.name] = sha(path)
    plt.close(fig)
    return dict(layout=layout, output_sha256=generated, vector_outputs=True, png_output=True)


def captions(eta):
    text = '''# Grid03-mini figure captions and reproduction

## Figure A — Temporal placement structure

Temporally concentrated placement and temporally dispersed placement at the
same L224/E16 average split (eight 30-FPS streams; 240 FPS in total). Each cell
shows one source-slot assignment, with Local in gray and Edge in hatched blue.
Concentrated aligns Edge assignments across streams; Dispersed shifts the
assignment phases using the frozen phase vector [0, 2, 4, 6, 8, 9, 11, 13].
The traces show per-slot Local and Edge assignment counts, m_L[n] and m_E[n].
Both schedules contain 224 Local and 16 Edge assignments per 30 source slots,
including two Edge assignments per stream. The peak Edge assignment count is
eight for Concentrated and one for Dispersed. Same average split, different
temporal load shapes. Source timestamps are unchanged; assignment phases do
not imply a change in physical camera capture timing or GPU start times.

Figure A displays the frozen assignment schedule, not measured execution times
or a causal explanation of performance.

## Figure B — Measured timely service (main, threshold-independent)

Measured worst-stream timely-inference ratio (TIR) for temporally concentrated
placement and temporally dispersed placement at four Local/Edge splits.
Small markers show all three measured repeats per condition; their horizontal
offsets are for visibility only. Large markers and lines show arithmetic means;
connecting lines are visual guides between tested points. The top axis gives
the corresponding Edge assigned rate. All 24 measured runs are VALID and use
C_L=3, C_E=1, B=1, eight 30-FPS streams, and a 100-ms relative deadline.
The main figure has no feasibility threshold line: it presents the measured
TIR values and run-to-run variation. Dispersed has higher worst-stream TIR at
L208/E32, L216/E24, and L224/E16; the measured ordering reverses at L232/E8.
This observation establishes neither global optimality nor a causal mechanism.

## Figure C — Path-wise temporal effect

Difference in timely FPS, Dispersed minus Concentrated, decomposed into Local,
Edge, and Total contributions at each tested split. Bars show the stored mean
of three paired repeat differences; small markers show all paired differences.
The Edge contribution is positive across the tested points, while the Local
contribution becomes negative at L232/E8. The measured path-wise contributions
have opposite signs at L232/E8. A causal mechanism is not established.

## Scope and terminology

Grid03-mini is not a strict one-factor reproduction of Grid02. Local concurrency
changes from two to three, and dispersed assignment phases use the preregistered
period-aware construction. Configuration A, the mini-grid runtime, and final
Configuration B are distinct; their repeats are not pooled. Internal assignment
labels are translated only for display. No claim is made about an optimal
placement, online-controller necessity or sufficiency, hysteresis, state-dependent
capacity, or a GPU/Edge queue causal mechanism.

All figures use Liberation Sans with text at least 8.5 pt at the native 7.16-inch
two-column width. Insert at the native width to retain the font-size guarantee.
PDF and SVG are vector-only; PNG is 600 dpi. Paths use hatches, line styles,
and/or marker shapes in addition to color, for grayscale legibility.

## Reproduction

```bash
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py
```

Optional screening-target variant:

```bash
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py --eta 0.99
```

Use `--output-dir <fresh-directory>` for another rendering; existing artifacts
are not overwritten. `FIGURE_DATA.json` records the exact plotted coordinates
and their CSV keys. `VALIDATION.json` records input/output SHA-256, cross-file
checks, native figure sizes, fonts, and output checks. No raw trace, analysis,
plan, preregistration, runtime, or Git index is modified.
'''
    if eta is not None:
        text += f'''
## Optional Figure B — Screening-target variant

Same measured data as the main Figure B, with the separately requested
screening operating target, eta = {eta:g}. The dashed reference is labeled
“Screening target η = {eta:g}”. It is an operational screening target and is
not a universal system requirement or a real-time standard. The main Figure B
remains threshold-independent.
'''
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eta', type=float, help='add a separate screening-target Figure B variant')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT, help='fresh output directory')
    args = parser.parse_args()
    if args.eta is not None:
        require(math.isfinite(args.eta) and 0 <= args.eta <= 1, 'eta must be a finite ratio')
    output = args.output_dir.resolve()
    require(not output.is_relative_to(ROOT / 'results'), 'never write into scientific results')
    schedules, by, paired, verdict, before = load_validate()
    font_path = style()
    stems = list(STEMS)
    eta_stem = None
    if args.eta is not None:
        eta_stem = f'fig_temporal_placement_results_eta{args.eta:g}'.replace('.', '')
        stems.append(eta_stem)
    names = [f'{stem}.{ext}' for stem in stems for ext in FORMATS]
    names += ['CAPTIONS.md', 'FIGURE_DATA.json', 'VALIDATION.json']
    collisions = [name for name in names if (output / name).exists() or (output / name).is_symlink()]
    require(not collisions, f'refusing to overwrite: {collisions}; use a fresh --output-dir')
    output.mkdir(parents=True, exist_ok=True)
    validation = {}
    fig, legends, axes = structure(schedules)
    validation[STEMS[0]] = save(fig, STEMS[0], output, legends, axes)
    fig, legends, axes, result_data = results(by)
    validation[STEMS[1]] = save(fig, STEMS[1], output, legends, axes)
    fig, legends, axes, path_data = pathwise(paired)
    validation[STEMS[2]] = save(fig, STEMS[2], output, legends, axes)
    if eta_stem:
        fig, legends, axes, eta_data = results(by, args.eta)
        require(eta_data == result_data, 'eta variant must preserve all measured coordinates')
        validation[eta_stem] = save(fig, eta_stem, output, legends, axes)
    after = {name: sha(SOURCE / name) for name in INPUT_NAMES}
    require(before == after, 'scientific source files changed')
    with (output / 'CAPTIONS.md').open('x') as stream:
        stream.write(captions(args.eta))
    data = dict(
        structure=dict(source_type='FROZEN_ASSIGNMENT_SCHEDULE', local_FPS=224, edge_FPS=16,
                       source_slots=list(range(30)), streams=list(range(8)),
                       placements={LABELS[p]: dict(local_masks=schedules[224, p]['local'].tolist(),
                                                  edge_masks=schedules[224, p]['edge'].tolist(),
                                                  m_L=schedules[224, p]['ml'].tolist(),
                                                  m_E=schedules[224, p]['me'].tolist(),
                                                  phase_vector=schedules[224, p]['phase']) for p in PATTERNS}),
        measured_results=result_data, paired_pathwise_measured_differences=path_data,
    )
    with (output / 'FIGURE_DATA.json').open('x') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write('\n')
    report = dict(
        source_directory=str(SOURCE.relative_to(ROOT)), input_sha256=before,
        script_path=str(Path(__file__).resolve().relative_to(ROOT)), script_sha256=sha(Path(__file__)),
        matplotlib_version=matplotlib.__version__, numpy_version=np.__version__,
        font_path=font_path, font_sha256=sha(Path(font_path)), minimum_font_pt=MIN_FONT,
        measured_run_count=24, raw_repeat_point_count=24, measured_integrity='24/24 VALID',
        preserved_analyzer_verdict=verdict['primary_verdict'],
        all_coordinates_from_source_data=True, no_fabricated_values=True,
        structure_is_frozen_schedule_not_measured_execution=True,
        assignment_counts_match_manifest=True, figure_B_repeats_match_per_run=True,
        figure_C_values_match_paired_comparison=True, stream_path_accounting_check='PASS',
        max_edge_burst_concentrated=8, max_edge_burst_dispersed=1,
        main_figure_has_threshold=False, optional_eta=args.eta,
        inputs_unchanged=True, new_workload_executed=False,
        figure_validation=validation,
        additional_output_sha256={n: sha(output / n) for n in ('CAPTIONS.md', 'FIGURE_DATA.json')},
    )
    with (output / 'VALIDATION.json').open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(output_directory=str(output), figures=stems,
                          raw_repeat_count=24, validation='PASS', sources_unchanged=True), indent=2))


if __name__ == '__main__':
    main()
