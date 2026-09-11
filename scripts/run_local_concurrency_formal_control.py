#!/usr/bin/env python3
"""Generalized-path C1/C2 smoke gate and exact 30-run formal control orchestration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone

from local_concurrency_control_metrics import validate_run
from run_local_concurrency_trtexec_probe import REPO, environment, save

BASE = REPO/'results/local_inference_concurrency'
PREP = BASE/'formal_control_preparation'
ROOT = BASE/'formal_control'
SMOKE_ORDER = [(1, 2), (2, 2), (1, 6), (2, 6)]
ORDER = [
    [(1,5),(2,5),(1,6),(2,6),(1,7),(2,7)],
    [(2,6),(1,6),(2,7),(1,7),(2,5),(1,5)],
    [(1,7),(2,7),(1,5),(2,5),(1,6),(2,6)],
    [(2,5),(1,5),(2,6),(1,6),(2,7),(1,7)],
    [(1,6),(2,6),(1,7),(2,7),(1,5),(2,5)],
]
SOURCES = ['profile_local_concurrency_control.py', 'local_concurrency_tensorrt.py',
           'local_concurrency_validation.py', 'local_concurrency_control_metrics.py',
           'profile_local_latency_breakdown.py', 'local_latency_breakdown_metrics.py',
           'profile_local_e2e.py', 'rtdetr_preprocess.py',
           'run_local_concurrency_trtexec_probe.py', 'run_local_concurrency_formal_control.py']


def hashes():
    return {name: hashlib.file_digest((REPO/'scripts'/name).open('rb'), 'sha256').hexdigest() for name in SOURCES}


def command(c, k, rep=0):
    formal = rep > 0
    output = (ROOT if formal else PREP/'smoke')/f'c{c}'/f'k{k}'
    run_id = f'run{rep:02d}' if formal else 'smoke01'
    if formal:
        output /= run_id
    argv = ['/usr/bin/python3', '-B', 'scripts/profile_local_concurrency_control.py',
            '--formal' if formal else '--smoke', '--concurrency', str(c), '--k', str(k),
            '--frames-per-stream', '1800' if formal else '100', '--run-id', run_id,
            '--output-dir', str(output.relative_to(REPO))]
    return argv, output, run_id


def plan():
    return {'primary_comparison': 'new control C1 vs new control C2; identical request code',
            'runs': [{'C': c, 'K': k, 'round': rep, 'argv': command(c,k,rep)[0]} for rep, group in enumerate(ORDER,1) for c,k in group],
            'run_count': 30, 'expected_frames': 324000, 'per_C_frames': 162000,
            'frames_per_stream': 1800, 'fps': 30, 'duration_seconds': 60, 'B': 1,
            'deliberate_cooldown': 'NONE', 'warmup': 'none, as in frozen application C1 formal; no frame excluded',
            'candidate_deadline': 'exact 1/30 second; e2e_ns*30>1000000000; not final application SLA',
            'power': 'MAXN', 'DVFS': 'unlocked', 'jetson_clocks': 'OFF', 'CUDA_Graph': 'OFF'}


def preflight():
    data = environment()
    if data['pid1'] not in ('systemd', 'init'):
        raise RuntimeError('host PID visibility required')
    ancestors = set()
    pid = os.getpid()
    while pid > 0 and pid not in ancestors:
        ancestors.add(pid)
        try:
            pid = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError, ValueError):
            break
    blockers = []
    for line in data['processes'].splitlines()[1:]:
        fields = line.split(None, 4)
        if len(fields) != 5 or int(fields[0]) in ancestors:
            continue
        comm, args = fields[2], fields[4]
        if comm in ('trtexec','gst-launch-1.0','ffmpeg') or ('python' in comm and 'scripts/profile_' in args):
            blockers.append(line)
    data['competing_experiments'] = blockers
    if blockers:
        raise RuntimeError(f'competing experiments present: {blockers}')
    return data


def one_run(c, k, rep, logroot):
    argv, output, run_id = command(c,k,rep)
    if output.exists():
        raise RuntimeError(f'existing output forbidden: {output}')
    label = f'c{c}_k{k}_{run_id}'
    before = preflight()
    details = {'argv': argv, 'cwd': str(REPO), 'exact_command': shlex.join(argv),
               'started_utc': datetime.now(timezone.utc).isoformat()}
    save(logroot/f'{label}_command.json', details)
    save(logroot/f'{label}_environment_before.json', before)
    started = time.monotonic_ns()
    print(f'START {label}', flush=True)
    with (logroot/f'{label}_stdout.log').open('x') as out, (logroot/f'{label}_stderr.log').open('x') as err:
        try:
            child = subprocess.run(argv, cwd=REPO, stdout=out, stderr=err, timeout=420)
            code, error = child.returncode, None
        except subprocess.TimeoutExpired:
            code, error = -1, 'child watchdog timeout; formal stopped, no retry'
    save(logroot/f'{label}_exit.json', {'exit_code': code, 'error': error,
         'elapsed_ns': time.monotonic_ns()-started, 'finished_utc': datetime.now(timezone.utc).isoformat()})
    save(logroot/f'{label}_environment_after.json', preflight())
    if output.is_dir():
        for suffix in ('stdout.log','stderr.log','command.json','exit.json','environment_before.json','environment_after.json'):
            target = output/suffix
            if target.exists():
                raise RuntimeError('unexpected artifact collision')
            shutil.copy2(logroot/f'{label}_{suffix}', target)
    if code:
        raise RuntimeError(f'{label}: exit {code}; raw failure preserved')
    summary, integrity = validate_run(output, c, k, 1800 if rep else 100, run_id)
    save(output/'independent_validation.json', integrity)
    print(f'PASS {label} frames={summary["frames"]} miss={summary["deadline_miss_pct"]:.4f}% local={summary["local_latency_mean_ms"]:.4f}ms queue={summary["queue_wait_mean_ms"]:.4f}ms active={summary["max_active_inferences"]}', flush=True)
    return summary, integrity


def smoke():
    dest = PREP/'smoke'
    dest.mkdir(exist_ok=False)
    logroot = dest/'orchestration'
    logroot.mkdir()
    pinned = hashes()
    save(dest/'source_sha256.json', pinned)
    summaries, checks = [], []
    try:
        for c,k in SMOKE_ORDER:
            if hashes() != pinned:
                raise RuntimeError('source changed during smoke')
            summary, check = one_run(c,k,0,logroot)
            summaries.append(summary); checks.append(check)
    except Exception as error:
        save(dest/'validation_report.json', {'validation': 'FAIL', 'error': str(error), 'runs': checks})
        raise
    save(dest/'validation_report.json', {'validation': 'PASS', 'runs': checks, 'summaries': summaries,
         'source_sha256': pinned, 'GPU_kernel_overlap_directly_measured': False})


def execute():
    smoke_report = json.loads((PREP/'smoke/validation_report.json').read_text())
    if smoke_report['validation'] != 'PASS' or hashes() != smoke_report['source_sha256']:
        raise RuntimeError('all four smoke PASS on identical source required')
    for c,k in SMOKE_ORDER:
        validate_run(command(c,k)[1], c,k,100,'smoke01')
    preflight_data = preflight()
    ROOT.mkdir(exist_ok=False)
    logroot = ROOT/'orchestration'; logroot.mkdir()
    save(ROOT/'formal_plan.json', plan())
    save(ROOT/'source_sha256.json', hashes())
    save(ROOT/'preflight.json', preflight_data)
    summaries, checks = [], []
    try:
        for rep, group in enumerate(ORDER, 1):
            for c,k in group:
                if hashes() != smoke_report['source_sha256']:
                    raise RuntimeError('source changed after smoke')
                summary, check = one_run(c,k,rep,logroot)
                summaries.append(summary); checks.append(check)
                save(logroot/f'completed_{len(checks):02d}.json', {'completed_valid_runs':len(checks), 'frames':sum(x['frames'] for x in checks), 'latest':summary})
    except Exception as error:
        save(ROOT/'formal_integrity_report.json', {'validation':'FAIL','error':str(error), 'completed_valid_runs':len(checks), 'runs':checks})
        raise
    total = sum(x['frames'] for x in checks)
    per_c = {str(c):sum(x['frames'] for x in checks if x['C']==c) for c in (1,2)}
    if len(checks)!=30 or total!=324000 or set(per_c.values())!={162000}:
        raise RuntimeError('formal matrix/frame mismatch')
    save(ROOT/'formal_integrity_report.json', {'validation':'PASS', 'expected_runs':30,'completed_valid_runs':len(checks),
         'expected_frames':324000,'actual_frames':total,'per_C_frames':per_c,'runs':checks,
         'GPU_kernel_overlap_directly_measured':False})
    print('FORMAL COMPLETE: 30 valid runs / 324000 frames', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    for option in ('smoke','execute','dry-run','preflight'):
        mode.add_argument('--'+option, action='store_true')
    args = p.parse_args()
    if args.dry_run:
        print(json.dumps(plan(), indent=2))
    elif args.preflight:
        print(json.dumps(preflight(), indent=2))
    elif args.smoke:
        smoke()
    else:
        execute()


if __name__ == '__main__':
    main()
