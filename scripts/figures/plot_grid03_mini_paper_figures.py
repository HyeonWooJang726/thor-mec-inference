#!/usr/bin/env python3
"""Draw Grid03-mini paper figures from frozen schedules and measured CSVs.

No runtime/analyzer imports, inference, network access, or source-data writes.
Default: threshold-independent Figures A--C. --eta adds a separate variant.
Uses the installed CPU Cairo renderer; no matplotlib or seaborn.
Existing outputs are never overwritten; --output-dir can select a fresh folder.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import io
import subprocess
import xml.etree.ElementTree as ET

import cairo
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
    'plan.json', 'runtime_manifest.json', 'source_sha256.json',
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
            require(np.all(ml + me == 8), 'eight assignments at every source slot')
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
        require(near(row['min'], min(values)) and near(row['max'], max(values)), 'paired observed range')
    for rate in RATES:
        for repeat in (1, 2, 3):
            require(near(paired[rate, 'total_timely_FPS'][f'R{repeat}'],
                         float(paired[rate, 'Local_timely_FPS'][f'R{repeat}']) +
                         float(paired[rate, 'Edge_timely_FPS'][f'R{repeat}'])), 'paired Total = Local + Edge')

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



def stats(values):
    return dict(mean=statistics.mean(values), min=min(values), max=max(values), values=list(values))


def color(value):
    if value == 'white':
        return (1., 1., 1.)
    return tuple(int(value[i:i+2], 16)/255 for i in (1, 3, 5))


class Drawing:
    """Point-coordinate drawing shared by PDF, SVG, and the 600-dpi raster."""
    def __init__(self, context, width, height):
        self.ctx, self.width, self.height = context, width, height
        self.font_sizes, self.texts = [], []
        self.ctx.set_source_rgb(1, 1, 1)
        self.ctx.paint()

    def line(self, points, ink=INK, width=.65, dash=()):
        require(all(-.1 <= x <= self.width+.1 and -.1 <= y <= self.height+.1 for x, y in points),
                'line outside figure bounds')
        self.ctx.save()
        self.ctx.set_source_rgb(*color(ink))
        self.ctx.set_line_width(width)
        self.ctx.set_dash(dash)
        self.ctx.move_to(*points[0])
        for point in points[1:]:
            self.ctx.line_to(*point)
        self.ctx.stroke()
        self.ctx.restore()

    def rectangle(self, x, y, w, h, fill, border=None, hatch=None, hatch_ink=INK):
        require(w >= 0 and h >= 0 and 0 <= x <= x+w <= self.width and
                0 <= y <= y+h <= self.height, 'rectangle outside figure bounds')
        self.ctx.save()
        self.ctx.rectangle(x, y, w, h)
        self.ctx.set_source_rgb(*color(fill))
        self.ctx.fill_preserve()
        if border:
            self.ctx.set_source_rgb(*color(border))
            self.ctx.set_line_width(.5)
            self.ctx.stroke()
        else:
            self.ctx.new_path()
        if hatch:
            self.ctx.rectangle(x, y, w, h)
            self.ctx.clip()
            self.ctx.set_source_rgb(*color(hatch_ink))
            self.ctx.set_line_width(.4)
            if hatch == '///':
                for offset in np.arange(-h, w+h, 6):
                    self.ctx.move_to(x+offset, y+h)
                    self.ctx.line_to(x+offset+h, y)
                self.ctx.stroke()
            else:
                for xx in np.arange(x+2, x+w, 5):
                    for yy in np.arange(y+2, y+h, 5):
                        self.ctx.arc(xx, yy, .45, 0, 2*math.pi)
                        self.ctx.fill()
        self.ctx.restore()

    def text(self, x, y, value, size=9, align='left', rotation=0, bold=False):
        require(size >= MIN_FONT, 'minimum font size')
        self.ctx.save()
        self.ctx.select_font_face('Liberation Sans', cairo.FONT_SLANT_NORMAL,
                                  cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        self.ctx.set_font_size(size)
        xb, yb, w, h, advance, _ = self.ctx.text_extents(value)
        shift = -advance/2 if align == 'center' else -advance if align == 'right' else 0
        c, s = math.cos(rotation), math.sin(rotation)
        corners = [(x+c*xx-s*yy, y+s*xx+c*yy)
                   for xx in (xb+shift, xb+shift+w) for yy in (yb, yb+h)]
        require(all(-.5 <= xx <= self.width+.5 and -.5 <= yy <= self.height+.5 for xx, yy in corners),
                'clipped text: '+value)
        self.ctx.translate(x, y)
        self.ctx.rotate(rotation)
        self.ctx.set_source_rgb(*color(INK))
        self.ctx.move_to(shift, 0)
        self.ctx.show_text(value)
        self.ctx.restore()
        self.font_sizes.append(size)
        self.texts.append(value)

    def marker(self, x, y, marker, ink, radius=3):
        self.ctx.save()
        if marker == 'circle':
            self.ctx.arc(x, y, radius, 0, 2*math.pi)
        else:
            self.ctx.move_to(x, y-radius)
            self.ctx.line_to(x-radius, y+radius)
            self.ctx.line_to(x+radius, y+radius)
            self.ctx.close_path()
        self.ctx.set_source_rgb(*color('white' if marker == 'circle' else ink))
        self.ctx.fill_preserve()
        self.ctx.set_source_rgb(*color(ink))
        self.ctx.set_line_width(.85)
        self.ctx.stroke()
        self.ctx.restore()

    def errorbar(self, x, mean, low, high, ymap, ink=INK):
        require(low <= mean <= high, 'mean inside observed range')
        if low == high:
            return  # Never inflate a zero observed range.
        top, bottom = ymap(high), ymap(low)
        self.line([(x, top), (x, bottom)], ink, .8)
        for y in (top, bottom):
            self.line([(x-4, y), (x+4, y)], ink, .8)


def axes(d, box, xvalues, xlabels, yticks, ylim, xlabel, ylabel):
    left, top, width, height = box
    lo, hi = ylim
    ymap = lambda v: top + (hi-v)/(hi-lo)*height
    for tick in yticks:
        y = ymap(tick)
        d.line([(left, y), (left+width, y)], '#dddddd', .45)
        d.line([(left-3, y), (left, y)])
        label = f'{tick:.2f}' if hi < 2 else f'{tick:g}'
        d.text(left-6, y+3, label, MIN_FONT, 'right')
    d.line([(left, top), (left, top+height), (left+width, top+height)])
    for x, label in zip(xvalues, xlabels):
        d.line([(x, top+height), (x, top+height+3)])
        d.text(x, top+height+15, label, MIN_FONT, 'center')
    d.text(left+width/2, top+height+29, xlabel, 9, 'center')
    d.text(14, top+height/2, ylabel, 9, 'center', -math.pi/2)
    return ymap


def structure(d, schedules):
    column_starts = (40., 302.)
    column_width = 198.
    matrix_top, matrix_height = 48., 108.
    load_top, load_height = 173., 64.
    require(all(schedules[224, 'ALIGNED']['ml'][n] == 0 for n in (0, 15)),
            'concentrated slots 0 and 15 have zero Local assignments')
    legend_start = d.width/2-55
    for x, label, fill, hatch in [(legend_start, 'Local', LOCAL, None),
                                 (legend_start+68, 'Edge', EDGE, '///')]:
        d.rectangle(x, 5, 20, 9, fill, INK, hatch)
        d.text(x+25, 14, label)
    for i, pattern in enumerate(PATTERNS):
        left = column_starts[i]
        data = schedules[224, pattern]
        d.text(left, 36, f"({'ab'[i]}) {LABELS[pattern]}", 10, bold=True)
        for k in range(8):
            for n in range(30):
                edge = bool(data['edge'][k, n])
                d.rectangle(left+n*column_width/30, matrix_top+k*matrix_height/8,
                            column_width/30, matrix_height/8,
                            EDGE if edge else LOCAL, 'white', '///' if edge else None, 'white')
        for k in range(8):
            d.text(left-7, matrix_top+(k+.5)*matrix_height/8+3, str(k), MIN_FONT, 'right')
        d.text(left-25, matrix_top+matrix_height/2, 'Stream', 9, 'center', -math.pi/2)
        # Matrix cells occupy [n,n+1); the load step has exactly the same edges.
        ymap = lambda v: load_top + (8.5-v)/9*load_height
        for tick in (0, 1, 4, 7, 8):
            yy = ymap(tick)
            d.line([(left, yy), (left+column_width, yy)], '#dddddd', .45)
            d.line([(left-3, yy), (left, yy)])
            d.text(left-6, yy+3, str(tick), MIN_FONT, 'right')
        d.line([(left, load_top), (left, load_top+load_height),
                (left+column_width, load_top+load_height)])
        for n in (0, 5, 10, 15, 20, 25, 29):
            x = left+(n+.5)*column_width/30
            d.line([(x, load_top+load_height), (x, load_top+load_height+3)])
            d.text(x, load_top+load_height+15, str(n), MIN_FONT, 'center')
        d.text(left+column_width/2, load_top+load_height+29, 'Source slot n', 9, 'center')
        d.text(left-25, load_top+load_height/2, 'Frames assigned per slot', MIN_FONT,
               'center', -math.pi/2)
        for field, ink, dash in [('ml', INK, (3, 2)), ('me', EDGE, ())]:
            points = []
            for n, count in enumerate(data[field]):
                points.extend([(left+n*column_width/30, ymap(count)),
                               (left+(n+1)*column_width/30, ymap(count))])
            d.line(points, ink, 1.05, dash)
        require(data['ml'][0] >= 0 and ymap(0) < load_top+load_height, 'zero steps visible inside axes')
    return dict(scatter_count=0, load_marker_count=0, footer_count=0,
                workload_title=False, annotations=False, step_edges_aligned_to_matrix=True,
                source_slot_zero_Local_visible=True, source_slot_fifteen_Local_visible=True,
                path_style_consistent_across_panels=True)


def results(d, by, eta=None):
    left, top, width, height = 46., 58., 456., 105.
    xmap = lambda v: left+(v-206.2)/(233.8-206.2)*width
    ymap = axes(d, (left, top, width, height), [xmap(r) for r in RATES],
                 [str(r) for r in RATES], np.arange(.70, 1.001, .05), (.70, 1.022),
                 'Local assigned rate [FPS]', 'Worst-stream TIR')
    d.text(left+width/2, 34, 'Edge assigned rate [FPS]', 9, 'center')
    d.line([(left, top), (left+width, top)])
    for rate in RATES:
        x = xmap(rate)
        d.line([(x, top), (x, top-3)])
        d.text(x, top-8, str(240-rate), MIN_FONT, 'center')
    entries = [('Temporally concentrated', INK, (4, 3), 'circle'),
               ('Temporally dispersed', EDGE, (), 'triangle')]
    if eta is not None:
        entries.append((f'Reference: η = {eta:g}', '#777777', (3, 3), None))
        require(.70 <= eta <= 1, 'eta reference within plotted TIR range')
        d.line([(left, ymap(eta)), (left+width, ymap(eta))], '#777777', .8, (3, 3))
    # Fixed legend boxes are outside the data area.
    starts = (70, 285) if eta is None else (18, 202, 388)
    font_size = 9 if eta is None else MIN_FONT
    for x, (label, ink, dash, marker) in zip(starts, entries):
        d.line([(x, 11), (x+22, 11)], ink, 1.1, dash)
        if marker:
            d.marker(x+11, 11, marker, ink, 2.6)
        d.text(x+27, 14, label, font_size)
    data = []
    for pattern, ink, dash, marker in [('ALIGNED', INK, (4, 3), 'circle'),
                                      ('STAGGERED', EDGE, (), 'triangle')]:
        observed = [stats([float(by[r, pattern, j]['worst_stream_TIR']) for j in (1, 2, 3)]) for r in RATES]
        d.line([(xmap(r), ymap(s['mean'])) for r, s in zip(RATES, observed)], ink, 1.25, dash)
        for rate, s in zip(RATES, observed):
            d.errorbar(xmap(rate), s['mean'], s['min'], s['max'], ymap, ink)
            d.marker(xmap(rate), ymap(s['mean']), marker, ink)
            data.append(dict(local_FPS=rate, edge_FPS=240-rate, placement=LABELS[pattern], **s,
                             lower=s['mean']-s['min'], upper=s['max']-s['mean']))
    return dict(scatter_count=0, jitter_count=0, footer_count=0, condition_mean_count=8,
                errorbar_definition='observed min-max across three runs; not CI or SE',
                mean_min_max=data, reference_eta=eta)


def pathwise(d, paired):
    left, top, width, height = 58., 39., 444., 112.
    vals = [float(paired[r, m][f'R{j}']) for r in RATES
            for m in ('Local_timely_FPS', 'Edge_timely_FPS', 'total_timely_FPS') for j in (1, 2, 3)]
    margin = .08*(max(vals)-min(vals))
    limits = (min(vals)-margin, max(vals)+margin)
    # Include the complete outer bars and caps, not just the group centers.
    xmap = lambda v: left+(v-205)/(235-205)*width
    ticks = [v for v in range(-30, 31, 10) if limits[0] <= v <= limits[1]]
    ymap = axes(d, (left, top, width, height), [xmap(r) for r in RATES], [str(r) for r in RATES],
                 ticks, limits, 'Local assigned rate [FPS]', 'Δ timely FPS (Dispersed − Concentrated)')
    d.line([(left, ymap(0)), (left+width, ymap(0))], INK, .75)
    data = []
    entries = [('Local_timely_FPS', 'Local', LOCAL, '///', -1.8),
               ('Edge_timely_FPS', 'Edge', EDGE, None, 0),
               ('total_timely_FPS', 'Total', 'white', '...', 1.8)]
    for i, (metric, label, fill, hatch, offset) in enumerate(entries):
        xx = d.width/2-101+i*75
        d.rectangle(xx, 5, 22, 10, fill, INK, hatch)
        d.text(xx+28, 14, label)
        for rate in RATES:
            row = paired[rate, metric]
            s = stats([float(row[f'R{j}']) for j in (1, 2, 3)])
            require(near(s['mean'], row['mean']) and near(s['min'], row['min']) and near(s['max'], row['max']),
                    'paired stored mean/min/max')
            # The bar uses the stored mean verbatim; the range uses paired R1--R3.
            mean = float(row['mean'])
            x = xmap(rate+offset)
            bar_width = xmap(rate+1.5)-xmap(rate)
            d.rectangle(x-bar_width/2, min(ymap(0), ymap(mean)), bar_width,
                        abs(ymap(mean)-ymap(0)), fill, INK, hatch)
            d.errorbar(x, mean, s['min'], s['max'], ymap)
            data.append(dict(local_FPS=rate, edge_FPS=240-rate, path=label,
                             R1=s['values'][0], R2=s['values'][1], R3=s['values'][2],
                             mean=mean, min=s['min'], max=s['max'],
                             lower=mean-s['min'], upper=s['max']-mean))
    return dict(scatter_count=0, footer_count=0, bar_count=12, paired_mean_min_max=data,
                errorbar_definition='min-max of three same-repeat Dispersed minus Concentrated differences')


def save(stem, output, size, painter):
    width, height = (v*72 for v in size)
    checks = []
    generated = {}
    for extension in FORMATS:
        path = output / f'{stem}.{extension}'
        buffer = io.BytesIO()
        if extension == 'pdf':
            surface = cairo.PDFSurface(buffer, width, height)
            surface.set_metadata(cairo.PDF_METADATA_CREATOR, 'Grid03-mini paper plotting script')
            surface.set_metadata(cairo.PDF_METADATA_CREATE_DATE, '2000-01-01T00:00:00Z')
            surface.set_metadata(cairo.PDF_METADATA_MOD_DATE, '2000-01-01T00:00:00Z')
        elif extension == 'svg':
            surface = cairo.SVGSurface(buffer, width, height)
            surface.restrict_to_version(cairo.SVG_VERSION_1_2)
        else:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, round(size[0]*600), round(size[1]*600))
        ctx = cairo.Context(surface)
        if extension == 'png':
            ctx.scale(600/72, 600/72)
        drawing = Drawing(ctx, width, height)
        check = painter(drawing)
        require(not any(any(word in t for word in ('Small markers:', 'Bars: mean', 'Edge burst',
                'Local relief slot', 'Smoothed Edge arrivals', 'Continuous Local load',
                'Same average split', 'L224/E16')) for t in drawing.texts), 'removed text reappeared')
        check.update(minimum_font_pt=min(drawing.font_sizes), width_inches=size[0], height_inches=size[1],
                     unclipped_text=True, legend_outside_data=True)
        checks.append(check)
        if extension == 'png':
            surface.write_to_png(buffer)
            buffer.seek(0)
            with Image.open(buffer) as image:
                with path.open('xb') as stream:
                    image.save(stream, format='PNG', dpi=(600, 600))
        else:
            surface.finish()
            with path.open('xb') as stream:
                stream.write(buffer.getvalue())
        surface.finish()
        if extension == 'pdf':
            require(path.read_bytes().startswith(b'%PDF-') and b'/Subtype /Image' not in path.read_bytes(), 'vector PDF')
        elif extension == 'svg':
            svg = ET.parse(path).getroot()
            require(not list(svg.iter('{http://www.w3.org/2000/svg}image')), 'vector SVG')
        else:
            with Image.open(path) as image:
                require(abs(image.info['dpi'][0]-600) < .1, '600 dpi PNG')
        generated[path.name] = sha(path)
    require(checks[0] == checks[1] == checks[2], 'identical data and layout across formats')
    return dict(layout_and_data=checks[0], output_sha256=generated, vector_outputs=True, png_output=True)


def captions(eta):
    text = """# Grid03-mini figure captions and reproduction

## Figure A — Temporal placement structure

Temporally concentrated placement and temporally dispersed placement at the same
L224/E16 mean split, with K=8 and F=30 FPS per stream. The 30 scheduled source
slots span one second. Each stream is assigned 28 Local frames and two Edge
frames, so both placements have identical total and per-stream assignment counts
(224 Local and 16 Edge). Concentrated aligns Edge assignments across streams;
Dispersed uses the frozen assignment phase vector [0, 2, 4, 6, 8, 9, 11, 13].
The lower step curves show the number of frames assigned to each path in each
source slot, with the same colors and line styles in both panels. A Local
assignment count of zero does not imply GPU idle. Scheduled assignment times
are distinct from actual queue arrivals, socket submissions, and GPU execution
start times. The assignment phases do not change the common source phase or
establish synchronized physical camera capture. This figure describes the
frozen schedule, not measured GPU load or Edge receive times.

## Figure B — Worst-stream timely service

Measured worst-stream TIR at four Local/Edge splits for temporally concentrated
placement and temporally dispersed placement. Markers and asymmetric error bars
show means and observed ranges across three runs: lower=mean-min and
upper=max-mean. All 24 VALID measured runs are included. The ranges are not
confidence intervals or standard errors; zero ranges are not enlarged.
Connecting lines guide the eye between measured operating points and estimate
neither unmeasured performance nor a crossing point. The upper axis reports the
corresponding Edge assigned rate. Runs use C_L=3, C_E=1, B=1, K=8, F=30 FPS,
and D=100 ms. The main figure contains no eta reference line.

## Figure C — Path-wise timely FPS difference

Paired timely FPS difference, Dispersed minus Concentrated, decomposed into
Local, Edge, and Total. Grouped bars show paired means, and asymmetric error
bars show the observed min-max range of three paired-run differences. Each
difference is computed within the same split and repeat before summarization;
the ranges are not obtained by subtracting the two conditions' extrema.
Positive values mean Dispersed provided more timely results; negative values
mean Concentrated provided more. Total=Local+Edge within each paired repeat,
up to floating-point representation. This is a path-wise measured decomposition.
At L232/E8 the Local and Edge contributions have opposite signs. It does not
establish a causal mechanism involving Local relief, GPU idle, or hysteresis.

## Scope and reproduction

Grid03-mini is not a strict one-factor reproduction of Grid02: C_L changes from
two to three, and dispersed assignment phases use the preregistered period-aware
rule. Configuration A, the mini-grid runtime, and final Configuration B are
not pooled. Historical verdicts and screening targets remain unchanged. No claim
is made about global optimality, controller necessity or sufficiency,
state-dependent capacity, or a GPU/Edge queue causal mechanism.

Figures use the installed CPU Cairo renderer, without matplotlib or seaborn.
PDF/SVG contain vector drawing and vector font glyphs; PNG is 600 dpi. Liberation
Sans is used at a minimum 8.5 pt at the native 7.16-inch two-column width. No
font file is copied. The PDF metadata date is fixed solely for reproducible
rendering and is not an experiment date.

```bash
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py --output-dir <fresh-directory>
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py --eta 0.99 --output-dir <fresh-directory>
```

Existing outputs are never overwritten by the generator. VALIDATION.json holds
current mean/min/max coordinates, all input SHA-256, output checksums, and layout
checks. The preexisting FIGURE_DATA.json is retained unchanged as the prior
rendering's coordinate record; its former jitter offsets are not used by this
version. No scientific data, plan, preregistration, or runtime is modified.
"""
    if eta is not None:
        text += f"""
## Optional Figure B — Reference variant

The separate eta variant shows the same means and observed ranges, with the
line labeled “Reference: η = {eta:g}”. At eta=0.99 this is the mini-grid's
preregistered screening target, not a universal standard or a requirement for
all experiments. It does not change the main threshold-independent figure.
"""
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eta', type=float, help='add a separate reference Figure B variant')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT, help='fresh output directory')
    args = parser.parse_args()
    if args.eta is not None:
        require(math.isfinite(args.eta) and .70 <= args.eta <= 1, 'eta within plotted TIR range')
    output = args.output_dir.resolve()
    require(not output.is_relative_to(ROOT/'results'), 'never write into scientific results')
    schedules, by, paired, verdict, before = load_validate()
    font_path = Path(subprocess.check_output(['fc-match', '-f', '%{file}', 'Liberation Sans'], text=True))
    require(font_path.is_file() and 'LiberationSans' in font_path.name, 'installed Liberation Sans')
    stems = list(STEMS)
    eta_stem = f'fig_temporal_placement_results_eta{args.eta:g}'.replace('.', '') if args.eta is not None else None
    if eta_stem:
        stems.append(eta_stem)
    names = [f'{s}.{ext}' for s in stems for ext in FORMATS] + ['CAPTIONS.md', 'VALIDATION.json']
    require(not any((output/n).exists() or (output/n).is_symlink() for n in names),
            'refusing to overwrite; use a fresh --output-dir')
    output.mkdir(parents=True, exist_ok=True)
    validation = {
        STEMS[0]: save(STEMS[0], output, (7.16, 3.75), lambda d: structure(d, schedules)),
        STEMS[1]: save(STEMS[1], output, (7.16, 2.75), lambda d: results(d, by)),
        STEMS[2]: save(STEMS[2], output, (7.16, 2.60), lambda d: pathwise(d, paired)),
    }
    if eta_stem:
        validation[eta_stem] = save(eta_stem, output, (7.16, 2.75), lambda d: results(d, by, args.eta))
        require(validation[eta_stem]['layout_and_data']['mean_min_max'] ==
                validation[STEMS[1]]['layout_and_data']['mean_min_max'], 'reference data unchanged')
    require(before == {name: sha(SOURCE/name) for name in INPUT_NAMES}, 'input hashes unchanged')
    with (output/'CAPTIONS.md').open('x') as stream:
        stream.write(captions(args.eta))
    report = dict(source_directory=str(SOURCE.relative_to(ROOT)), input_sha256=before,
                  script_path=str(Path(__file__).resolve().relative_to(ROOT)), script_sha256=sha(Path(__file__)),
                  renderer='Cairo CPU', cairo_version=cairo.cairo_version_string(),
                  numpy_version=np.__version__, matplotlib_used=False, seaborn_used=False,
                  font_path=str(font_path), font_sha256=sha(font_path), minimum_font_pt=MIN_FONT,
                  measured_run_count=24, input_repeat_count=24, individual_scatter_count=0,
                  measured_integrity='24/24 VALID', preserved_analyzer_verdict=verdict['primary_verdict'],
                  all_coordinates_from_source_data=True, no_fabricated_values=True,
                  structure_is_frozen_schedule_not_measured_execution=True,
                  assignment_counts_match_manifest=True, assignment_sums_equal_eight=True,
                  figure_B_mean_min_max_match_per_run=True, figure_C_paired_mean_min_max_match_CSV=True,
                  paired_Total_equals_Local_plus_Edge=True, stream_path_accounting_check='PASS',
                  max_edge_burst_concentrated=8, max_edge_burst_dispersed=1,
                  main_figure_has_threshold=False, optional_eta=args.eta,
                  inputs_unchanged=True, new_workload_executed=False, figure_validation=validation,
                  additional_output_sha256={'CAPTIONS.md':sha(output/'CAPTIONS.md')})
    with (output/'VALIDATION.json').open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(output_directory=str(output), figures=stems, input_repeat_count=24,
                          individual_scatter_count=0, validation='PASS', sources_unchanged=True), indent=2))


if __name__ == '__main__':
    main()
