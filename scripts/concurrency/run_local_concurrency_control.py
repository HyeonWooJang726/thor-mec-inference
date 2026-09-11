#!/usr/bin/env python3
"""Run two bounded smokes, or print the future 15-run formal plan (never execute it)."""

# Resolve shared experiment modules for direct script and repository-root imports.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "common"))
from script_paths import configure as _configure, script_path
_configure()

import argparse
import csv
import json
from pathlib import Path
import shlex
import subprocess
import sys
from fractions import Fraction

from local_latency_breakdown_metrics import validate_timing, queue_metrics, frame_rows_ns, PER_FRAME_FIELDS
from local_concurrency_validation import validate_concurrency
from run_local_concurrency_trtexec_probe import REPO, environment, save

ROOT = REPO/'results/local_inference_concurrency'


def command(k, frames, run_id, output, formal=False):
    return ['/usr/bin/python3', '-B', 'scripts/concurrency/profile_local_concurrency_control.py',
            '--formal' if formal else '--smoke', '--k', str(k), '--frames-per-stream', str(frames),
            '--run-id', run_id, '--output-dir', str(output.relative_to(REPO))]


def formal_plan():
    # Preserve the relative K5/6/7 order from each frozen C1 repetition.
    order = [[5, 6, 7]]*5
    return {'status': 'PREPARED ONLY / NOT EXECUTED', 'C': 2, 'B': 1, 'fps': 30,
            'frames_per_stream': 1800, 'duration_seconds': 60, 'run_count': 15,
            'total_frames': 162000, 'deliberate_cooldown': 'NONE',
            'warmup': 'none; same as frozen C1 formal',
            'order_reason': 'relative order of selected K values in existing C1 formal rotation',
            'runs': [{'rep': rep, 'K': k, 'run_id': f'run{rep:02d}',
                      'argv': command(k, 1800, f'run{rep:02d}', ROOT/'formal'/f'k{k}'/f'run{rep:02d}', True)}
                     for rep, ks in enumerate(order, 1) for k in ks]}


def verify(output, k, frames=100):
    prefix = 'smoke_' if frames == 100 else ''
    raw = json.loads((output/f'{prefix}raw_ns.json').read_text())
    v = json.loads((output/f'{prefix}validation.json').read_text())
    resources = json.loads((output/'resources.json').read_text())
    records, events = raw['records'], raw['queue_events']
    expected = k*frames
    if v['validation'] != 'PASS' or len(records) != expected or set(v['counts'].values()) != {expected}:
        raise ValueError('child validation/count failure')
    if any(validate_timing(records).values()):
        raise ValueError('timing/decomposition failure')
    for stream in range(k):
        if sorted(r['frame_id'] for r in records if r['stream_id'] == stream) != list(range(frames)):
            raise ValueError('missing/duplicate frame IDs')
    if any(r['a_ns'] != raw['t0_ns']+(r['frame_id']*1_000_000_000)//30 for r in records):
        raise ValueError('arrival phase mismatch')
    q = queue_metrics(events, records, expected, expected)
    concurrency = validate_concurrency(records, resources)
    with (output/'per_frame.csv').open() as f:
        saved = list(csv.DictReader(f))
    expected_rows = frame_rows_ns(records, raw['t0_ns'])
    if len(saved) != expected:
        raise ValueError('CSV frame count mismatch')
    raw_by_id = {(r['stream_id'], r['frame_id']): r for r in records}
    for row, actual in zip(expected_rows, saved):
        for field in PER_FRAME_FIELDS:
            value = float(Fraction(row[field[:-3]+'_ns'], 1_000_000)) if field.endswith('_ms') else row[field]
            parsed = float(actual[field]) if field.endswith('_ms') else int(actual[field])
            if parsed != value:
                raise ValueError(f'CSV/raw mismatch: {field}')
        r = raw_by_id[(row['stream_id'], row['frame_id'])]
        for field in ('worker_id', 'service_start_ns', 'service_completion_ns', 'submission_return_ns', 'stream_sync_return_ns'):
            if int(actual[field]) != r[field]:
                raise ValueError(f'CSV concurrency/raw mismatch: {field}')
    return {'K': k, 'expected': expected, 'counts': v['counts'], 'validation': 'PASS',
            'integer_ns_timing': validate_timing(records), 'queue': {key: float(val) if isinstance(val, Fraction) else val for key, val in q.items()},
            'negative_waiting_depth_events': sum(e['depth'] < 0 for e in events),
            'exact_frame_ids': True, 'phase_aligned_arrivals': True, 'CSV_matches_raw': True,
            'concurrency': concurrency, 'resources': resources}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if args.dry_run:
        print(json.dumps(formal_plan(), indent=2))
        return
    smoke = ROOT/'smoke'
    smoke.mkdir(exist_ok=False)
    results = []
    for k in (2, 6):
        output = smoke/f'k{k}'
        argv = command(k, 100, 'smoke01', output)
        save(smoke/f'k{k}_command.json', {'argv': argv, 'cwd': str(REPO), 'exact_command': shlex.join(argv)})
        save(smoke/f'k{k}_environment_before.json', environment())
        print(f'START K{k} x 100 frames/stream, C=2 smoke', flush=True)
        with (smoke/f'k{k}_stdout.log').open('x') as out, (smoke/f'k{k}_stderr.log').open('x') as err:
            child = subprocess.run(argv, cwd=REPO, stdout=out, stderr=err)
        save(smoke/f'k{k}_exit.json', {'exit_code': child.returncode})
        save(smoke/f'k{k}_environment_after.json', environment())
        try:
            if child.returncode:
                raise ValueError(f'child exit {child.returncode}')
            results.append(verify(output, k))
        except Exception as error:
            save(smoke/'validation_report.json', {'validation': 'FAIL', 'completed_checks': results, 'failed_K': k, 'error': str(error)})
            raise
        print(f'PASS K{k}: {results[-1]["concurrency"]}', flush=True)
    save(smoke/'validation_report.json', {'validation': 'PASS', 'runs': results,
         'GPU_kernel_overlap_directly_measured': False, 'evidence_scope': 'concurrent inference submission only',
         'formal_control_executed': False})


if __name__ == '__main__':
    main()
