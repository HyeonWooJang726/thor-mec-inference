"""Raw integer-ns interval validation; host intervals do not prove kernel overlap."""
from collections import Counter


def interval_metrics(records, start='s_ns', end='c_ns', concurrency=2):
    events = []
    for index, r in enumerate(records):
        a, b = r[start], r[end]
        if type(a) is not int or type(b) is not int or a >= b:
            raise ValueError('invalid service interval')
        events.extend([(a, 1, index), (b, -1, index)])
    active = set()
    peak = overlap_count = overlap_ns = 0
    previous = None
    for ns, delta, index in sorted(events):  # end before start at ties: [s,c).
        if previous is not None and len(active) >= 2:
            overlap_ns += ns-previous
        if delta == 1:
            worker = records[index]['worker_id']
            if any(records[i]['worker_id'] == worker for i in active):
                raise ValueError('same worker has overlapping requests')
            overlap_count += len(active)
            active.add(index)
        else:
            active.remove(index)
        peak = max(peak, len(active))
        previous = ns
    if peak > concurrency or active:
        raise ValueError(f'C={concurrency} active accounting violation')
    return {'max_active_inferences': peak, 'service_interval_overlap_count': overlap_count,
            'service_interval_overlap_time_ns': overlap_ns,
            'service_interval_overlap_time_ms': overlap_ns/1_000_000,
            'active_after_drain': len(active)}


def validate_concurrency(records, resources, concurrency=2):
    if concurrency not in (1, 2):
        raise ValueError('unsupported concurrency')
    if resources['execution_context_count'] != concurrency or resources['cuda_stream_count'] != concurrency:
        raise ValueError('context/stream count differs from C')
    if set(r['worker_id'] for r in records) != set(range(concurrency)):
        raise ValueError('all configured workers must perform requests')
    if 'workers' in resources:
        workers = resources['workers']
        if len(workers) != concurrency:
            raise ValueError('worker resource count differs from C')
        for key in ('context_object_id', 'cuda_stream_pointer'):
            values = [w[key] for w in workers]
            if len(set(values)) != concurrency or not all(values):
                raise ValueError('resources not independent/nonzero')
        for key in ('device_buffers', 'pinned_host_buffers'):
            values = [v for w in workers for v in w[key].values()]
            if len(values) != 3*concurrency or len(set(values)) != len(values) or not all(values):
                raise ValueError('buffer alias/count invalid')
    for r in records:
        if r['service_start_ns'] != r['s_ns'] or r['service_completion_ns'] != r['c_ns']:
            raise ValueError('service alias differs from raw boundary')
        if not r['s_ns'] <= r['submission_return_ns'] <= r['stream_sync_return_ns'] <= r['c_ns']:
            raise ValueError('submission ordering invalid')
    metrics = interval_metrics(records, concurrency=concurrency)
    outstanding = interval_metrics(records, 'submission_return_ns', 'stream_sync_return_ns', concurrency)
    if concurrency == 2 and (metrics['max_active_inferences'] != 2 or not metrics['service_interval_overlap_time_ns']):
        raise ValueError('no concurrent service: C=2 validation FAIL')
    if concurrency == 2 and (outstanding['max_active_inferences'] != 2 or not outstanding['service_interval_overlap_time_ns']):
        raise ValueError('no overlapping submitted-not-yet-synchronized host intervals')
    return {**metrics, 'service_overlap_pair_count': metrics['service_interval_overlap_count'],
            'service_overlap_time_ms': metrics['service_interval_overlap_time_ms'],
            'worker_request_counts': dict(Counter(r['worker_id'] for r in records)),
            'submitted_not_yet_synchronized_intervals': outstanding,
            'evidence_scope': 'concurrent inference submission only; GPU kernel overlap not directly measured'}
