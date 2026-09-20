#!/usr/bin/env python3
"""Reproduce the frozen Figure 1–3 designs from measured result CSVs only."""
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile

# Keep matplotlib's cache outside the repository and protected home directory.
os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='local-capacity-mpl-'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'paper/figures/local_capacity'
SOURCES = {
    'anchors': 'results/local_capacity_characterization/capacity_anchor_map.csv',
    'models': 'results/capacity_model_validity/model_predictions.csv',
    'boundaries': 'results/capacity_model_validity/empirical_boundaries.csv',
    'decisions': 'results/capacity_model_validity/frequency_decision_map.csv',
    'cases': 'results/capacity_model_validity/decision_cases.csv',
}
REQUIRED = {
    'anchors': ['frequency_MHz', 'highest_stable_r_per_stream',
                'highest_stable_aggregate_admission_FPS', 'lowest_unstable_r_per_stream',
                'boundary_status', 'frontend_status', 'stable_OC3_by_repeat', 'unstable_OC3_by_repeat'],
    'models': ['frequency_MHz', 'A_ISO', 'B_NAIVE_C2', 'T_iso_mean_ms',
               'confirmed_stable_offered_FPS', 'confirmed_unstable_offered_FPS', 'empirical_hardware_status'],
    'boundaries': ['frequency_MHz', 'confirmed_stable_offered_FPS', 'confirmed_unstable_offered_FPS',
                   'boundary_status', 'primary_included', 'empirical_hardware_status'],
    'decisions': ['model', 'demand_FPS', 'model_lowest_frequency_MHz',
                  'empirical_map_lowest_frequency_MHz', 'decision'],
    'cases': ['model', 'frequency_MHz', 'demand_FPS', 'primary_endpoint', 'predicted_capacity_FPS',
              'observation', 'decision', 'observed_repeats', 'empirical_hardware_status'],
}
DEMANDS = [96, 104, 120, 128, 144, 152, 160, 168, 176, 184, 192, 200]
STEMS = ['fig1_empirical_sustainable_capacity', 'fig2_isolated_model_gap',
         'fig3_frequency_selection_decisions']

plt.rcParams.update({
    'font.family': 'DejaVu Serif',
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'legend.fontsize': 9.5,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'pdf.fonttype': 42,
    'ps.fonttype': 42,
})


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError('Canonical sanity check FAIL: ' + message)


def load_validate():
    frames, hashes = {}, {}
    for key, relative in SOURCES.items():
        path = ROOT / relative
        hashes[relative] = digest(path)
        data = pd.read_csv(path)
        print('SCHEMA', relative, json.dumps(list(data.columns)), 'ROWS', len(data))
        missing = set(REQUIRED[key]) - set(data.columns)
        require(not missing, f'{relative}: missing columns {sorted(missing)}')
        frames[key] = data

    # These constants are exclusively assertions supplied by the user.
    # Every plotted coordinate below comes from the validated dataframes.
    expected = {
        315: (48, 56, 'FRONTEND_CONTAMINATED'),
        477: (72, 80, 'FRONTEND_CONTAMINATED'),
        630: (96, 104, 'CONFIRMED'), 792: (120, 128, 'CONFIRMED'),
        945: (144, 152, 'CONFIRMED'), 1107: (160, 168, 'CONFIRMED'),
        1260: (176, 184, 'CONFIRMED'), 1413: (184, 192, 'CONFIRMED'),
        1575: (200, 208, 'CONFIRMED'),
    }
    expected_models = {
        630: (90.20, 180.39), 792: (117.47, 234.93), 945: (130.01, 260.02),
        1107: (153.94, 307.88), 1260: (178.00, 356.00),
        1413: (192.57, 385.14), 1575: (214.31, 428.62),
    }
    anchors = frames['anchors'].sort_values('frequency_MHz').set_index('frequency_MHz', verify_integrity=True)
    boundaries = frames['boundaries'].sort_values('frequency_MHz').set_index('frequency_MHz', verify_integrity=True)
    models = frames['models'].sort_values('frequency_MHz').set_index('frequency_MHz', verify_integrity=True)
    require(list(anchors.index) == list(expected), 'anchor set/order')
    require(list(boundaries.index) == list(expected), 'empirical boundary set')
    require(list(models.index) == list(expected_models), 'model frequency set')
    for frequency, (stable, unstable, status) in expected.items():
        a, b = anchors.loc[frequency], boundaries.loc[frequency]
        require(a.highest_stable_aggregate_admission_FPS == b.confirmed_stable_offered_FPS == stable,
                f'{frequency}: stable endpoint')
        require(8 * a.lowest_unstable_r_per_stream == b.confirmed_unstable_offered_FPS == unstable,
                f'{frequency}: unstable endpoint')
        require(8 * a.highest_stable_r_per_stream == stable, f'{frequency}: K8 load accounting')
        require(a.boundary_status == b.boundary_status == status, f'{frequency}: boundary status')
        require(bool(b.primary_included) == (status == 'CONFIRMED'), f'{frequency}: primary scope')
        require(a.frontend_status == ('NORMAL' if status == 'CONFIRMED' else 'FRONTEND_LIMITED'),
                f'{frequency}: frontend annotation')
        expected_hardware = 'PROTECTION_LIMITED' if frequency == 1575 else 'CLEAN'
        require(b.empirical_hardware_status == expected_hardware, f'{frequency}: hardware annotation')
        oc = json.loads(a.stable_OC3_by_repeat) + json.loads(a.unstable_OC3_by_repeat)
        require(len(oc) == 6 and all(x > 0 if frequency == 1575 else x == 0 for x in oc),
                f'{frequency}: OC3 repeat evidence')
    for frequency, (a_expected, b_expected) in expected_models.items():
        m = models.loc[frequency]
        require(f'{m.A_ISO:.2f}' == f'{a_expected:.2f}' and f'{m.B_NAIVE_C2:.2f}' == f'{b_expected:.2f}',
                f'{frequency}: supplied rounded A/B predictions')
        require(np.isclose(m.A_ISO, 1000 / m.T_iso_mean_ms, rtol=1e-12, atol=0), f'{frequency}: Model A definition')
        require(np.isclose(m.B_NAIVE_C2, 2 * m.A_ISO, rtol=1e-12, atol=0), f'{frequency}: Model B definition')
        require(m.confirmed_stable_offered_FPS == boundaries.loc[frequency].confirmed_stable_offered_FPS and
                m.confirmed_unstable_offered_FPS == boundaries.loc[frequency].confirmed_unstable_offered_FPS,
                f'{frequency}: model/empirical cross-file endpoints')
        require(m.empirical_hardware_status == boundaries.loc[frequency].empirical_hardware_status,
                f'{frequency}: model hardware scope')

    decisions = frames['decisions'].query("model == 'A_ISO'")
    decisions = decisions[decisions.demand_FPS.isin(DEMANDS)].sort_values('demand_FPS')
    require(decisions.demand_FPS.tolist() == DEMANDS, 'Figure 3 demand set and uniqueness')
    clean = boundaries[boundaries.primary_included]
    for row in decisions.itertuples():
        feasible_empirical = clean[clean.confirmed_stable_offered_FPS >= row.demand_FPS]
        feasible_model = models[models.A_ISO >= row.demand_FPS]
        require(not feasible_empirical.empty and not feasible_model.empty, 'selected demand has no supported candidate')
        require(row.empirical_map_lowest_frequency_MHz == feasible_empirical.index.min() and
                row.model_lowest_frequency_MHz == feasible_model.index.min(),
                f'{row.demand_FPS}: stored frequency decision does not match maps')
        require(row.decision == ('MATCH' if row.model_lowest_frequency_MHz == row.empirical_map_lowest_frequency_MHz
                                else 'FREQUENCY_DECISION_MISMATCH'), f'{row.demand_FPS}: mismatch label')
    case = frames['cases'].query("model == 'A_ISO' and frequency_MHz == 1413 and demand_FPS == 192 and primary_endpoint == True")
    require(len(case) == 1 and case.iloc[0].decision == 'FALSE_FEASIBLE' and
            case.iloc[0].observation == 'OBSERVED_UNSTABLE' and case.iloc[0].observed_repeats == 3,
            'Figure 2 false-feasible annotation evidence')
    require(np.isclose(case.iloc[0].predicted_capacity_FPS, models.loc[1413].A_ISO), 'false-feasible prediction cross-check')
    choice = decisions.set_index('demand_FPS').loc[192]
    require(choice.model_lowest_frequency_MHz == 1413 and choice.empirical_map_lowest_frequency_MHz == 1575,
            'Figure 3 frozen 192-FPS annotation')
    # No output is created until all five CSVs pass the preceding validations.
    return frames, hashes


def save(fig, stem):
    fig.tight_layout()
    paths = []
    for extension in ['png', 'pdf', 'svg']:
        path = OUTPUT / f'{stem}.{extension}'
        with path.open('xb') as output:
            fig.savefig(output, format=extension, bbox_inches='tight',
                        **({'dpi': 600} if extension == 'png' else {}))
        paths.append(path)
    plt.close(fig)
    return paths


def main():
    frames, before = load_validate()
    expected_outputs = [f'{stem}.{ext}' for stem in STEMS for ext in ['png', 'pdf', 'svg']]
    expected_outputs += ['fig1_data.csv', 'fig2_data.csv', 'fig3_data.csv', 'README.md']
    collisions = [str(OUTPUT / name) for name in expected_outputs
                  if (OUTPUT / name).exists() or (OUTPUT / name).is_symlink()]
    if collisions:
        raise FileExistsError('Refusing to overwrite existing outputs: ' + ', '.join(collisions))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = []
    # Snapshot original columns; no rounded plotting values or synthetic bounds.
    d1 = frames['anchors'][['frequency_MHz', 'highest_stable_aggregate_admission_FPS', 'boundary_status']].merge(
        frames['boundaries'][['frequency_MHz', 'confirmed_unstable_offered_FPS', 'empirical_hardware_status']],
        on='frequency_MHz', validate='one_to_one').sort_values('frequency_MHz')
    d1.to_csv(OUTPUT / 'fig1_data.csv', index=False, mode='x')
    clean = d1[d1.boundary_status == 'CONFIRMED']
    contaminated = d1[d1.boundary_status == 'FRONTEND_CONTAMINATED']
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.vlines(clean.frequency_MHz, clean.highest_stable_aggregate_admission_FPS,
              clean.confirmed_unstable_offered_FPS, linewidth=1.5, alpha=0.7)
    ax.plot(clean.frequency_MHz, clean.highest_stable_aggregate_admission_FPS, marker='o', linewidth=2.0,
            label='Highest confirmed stable load')
    ax.plot(clean.frequency_MHz, clean.confirmed_unstable_offered_FPS, marker='^', linewidth=1.8,
            linestyle='--', label='Lowest confirmed unstable load')
    ax.scatter(contaminated.frequency_MHz, contaminated.highest_stable_aggregate_admission_FPS,
               marker='x', s=60, label='Frontend-contaminated stable endpoint')
    ax.scatter(contaminated.frequency_MHz, contaminated.confirmed_unstable_offered_FPS,
               marker='+', s=70, label='Frontend-contaminated unstable endpoint')
    protected = clean[clean.empirical_hardware_status == 'PROTECTION_LIMITED'].iloc[0]
    ax.annotate('protection-limited', xy=(protected.frequency_MHz, protected.highest_stable_aggregate_admission_FPS),
                xytext=(1430, 170), arrowprops={'arrowstyle': '->', 'linewidth': 1.0}, fontsize=9)
    ax.set(title='Empirical Sustainable-Capacity Boundaries', xlabel='GPU frequency (MHz)',
           ylabel='Total inference load (frames/s)', xticks=d1.frequency_MHz, ylim=(35, 220))
    ax.grid(axis='y', alpha=0.25)
    ax.legend(frameon=False, loc='upper left')
    files.extend(save(fig, STEMS[0]))

    d2 = frames['models'][['frequency_MHz', 'confirmed_stable_offered_FPS', 'confirmed_unstable_offered_FPS',
                           'A_ISO', 'empirical_hardware_status']].sort_values('frequency_MHz')
    d2.to_csv(OUTPUT / 'fig2_data.csv', index=False, mode='x')
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.plot(d2.frequency_MHz, d2.confirmed_stable_offered_FPS, marker='o', linewidth=1.8,
            label='Confirmed stable endpoint')
    ax.plot(d2.frequency_MHz, d2.confirmed_unstable_offered_FPS, marker='^', linewidth=1.6,
            linestyle='--', label='Confirmed unstable endpoint')
    ax.plot(d2.frequency_MHz, d2.A_ISO, marker='s', linewidth=2.0,
            label='Isolated-service estimate 1/T_iso')
    # One NaN-separated line draws vertical segments only, never a filled band or interpolation.
    segment_x = np.column_stack([d2.frequency_MHz, d2.frequency_MHz, np.full(len(d2), np.nan)]).ravel()
    segment_y = np.column_stack([d2.confirmed_stable_offered_FPS, d2.confirmed_unstable_offered_FPS,
                                 np.full(len(d2), np.nan)]).ravel()
    ax.plot(segment_x, segment_y, linewidth=6, alpha=0.18, solid_capstyle='round')
    example = d2.set_index('frequency_MHz').loc[1413]
    ax.annotate('False-feasible example\n192 FPS predicted feasible', xy=(example.name, round(example.A_ISO, 2)),
                xytext=(1150, 212), arrowprops={'arrowstyle': '->', 'linewidth': 1.0}, fontsize=9)
    protected = d2[d2.empirical_hardware_status == 'PROTECTION_LIMITED'].iloc[0]
    midpoint = (protected.confirmed_stable_offered_FPS + protected.confirmed_unstable_offered_FPS) / 2
    ax.annotate('protection-limited empirical runs', xy=(protected.frequency_MHz, midpoint),
                xytext=(1320, 228), arrowprops={'arrowstyle': '->', 'linewidth': 1.0}, fontsize=9)
    ax.set(title='Isolated-Service Estimate Relative to Empirical Capacity', xlabel='GPU frequency (MHz)',
           ylabel='Inference rate (frames/s)', xticks=d2.frequency_MHz, ylim=(80, 240))
    ax.grid(axis='y', alpha=0.25)
    ax.legend(frameon=False, loc='upper left')
    files.extend(save(fig, STEMS[1]))

    d3 = frames['decisions'].query("model == 'A_ISO'")
    d3 = d3[d3.demand_FPS.isin(DEMANDS)][REQUIRED['decisions']].sort_values('demand_FPS')
    d3.to_csv(OUTPUT / 'fig3_data.csv', index=False, mode='x')
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.plot(d3.demand_FPS, d3.empirical_map_lowest_frequency_MHz, marker='o', linewidth=2.0,
            label='Empirical sustainable-capacity map')
    ax.plot(d3.demand_FPS, d3.model_lowest_frequency_MHz, marker='s', linewidth=1.8, linestyle='--',
            label='Isolated-service model 1/T_iso')
    mismatch = d3[d3.decision == 'FREQUENCY_DECISION_MISMATCH']
    ax.scatter(mismatch.demand_FPS, mismatch.model_lowest_frequency_MHz, marker='x', s=70, zorder=3,
               label='Frequency-selection mismatch')
    example = d3.set_index('demand_FPS').loc[192]
    ax.annotate(f'{example.name} FPS:\nmodel → {example.model_lowest_frequency_MHz:g} MHz\n'
                f'empirical → {example.empirical_map_lowest_frequency_MHz:g} MHz',
                xy=(example.name, example.model_lowest_frequency_MHz), xytext=(160, 1300),
                arrowprops={'arrowstyle': '->', 'linewidth': 1.0}, fontsize=9)
    ax.set(title='Frequency Selection under Model-Based and Empirical Capacity',
           xlabel='Required inference rate (frames/s)', ylabel='Selected GPU frequency (MHz)',
           xticks=d3.demand_FPS, yticks=d2.frequency_MHz, ylim=(580, 1625))
    ax.grid(alpha=0.22)
    ax.legend(frameon=False, loc='upper left')
    files.extend(save(fig, STEMS[2]))

    after = {relative: digest(ROOT / relative) for relative in before}
    require(before == after, 'source CSV changed while plotting')
    generated = [p.name for p in files] + ['fig1_data.csv', 'fig2_data.csv', 'fig3_data.csv', 'README.md']
    readme = [
        '# Local capacity Figures 1–3', '',
        'Reproduce from repository root:', '', '```sh',
        'python3 -B scripts/figures/plot_local_capacity_figures.py', '```', '',
        'The script refuses to overwrite existing figure outputs. Reproduction requires a fresh output location at the same repository-relative path in a separate copy of the repository.', '',
        f'Generation repository: `{ROOT}`. No GPU workload, result modification, smoothing, fitting or confidence intervals.',
        f'Python {platform.python_version()}; libraries: matplotlib {matplotlib.__version__}, pandas {pd.__version__}, numpy {np.__version__}.', '',
        '## Semantics', '',
        '- Source frame rate: frame rate generated by the camera/video source.',
        '- Per-stream admission rate: frames/s selected for DNN inference in one stream.',
        '- Total inference load: frames/s selected for inference across all streams.',
        '- Completion rate: frames/s whose inference actually completed.',
        '- Sustainable capacity: maximum total inference load supportable without sustained backlog growth.',
        '- Figure 1 retains confirmed stable and next confirmed unstable endpoints; the stable endpoint is not exact μ_L(f). '
        '315/477 MHz are disconnected frontend-contaminated points. 1575 MHz is protection-limited.',
        '- Figure 2 shows only the isolated-service capacity estimate 1/T_iso, not all conventional models. '
        'The 1413/192 annotation is based on the mean estimate; its decision differs across baseline repeats (2/3 false-feasible). '
        'Empirical 1575 MHz runs are protection-limited. The annotation at the interval midpoint 204 is a label anchor, not a measured capacity.',
        '- Figure 3 uses the lowest eligible clean anchor under each stored map. The empirical map is a confirmed stable-load '
        'support envelope, not proof that each equal-demand pair was directly measured. No energy superiority is implied. '
        'Straight connecting lines follow the prescribed design and do not estimate unmeasured capacity or frequency states.',
        '- Every endpoint is based on three empirical repeats; no five-repeat or confidence-interval claim is made.', '',
        '## Source columns and snapshots', '',
        'Snapshots are the actual plotting dataframes and serve figure provenance only; they do not replace original raw measurements or results.', '',
        '- fig1_data.csv: original anchor columns plus original unstable endpoint/hardware columns joined from empirical_boundaries.csv. '
        'No completion-rate value is substituted for total inference load.',
        '- fig2_data.csv: original frequency, stable/unstable endpoint, A_ISO and hardware columns from model_predictions.csv.',
        '- fig3_data.csv: original Model A decision rows from frequency_decision_map.csv for the twelve requested demands. '
        'Each selection is independently cross-checked against the two maps. decision_cases.csv verifies the false-feasible annotation.', '',
        '## Original result SHA-256', '',
        *[f'- `{relative}`: `{h}`' for relative, h in before.items()], '',
        'Canonical sanity check: PASS. Source CSV hashes unchanged after plotting.', '',
        '## Generated files', '', *[f'- `{name}`' for name in generated], '',
        'Observation counts: Figure 1 =9 frequencies (18 endpoints;7 clean and2 contaminated); '
        'Figure 2 =7 frequencies (14 empirical endpoints +7 model estimates); '
        f'Figure 3 =12 demands (24 selected-frequency points;{len(mismatch)} mismatches).',
    ]
    with (OUTPUT / 'README.md').open('x') as output:
        output.write('\n'.join(readme) + '\n')
    print('INPUT_PATHS_AND_SHA256', json.dumps({str(ROOT / k): v for k, v in before.items()}, indent=2))
    print('FIGURE_OUTPUT_PATHS', json.dumps([str(p) for p in files], indent=2))
    print('PLOTTED_OBSERVATIONS', json.dumps({'fig1_frequencies': len(d1), 'fig1_endpoints': 2 * len(d1),
          'fig2_frequencies': len(d2), 'fig2_endpoint_and_model_points': 3 * len(d2),
          'fig3_demands': len(d3), 'fig3_frequency_points': 2 * len(d3), 'fig3_mismatch_markers': len(mismatch)}))
    print('canonical sanity check PASS')
    print('git status --short')
    print(subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True), end='')


if __name__ == '__main__':
    main()
