"""Resource and interval validation, permitting unused configured capacity."""
from collections import Counter
from local_concurrency_validation import interval_metrics


def validate_concurrency(records, resources, concurrency=2):
    if concurrency not in (2, 4, 7):
        raise ValueError('unsupported screening concurrency')
    for key in ('configured_workers', 'execution_context_count', 'cuda_stream_count',
                'submission_stream_count', 'buffer_set_count', 'pinned_staging_set_count'):
        if resources[key] != concurrency:
            raise ValueError(f'resource count differs from C: {key}')
    if resources['engine_instance_count'] != 1:
        raise ValueError('one shared engine required')
    workers = resources['workers']
    if len(workers) != concurrency or {w['worker_id'] for w in workers} != set(range(concurrency)):
        raise ValueError('invalid configured worker pool')
    used = {r['worker_id'] for r in records}
    if not used or not used <= set(range(concurrency)):
        raise ValueError('unknown or empty worker usage')
    for key in ('context_object_id', 'cuda_stream_pointer'):
        values = [w[key] for w in workers]
        if len(set(values)) != concurrency or not all(values):
            raise ValueError('context/stream alias or null resource')
    for key in ('device_buffers', 'pinned_host_buffers'):
        intervals = []
        for worker in workers:
            if set(worker[key]) != {'inputs', 'pred_logits', 'pred_boxes'}:
                raise ValueError('incomplete buffer set')
            for name, address in worker[key].items():
                size = worker['buffer_bytes'][name]
                if address <= 0 or size <= 0:
                    raise ValueError('invalid allocation')
                intervals.append((address, address+size))
        intervals.sort()
        if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
            raise ValueError('overlapping buffer allocation ranges')
    for r in records:
        if r['context_id'] != r['worker_id']:
            raise ValueError('context ownership differs from worker')
        if (r['service_start_ns'], r['service_completion_ns']) != (r['s_ns'], r['c_ns']):
            raise ValueError('service timestamp alias mismatch')
        if not r['s_ns'] <= r['submission_return_ns'] < r['stream_sync_return_ns'] <= r['c_ns']:
            raise ValueError('invalid submission ordering')
    service = interval_metrics(records, concurrency=concurrency)
    outstanding = interval_metrics(records, 'submission_return_ns', 'stream_sync_return_ns', concurrency)
    # Low load can leave configured capacity idle; actual overlap is reported.
    return {**service, 'service_overlap_pair_count': service['service_interval_overlap_count'],
            'service_overlap_time_ms': service['service_interval_overlap_time_ms'],
            'worker_request_counts': dict(Counter(r['worker_id'] for r in records)),
            'configured_workers': concurrency, 'workers_actually_used': len(used),
            'worker_ids_used': sorted(used), 'unused_worker_ids': sorted(set(range(concurrency))-used),
            'resource_ownership': 'PASS', 'buffer_ranges_nonoverlapping': True,
            'submitted_not_yet_synchronized_intervals': outstanding,
            'evidence_scope': 'concurrent submission/outstanding host intervals only; GPU kernel overlap not measured'}
