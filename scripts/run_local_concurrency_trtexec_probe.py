#!/usr/bin/env python3
"""Canonical-engine 15-run trtexec probe. Does not launch application benchmarks."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import statistics
import subprocess
import time
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'results/local_inference_concurrency/trtexec_probe'
ENGINE = 'models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine'
INPUT = 'results/correctness/Camera_0000_t60_input.bin'
ORDER = [[1, 2, 4], [2, 4, 1], [4, 1, 2], [1, 2, 4], [2, 4, 1]]


def save(path, data):
    with path.open('x') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def environment():
    def optional_read(path):
        try:
            return path.read_text().strip()
        except OSError as error:
            return f'unavailable: {error}'
    clocks = {}
    for root, patterns in [('/sys/devices/system/cpu/cpufreq', ['policy*/scaling_governor', 'policy*/scaling_min_freq', 'policy*/scaling_max_freq']),
                           ('/sys/class/devfreq', ['*/governor', '*/min_freq', '*/max_freq', '*/cur_freq'])]:
        for pattern in patterns:
            for p in Path(root).glob(pattern):
                clocks[str(p)] = p.read_text().strip()
    unlocked = all(int(clocks[str(Path(d)/lo)]) < int(clocks[str(Path(d)/hi)]) for d, lo, hi in [
        ('/sys/devices/system/cpu/cpufreq/policy0', 'scaling_min_freq', 'scaling_max_freq'),
        ('/sys/class/devfreq/gpu-gpc-0', 'min_freq', 'max_freq'),
        ('/sys/class/devfreq/bwmgr', 'min_freq', 'max_freq')])
    power = subprocess.check_output(['nvpmodel', '-q'], text=True)
    metadata = {'utc': datetime.now(timezone.utc).isoformat(), 'uname': list(os.uname()),
                'power_mode': power, 'clock_sysfs': clocks, 'DVFS_unlocked': unlocked,
                'jetson_clocks': 'OFF: CPU/GPU/EMC min < max; no clock modification',
                'pid1': Path('/proc/1/comm').read_text().strip(),
                'processes': subprocess.check_output(['ps', '-eo', 'pid,ppid,comm,pcpu,args'], text=True),
                'thermal': {str(p): optional_read(p) for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')},
                'relevant_environment': {k: v for k, v in os.environ.items() if k.startswith(('CUDA_', 'OMP_', 'OPENBLAS_', 'MKL_')) or k in ('LD_LIBRARY_PATH', 'PATH')},
                'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()}
    if 'NV Power Mode: MAXN' not in power or not unlocked:
        raise RuntimeError('MAXN / unlocked DVFS required')
    return metadata


def command(c, output):
    return ['/usr/bin/trtexec', f'--loadEngine={ENGINE}', '--shapes=inputs:1x3x640x640',
            f'--loadInputs=inputs:{INPUT}', '--warmUp=2000', '--duration=30', f'--infStreams={c}',
            f'--exportTimes={output.relative_to(REPO)}/timing.json']


def parse_metrics(log):
    if '&&&& PASSED TensorRT.trtexec' not in log:
        raise ValueError('trtexec did not report PASSED')
    tail = log.rsplit('=== Performance summary ===', 1)[1]
    row = {'throughput_qps': float(re.search(r'Throughput: ([\d.eE+-]+) qps', tail)[1])}
    for label, prefix in [('Latency', 'latency'), ('Enqueue Time', 'enqueue'), ('H2D Latency', 'h2d'),
                          ('GPU Compute Time', 'gpu_compute'), ('D2H Latency', 'd2h')]:
        match = re.search(r'\[I\] ' + label + r': ([^\n]+)', tail)
        if not match:
            continue
        for key, val in re.findall(r'(min|max|mean|median|percentile\(\d+%\)) = ([\d.eE+-]+) ms', match[1]):
            key = re.sub(r'percentile\((\d+)%\)', r'p\1', key)
            row[f'{prefix}_{key}_ms'] = float(val)
    for field in ['latency_mean_ms', 'latency_p95_ms', 'gpu_compute_mean_ms', 'gpu_compute_p95_ms']:
        if field not in row:
            raise ValueError(f'required reported metric absent: {field}')
    return row


def csv_write(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def summarize():
    rows = []
    for rep, order in enumerate(ORDER, 1):
        for pos, c in enumerate(order, 1):
            d = ROOT / f'rep{rep:02d}_infStreams{c}'
            status = json.loads((d/'exit.json').read_text())
            if status['exit_code'] != 0:
                raise ValueError(f'failed run: {d}')
            rows.append({'rep': rep, 'position': pos, 'infStreams': c, **parse_metrics((d/'stdout.log').read_text())})
    reference = {r['rep']: r['throughput_qps'] for r in rows if r['infStreams'] == 1}
    base = statistics.mean(reference.values())
    for r in rows:
        r['throughput_speedup_vs_infStreams1'] = r['throughput_qps']/reference[r['rep']]
        r['concurrency_efficiency_reference'] = r['throughput_speedup_vs_infStreams1']/r['infStreams']
    csv_write(ROOT/'run_summary.csv', rows)
    summaries = []
    for c in (1, 2, 4):
        group = [r for r in rows if r['infStreams'] == c]
        out = {'infStreams': c, 'run_count': len(group)}
        for metric in rows[0]:
            if metric in ('rep', 'position', 'infStreams'):
                continue
            vals = [r[metric] for r in group]
            for stat, value in [('mean', statistics.mean(vals)), ('sample_sd', statistics.stdev(vals)), ('min', min(vals)), ('max', max(vals))]:
                out[f'{metric}_{stat}'] = value
        out['throughput_ratio_of_configuration_means'] = out['throughput_qps_mean']/base
        out['concurrency_reference_ratio_of_means'] = out['throughput_qps_mean']/(c*base)
        summaries.append(out)
    csv_write(ROOT/'concurrency_summary.csv', summaries)
    print(json.dumps(summaries, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        for rep, order in enumerate(ORDER, 1):
            for c in order:
                print(shlex.join(command(c, ROOT/f'rep{rep:02d}_infStreams{c}')))
        return
    ROOT.mkdir(parents=True, exist_ok=False)
    help_result = subprocess.run(['/usr/bin/trtexec', '--help'], capture_output=True, text=True)
    (ROOT/'trtexec_help.stdout.log').write_text(help_result.stdout)
    (ROOT/'trtexec_help.stderr.log').write_text(help_result.stderr)
    save(ROOT/'trtexec_help.exit.json', {'exit_code': help_result.returncode})
    if help_result.returncode or '--infStreams=N' not in help_result.stdout:
        raise RuntimeError('--infStreams unavailable; no substitute used')
    save(ROOT/'protocol.json', {'engine': ENGINE, 'engine_sha256': digest(REPO/ENGINE), 'input': INPUT,
        'input_sha256': digest(REPO/INPUT), 'shape': 'inputs:1x3x640x640', 'warmup_ms': 2000,
        'measurement_seconds': 30, 'rotation': ORDER, 'deliberate_cooldown': 'NONE',
        'CUDA_graph': False, 'spin_wait': False, 'data_transfers': True,
        'extra_reporting_only_option': '--exportTimes (raw per-inference timing; warmup excluded by trtexec)',
        'historical_protocol_evidence': ['results/power_calibration/rtdetr_b1_maxn_run1.log', 'results/cross_inference_profiling/rtdetr_b1_c1_maxn_run1.log'],
        'historical_engine_differs': True})
    for rep, order in enumerate(ORDER, 1):
        for c in order:
            d = ROOT/f'rep{rep:02d}_infStreams{c}'
            d.mkdir()
            argv = command(c, d)
            save(d/'command.json', {'argv': argv, 'cwd': str(REPO), 'exact_shell_command': shlex.join(argv)})
            (d/'command.txt').write_text(shlex.join(argv)+'\n')
            save(d/'environment_before.json', environment())
            started = time.monotonic_ns()
            print(f'START rep{rep:02d} infStreams={c}', flush=True)
            with (d/'stdout.log').open('x') as out, (d/'stderr.log').open('x') as err:
                p = subprocess.run(argv, cwd=REPO, stdout=out, stderr=err)
            save(d/'exit.json', {'exit_code': p.returncode, 'elapsed_ns': time.monotonic_ns()-started})
            save(d/'environment_after.json', environment())
            if p.returncode:
                raise RuntimeError(f'run failed, no automatic retry: {d}')
            save(d/'metrics.json', parse_metrics((d/'stdout.log').read_text()))
            if not (d/'timing.json').is_file():
                raise RuntimeError('raw timing export missing')
            print(f'DONE rep{rep:02d} infStreams={c}', flush=True)
    summarize()


if __name__ == '__main__':
    main()
