#!/usr/bin/env python3
"""Replay frozen canonical analysis and figures into a new directory, CPU only.

Source snapshots and input artifacts remain read-only. The only adaptations are
import search paths and output placement; the plotting/analysis code is copied
byte-for-byte from the checkpoint, never edited by this adapter.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from script_paths import REPO, SCRIPTS, ROLES, configure
configure()

SOURCE = REPO / 'results/local_canonical_c2'
SUMMARY_FILES = (
    'per_run_summary.csv', 'motivation_summary.csv', 'run_level_variability.csv',
    'inference_queue_summary.csv', 'latency_decomposition.csv',
    'deadline_knee_analysis.csv', 'analysis/analysis_data.json',
    'analysis/analysis_validation.json',
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New scratch directory outside the repository results tree.')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.is_relative_to(REPO / 'results'):
        parser.error('Use a scratch directory outside protected results.')
    output.mkdir(parents=True, exist_ok=False)
    target = output / 'results/local_canonical_c2'
    analysis = target / 'analysis'
    analysis.mkdir(parents=True)
    # Only raw run directories are linked; all generated output paths are private.
    for k in range(1, 8):
        (target / f'k{k}').symlink_to(SOURCE / f'k{k}', target_is_directory=True)
    shutil.copy2(SOURCE / 'formal_integrity_report.json', target)
    for path in (SOURCE / 'analysis').glob('*.py'):
        shutil.copy2(path, analysis / path.name)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = os.pathsep.join(
        [str(SOURCE / 'code'), *(str(SCRIPTS / role) for role in ROLES)])
    subprocess.run([sys.executable, '-B', str(analysis / 'analyze.py')],
                   cwd=REPO, env=env, check=True)
    summary_checks = {name: digest(target / name) == digest(SOURCE / name)
                      for name in SUMMARY_FILES}
    assert all(summary_checks.values()), summary_checks
    pins = json.loads((SOURCE / 'analysis/plot_inputs_sha256.json').read_text())
    for name in [*pins, 'analysis/plot_inputs_sha256.json',
                 'analysis/plot_axis_limits.json']:
        destination = target / name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / name, destination)
    subprocess.run([sys.executable, '-B', str(analysis / 'plot_figures.py'),
                    '--from-derived'], cwd=REPO, env=env, check=True)
    figures = sorted((analysis / 'figures').glob('*.png'))
    assert len(figures) == 4
    figure_checks = {p.name: digest(p) == digest(SOURCE / 'analysis/figures' / p.name)
                     for p in figures}
    assert all(figure_checks.values()), figure_checks
    report = {'validation': 'PASS', 'summary_byte_identity': summary_checks,
              'figure_byte_identity': figure_checks, 'runs': 35, 'frames': 252000,
              'GPU_workload_executed': False, 'historical_artifacts_rewritten': False}
    (output / 'reproduction_report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
