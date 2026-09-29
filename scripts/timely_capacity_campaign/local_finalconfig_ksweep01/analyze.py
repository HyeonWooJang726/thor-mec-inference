"""Read-only formal Local K-sweep analysis; refuses incomplete/invalid data."""
import argparse
import csv
import inspect
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

from config import OUT, PLAN, load_plan, sha
from integrity import validate_cardinality, validate_source
from ksweep_schedule import decorate
import analyze_b1 as inherited


_source = inspect.getsource(inherited.validate_run)
_anchors = {
    'for k in range(8):': "for k in range(int(c['K'])):",
    "len(wi)==2 and {int(w['worker_id']) for w in wi}=={0,1}":
        "len(wi)==int(c['C']) and {int(w['worker_id']) for w in wi}==set(range(int(c['C'])))",
}
for old, new in _anchors.items():
    if _source.count(old) != 1:
        raise RuntimeError('Frozen offline validator anchor changed: '+old)
    _source = _source.replace(old, new)
_namespace = dict(inherited.__dict__, cfg=SimpleNamespace(decorate=decorate))
exec(compile(_source, '<ksweep-strict-offline-validator>', 'exec'), _namespace)
_validate = _namespace['validate_run']


def active_concurrency_p95(rows, start, end):
    events = {}
    for row in rows:
        a = inherited.number(row, 'inference_start_timestamp_ns')
        b = inherited.number(row, 'completion_timestamp_ns')
        if a is None or b is None:
            continue
        a, b = max(a, start), min(b, end)
        if a < b:
            events[a] = events.get(a, 0)+1
            events[b] = events.get(b, 0)-1
    level, last, duration = 0, start, {}
    for stamp, delta in sorted(events.items()):
        duration[level] = duration.get(level, 0)+stamp-last
        level += delta
        last = stamp
    duration[level] = duration.get(level, 0)+end-last
    if level != 0:
        raise RuntimeError('Unbalanced active concurrency events')
    total = 0
    for value, span in sorted(duration.items()):
        total += span
        if total >= .95*(end-start):
            return value
    raise RuntimeError('Incomplete concurrency coverage')


def analyze_run(directory, condition):
    manifest = json.loads((directory/'manifest.json').read_text())
    summary = json.loads((directory/'summary.json').read_text())
    raw = inherited.read(directory/'per_frame.csv.gz')
    phase = inherited.read(directory/'per_frame_phase_timestamps.csv')
    workers = json.loads((directory/'phase_instrumentation_manifest.json').read_text())
    checks = (_validate(condition, manifest, summary, raw, phase, workers),
              validate_cardinality(condition, manifest, raw, phase, workers),
              validate_source(condition, manifest, raw, summary))
    errors = sorted(set(error for check in checks for error in check['errors']))
    for name in ('CPU_BEFORE_RUN.json', 'CPU_AFTER_RUN.json'):
        if json.loads((directory/name).read_text()).get('status') != 'PASS':
            errors.append(name+' failed')
    if manifest.get('CPU_pin_child_readback', {}).get('status') != 'PASS':
        errors.append('CPU child pin failed')
    for field in ('active_phase_completed', 'drain_completed', 'cleanup_completed',
                  'frequency_restore_ok'):
        if manifest.get(field) is not True:
            errors.append(field+' failed')
    if manifest.get('child_returncode') != 0 or summary.get('PROCESS_LIFECYCLE') != 'PASS':
        errors.append('process lifecycle failed')
    if summary.get('integrity_status') != 'VALID' or summary.get('true_unfinished_after_drain') != 0:
        errors.append('saved integrity/terminal failure')
    if manifest.get('requested_freq_MHz') != 1575 or summary.get('actual_clock_non_target_fraction') != 0:
        errors.append('GPU target/readback mismatch')
    base, _, _ = inherited.summarize_run(condition, manifest, summary, raw, phase)
    active = [r for r in raw if r.get('phase') == 'active']
    local = [r for r in active if r.get('placement') == 'LOCAL']
    queue = inherited.quant([(int(r['inference_start_timestamp_ns']) - int(r['ready_timestamp_ns']))/1e6
                             for r in local if r.get('inference_start_timestamp_ns') not in ('', None)])
    service = inherited.quant([(int(r['completion_timestamp_ns']) - int(r['inference_start_timestamp_ns']))/1e6
                               for r in local if r.get('completion_timestamp_ns') not in ('', None)])
    result = dict(run_id=condition['run_id'], repeat=condition['repeat'], K=condition['K'],
                  C_L=condition['C'], B=1, Edge='OFF', per_stream_input_FPS=30,
                  aggregate_offered_FPS=30*condition['K'],
                  expected_source_frames=condition['K']*30*condition['seconds'],
                  actual_source_frames=len(active), completed_FPS=base['raw_completed_FPS'],
                  overall_TIR=summary['TIR_source'], timely_FPS=summary['timely_FPS'],
                  worst_stream_TIR=summary['worst_stream_TIR'],
                  queue_p50_ms=queue['p50'], queue_p95_ms=queue['p95'],
                  service_p50_ms=service['p50'], service_p95_ms=service['p95'],
                  active_concurrency_mean=summary['active_concurrency_mean'],
                  active_concurrency_p95=active_concurrency_p95(local,
                      manifest['active_start_ns'], manifest['active_end_ns']),
                  active_concurrency_peak=summary['active_concurrency_peak'],
                  measurement_end_unfinished=summary.get('unfinished_at_active_end'),
                  after_drain_unfinished=summary.get('true_unfinished_after_drain'),
                  missing_source_frames=summary.get('missing_frames'),
                  duplicate_source_frames=len(active)-len({(r['stream_id'],r['frame_id']) for r in active}),
                  per_stream_TIR_json=json.dumps([
                      dict(stream_id=int(stream['stream_id']), TIR=stream['TIR_source'])
                      for stream in summary['per_stream']]),
                  integrity_status='VALID' if not errors else 'INVALID', errors=errors)
    return result


def _csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = load_plan()
    restore = json.loads((OUT/'CPU_RESTORE_READBACK.json').read_text())
    if restore.get('status') != 'PASS' or restore.get('mode') != 'restored':
        raise RuntimeError('CPU restore PASS required before analysis')
    runs = [analyze_run(OUT/c['run_id'], c) for c in plan['order']]
    if len(runs) != 40 or any(r['integrity_status'] != 'VALID' for r in runs):
        raise RuntimeError('Complete 40/40 VALID cohort required; preserve invalid evidence')
    args.output.mkdir(parents=True, exist_ok=False)
    _csv(args.output/'per_run.csv', runs)
    per_stream = [dict(run_id=run['run_id'], K=run['K'], repeat=run['repeat'], **stream)
                  for run in runs for stream in json.loads(run['per_stream_TIR_json'])]
    if len(per_stream) != sum(run['K'] for run in runs):
        raise RuntimeError('K-specific per-stream reporting cardinality mismatch')
    _csv(args.output/'per_stream.csv', per_stream)
    metrics = ('completed_FPS', 'overall_TIR', 'worst_stream_TIR', 'timely_FPS')
    rows = []
    for k in range(1, 9):
        cohort = [r for r in runs if r['K'] == k]
        if len(cohort) != 5 or {r['repeat'] for r in cohort} != set(range(1, 6)):
            raise RuntimeError('K-specific five-repeat cohort mismatch')
        for metric in metrics:
            values = [r[metric] for r in sorted(cohort, key=lambda row: row['repeat'])]
            rows.append(dict(K=k, metric=metric, n=5, mean=statistics.mean(values),
                             sample_SD=statistics.stdev(values),
                             **{f'R{i}': value for i, value in enumerate(values, 1)}))
    _csv(args.output/'per_K_summary.csv', rows)
    with (args.output/'provenance.json').open('x') as stream:
        json.dump(dict(plan_sha256=sha(PLAN), run_count=40,
                       synthetic_data_used=False, C_L=3, B=1, Edge='OFF'), stream, indent=2)


if __name__ == '__main__':
    main()
