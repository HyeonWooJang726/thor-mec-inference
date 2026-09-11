"""Raw-ns control statistics and independent disk-artifact validation; no GPU imports."""
import csv
import json
from fractions import Fraction

from local_latency_breakdown_metrics import (
    frame_rows_ns, validate_timing, queue_metrics, mean, percentile_ns, SEGMENTS,
)
from local_concurrency_validation import validate_concurrency

METRICS = [
    'local_latency_mean_ms', 'local_latency_median_ms', 'local_latency_p95_ms', 'local_latency_p99_ms',
    'deadline_miss_pct', 'start_lag_mean_ms', 'front_end_mean_ms',
    'queue_wait_mean_ms', 'queue_wait_p95_ms', 'inference_mean_ms', 'inference_p95_ms',
    'peak_waiting_queue', 'time_weighted_waiting_queue', 'max_active_inferences',
    'service_overlap_pair_count', 'service_overlap_time_ms',
]


def summarize_records(records, q, concurrency, c, k, run_id):
    values = {name: [r[end]-r[start] for r in records] for name, (start, end) in SEGMENTS.items()}
    result = {'C': c, 'K': k, 'run_id': run_id, 'frames': len(records)}
    for label, source, statistics in [
        ('local_latency', 'e2e', ('mean', 'median', 'p95', 'p99')),
        ('start_lag', 'frame_start_lag', ('mean',)), ('front_end', 'front_end', ('mean',)),
        ('queue_wait', 'inference_queue_wait', ('mean', 'p95')), ('inference', 'inference', ('mean', 'p95')),
    ]:
        for statistic in statistics:
            ns = mean(values[source]) if statistic == 'mean' else percentile_ns(values[source], {'median': 50, 'p95': 95, 'p99': 99}[statistic])
            result[f'{label}_{statistic}_ms'] = float(ns/1_000_000)
    result.update(
        deadline_miss_pct=float(Fraction(sum(v*30 > 1_000_000_000 for v in values['e2e'])*100, len(records))),
        peak_waiting_queue=q['inference_queue_peak'],
        time_weighted_waiting_queue=float(q['inference_queue_time_weighted']),
        max_active_inferences=concurrency['max_active_inferences'],
        service_overlap_pair_count=concurrency['service_overlap_pair_count'],
        service_overlap_time_ms=concurrency['service_overlap_time_ms'],
    )
    return result


def validate_run(output, c, k, frames, run_id):
    prefix = 'smoke_' if frames == 100 else ''
    raw = json.loads((output/f'{prefix}raw_ns.json').read_text())
    validation = json.loads((output/f'{prefix}validation.json').read_text())
    metadata = json.loads((output/f'{prefix}metadata.json').read_text())
    resources = json.loads((output/'resources.json').read_text())
    records, events = raw['records'], raw['queue_events']
    expected = k*frames
    if validation['validation'] != 'PASS' or validation['C'] != c or validation['K'] != k:
        raise ValueError('child validation or identity failure')
    if len(records) != expected or set(validation['counts'].values()) != {expected}:
        raise ValueError('frame counts not exact')
    if (metadata['concurrency'], metadata['batch_size'], metadata['fps'], metadata['frames_per_stream']) != (c, 1, 30, frames):
        raise ValueError('workload metadata mismatch')
    if resources['buffer_set_count'] != c or resources['pinned_staging_set_count'] != c:
        raise ValueError('buffer/staging set count mismatch')
    if any(validate_timing(records).values()):
        raise ValueError('raw timing/decomposition failure')
    if set(r['stream_id'] for r in records) != set(range(k)):
        raise ValueError('stream IDs differ')
    for i in range(k):
        if sorted(r['frame_id'] for r in records if r['stream_id'] == i) != list(range(frames)):
            raise ValueError('duplicate/missing frame IDs')
        counts = validation['per_stream_counts'][i]
        if any(counts[name] != frames for name in ('arrivals', 'source_samples', 'preprocessed', 'completions')):
            raise ValueError('per-stream counts differ')
    for record in records:
        if record['a_ns'] != raw['t0_ns']+(record['frame_id']*1_000_000_000)//30:
            raise ValueError('arrival phase mismatch')
        if record['context_id'] != record['worker_id']:
            raise ValueError('worker/context ownership mismatch')
    if frames == 1800 and (validation['EOS_validation'] != 'PASS' or not all(validation['source_EOS'])):
        raise ValueError('formal source EOS incomplete')
    q = queue_metrics(events, records, expected, expected)
    conc = validate_concurrency(records, resources, c)
    if c == 1 and (conc['max_active_inferences'] > 1 or conc['service_overlap_pair_count'] != 0):
        raise ValueError('C1 service overlap')
    with (output/'per_frame.csv').open() as f:
        csv_rows = list(csv.DictReader(f))
    expected_rows = frame_rows_ns(records, raw['t0_ns'])
    raw_by_id = {(r['stream_id'], r['frame_id']): r for r in records}
    if len(csv_rows) != expected:
        raise ValueError('CSV row count')
    aliases = {'start_lag_ms': 'frame_start_lag_ns', 'queue_wait_ms': 'inference_queue_wait_ns', 'local_latency_ms': 'e2e_ns'}
    for row, saved in zip(expected_rows, csv_rows):
        record = raw_by_id[(row['stream_id'], row['frame_id'])]
        for field, value in saved.items():
            if field.endswith('_ms'):
                key = aliases.get(field, field[:-3]+'_ns')
                expected_value = float(Fraction(row[key], 1_000_000))
                if float(value) != expected_value:
                    raise ValueError(f'CSV duration differs from raw: {field}')
            else:
                expected_value = record[field] if field in record else row[field]
                if int(value) != expected_value:
                    raise ValueError(f'CSV integer differs from raw: {field}')
    summary = summarize_records(records, q, conc, c, k, run_id)
    if summary != json.loads((output/'summary.json').read_text()):
        raise ValueError('summary differs from independent raw replay')
    return summary, {
        'C': c, 'K': k, 'run_id': run_id, 'validation': 'PASS', 'frames': len(records),
        'counts': validation['counts'], 'duplicate_frames': 0, 'missing_frames': 0,
        **validate_timing(records), 'negative_waiting_depth_events': sum(e['depth'] < 0 for e in events),
        'waiting_after_drain': q['waiting_after_drain'], 'active_after_drain': conc['active_after_drain'],
        'queue_accounting': 'PASS', 'CSV_raw_equality': 'PASS',
        'EOS': validation['EOS_validation'], 'concurrency': conc,
    }
