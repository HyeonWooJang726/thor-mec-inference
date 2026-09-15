"""Render two panels from immutable measured CSV and structural manifest only."""
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.container import BarContainer, ErrorbarContainer
from matplotlib.ticker import MaxNLocator
import numpy as np

base = Path('/workspace/split_inference/results/thor_processing_profile/20260915T181507')
manifest_path = Path('/workspace/split_inference/manifests/efficientnet_v2_s_p0_p9.json')
output = Path('/output')
rows = list(csv.DictReader((base / 'group_summary.csv').open()))
manifest = json.loads(manifest_path.read_text())
assert [r['group'] for r in rows] == [f'G{i}' for i in range(1, 10)]
assert manifest['points'][0]['expected_shape'] == [1, 3, 384, 384]
assert all(p['dtype'] == 'torch.float32' for p in manifest['points'])
input_bytes = math.prod(manifest['points'][0]['expected_shape']) * 4
values = []
for i, row in enumerate(rows, 1):
    shape = json.loads(row['output_shape'])
    assert shape == manifest['points'][i]['expected_shape']
    output_bytes = math.prod(shape) * 4
    assert output_bytes == int(row['output_bytes'])
    assert input_bytes == math.prod(manifest['points'][i-1]['expected_shape']) * 4
    mean_ms = float(row['mean_ms'])
    assert math.isfinite(mean_ms) and mean_ms >= 0
    input_bits, output_bits = input_bytes * 8, output_bytes * 8
    density = mean_ms / (input_bits / 1_000_000)
    sigma = output_bits / input_bits
    assert math.isclose(density * (input_bits / 1_000_000), mean_ms, rel_tol=1e-14)
    assert math.isclose(sigma * input_bits, output_bits, rel_tol=1e-14)
    values.append(dict(group=row['group'], mean_ms=mean_ms, input_bytes=input_bytes,
                       output_bytes=output_bytes, input_bits=input_bits,
                       output_bits=output_bits, output_mib=output_bytes / 2**20,
                       processing_time_density_ms_per_mbit=density,
                       bit_conversion_ratio=sigma))
    input_bytes = output_bytes

blue, orange = '#0072B2', '#E69F00'
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11,
                     'axes.labelsize':13, 'xtick.labelsize':11,
                     'ytick.labelsize':11, 'legend.fontsize':10,
                     'axes.linewidth':0.7, 'pdf.fonttype':42,
                     'svg.fonttype':'none', 'figure.facecolor':'white',
                     'axes.facecolor':'white', 'savefig.facecolor':'white'})
fig, primary = plt.subplots(1, 2, figsize=(10.8, 4.5))
fig.subplots_adjust(left=0.085, right=0.915, bottom=0.25, top=0.95, wspace=0.48)
x = np.arange(9)
width = 0.36
texts = []
barsets = []
legends = []
secondary = []
specs = [
    ('mean_ms', 'output_mib', 'Mean processing time (ms)', 'Output data size (MiB)',
     'Mean processing time', 'Output data size', '(a)'),
    ('processing_time_density_ms_per_mbit', 'bit_conversion_ratio',
     'Processing-time density (ms/Mbit)', 'Bit conversion ratio (bits/bit)',
     'Processing-time density', 'Bit conversion ratio', '(b)'),
]
for left, spec in zip(primary, specs):
    lk, rk, ll, rl, legend_left, legend_right, panel = spec
    right = left.twinx()
    secondary.append(right)
    lv, rv = [v[lk] for v in values], [v[rk] for v in values]
    lb = left.bar(x - width/2, lv, width, color=blue, edgecolor='black', linewidth=0.5)
    rb = right.bar(x + width/2, rv, width, color=orange, edgecolor='black', linewidth=0.5)
    assert [p.get_height() for p in lb] == lv
    assert [p.get_height() for p in rb] == rv
    barsets.extend([lb, rb])
    left.set_xlim(-0.65, 8.65)
    left.set_xticks(x, [f'G{i}' for i in range(1, 10)])
    left.set_xlabel('Layer group index', labelpad=9)
    left.set_ylabel(ll, color=blue, labelpad=9)
    right.set_ylabel(rl, color=orange, labelpad=9)
    left.tick_params(axis='y', colors=blue, width=0.7)
    right.tick_params(axis='y', colors=orange, width=0.7)
    left.tick_params(axis='x', width=0.7)
    left.set_ylim(0, max(lv)*1.38)
    right.set_ylim(0, max(rv)*1.38)
    left.yaxis.set_major_locator(MaxNLocator(nbins=5))
    right.yaxis.set_major_locator(MaxNLocator(nbins=5))
    left.grid(axis='y', color='#dedede', linewidth=0.5, alpha=0.65)
    left.set_axisbelow(True)
    legend = right.legend([lb, rb], [legend_left, legend_right], loc='upper right',
                          frameon=False, borderaxespad=0.55, handlelength=1.4)
    legends.append(legend)
    panel_text = left.text(0.5, -0.205, panel, ha='center', va='top', fontsize=13,
                           transform=left.transAxes)
    texts.extend([left.xaxis.label,left.yaxis.label,right.yaxis.label,panel_text])
    texts.extend(legend.get_texts())
    assert not left.lines and not right.lines
    assert not left.collections and not right.collections
    for ax in (left, right):
        assert not any(isinstance(c, ErrorbarContainer) for c in ax.containers)
        assert all(isinstance(c, BarContainer) and c.errorbar is None for c in ax.containers)
    assert not left.get_title() and not right.get_title()

fig.canvas.draw()
renderer = fig.canvas.get_renderer()
for left, right in zip(primary, secondary):
    texts.extend(t for t in left.get_xticklabels() if t.get_visible())
    texts.extend(t for t in left.get_yticklabels() if t.get_visible() and left.get_ylim()[0] <= t.get_position()[1] <= left.get_ylim()[1])
    texts.extend(t for t in right.get_yticklabels() if t.get_visible() and right.get_ylim()[0] <= t.get_position()[1] <= right.get_ylim()[1])
for text in texts:
    label = text.get_text().lower()
    assert not any(token in label for token in ('thor','jetson','nvidia','2026','p95','p99','median','sample','prefix','suffix'))
    if 'mean' in label:
        assert label in ('mean processing time', 'mean processing time (ms)')
    bb = text.get_window_extent(renderer)
    assert fig.bbox.contains(bb.x0,bb.y0) and fig.bbox.contains(bb.x1,bb.y1), ('clipped',text.get_text())
for i, a in enumerate(texts):
    for b in texts[i+1:]:
        assert not a.get_window_extent(renderer).overlaps(b.get_window_extent(renderer)), ('text overlap',a.get_text(),b.get_text())
for legend in legends:
    for container in barsets:
        for patch in container:
            assert not legend.get_window_extent(renderer).overlaps(patch.get_window_extent(renderer)), 'legend overlaps bar'
assert math.isclose(primary[0].get_position().width,primary[1].get_position().width)
assert math.isclose(primary[0].get_position().height,primary[1].get_position().height)
name = 'efficientnetv2s_layer_group_characteristics'
fig.savefig(output/f'{name}.png',dpi=600)
fig.savefig(output/f'{name}.pdf',metadata={'CreationDate':None,'ModDate':None,'Creator':None})
fig.savefig(output/f'{name}.svg',metadata={'Date':None,'Creator':None})
svg = (output/f'{name}.svg').read_text()
assert all(token not in svg.lower() for token in ('thor','jetson','nvidia','p95','p99','median','prefix','suffix'))
plt.close(fig)
with (output/'derived_values.csv').open('w',newline='') as f:
    writer = csv.DictWriter(f,fieldnames=list(values[0]))
    writer.writeheader()
    writer.writerows(values)
validation = {
    'status':'passed','density_definition':'mean_ms / (input_bytes * 8 / 1e6)',
    'density_unit':'ms/Mbit','frequency_status':'unverified; no reliable measured clock in metadata/preflight/postflight; MAXN alone insufficient',
    'output_size_unit':'MiB = bytes / 2**20',
    'sigma_definition':'output_bits / input_bits',
    'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (base/'group_summary.csv',manifest_path)},
    'same_plot_area':True,'text_clipping_or_overlap':False,'errorbars':False,
    'figure_size_inches':[10.8,4.5],'png_dpi':600,
}
(output/'figure_validation.json').write_text(json.dumps(validation,indent=2)+'\n')
for row in values: print(json.dumps(row),flush=True)
print('CHARACTERISTICS_FIGURE_PASS',flush=True)
