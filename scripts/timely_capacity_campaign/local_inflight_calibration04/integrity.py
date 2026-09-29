"""C-dependent post-run cardinality checks for calibration04 only."""


def validate_cardinality(condition, manifest, raw, phase, workers):
    c = int(condition['C'])
    t0 = manifest['active_start_ns']
    per_worker = int(manifest['warmup_inferences_per_worker'])
    expected_ids = set(range(c))
    errors = []

    def require(ok, message):
        if not ok:
            errors.append(message)

    resources = manifest.get('resources') or []
    resource_ids = [int(r['worker_id']) for r in resources]
    require(len(resources) == c and set(resource_ids) == expected_ids and
            len(resource_ids) == len(set(resource_ids)), 'context cardinality mismatch')
    for key in ('context_object_id', 'cuda_stream_pointer'):
        values = [r.get(key) for r in resources]
        require(len(values) == c and None not in values and len(set(values)) == c,
                key + ' missing/aliased')
    worker_ids = [int(w['worker_id']) for w in workers]
    require(len(workers) == c and set(worker_ids) == expected_ids and
            len(worker_ids) == len(set(worker_ids)), 'missing worker-level accounting entry')
    warm = [r for r in raw if r.get('phase') == 'warmup']
    require(len(warm) == c * per_worker, 'warmup count mismatch')
    for worker_id in expected_ids:
        rows = [r for r in warm if int(r['worker_id']) == worker_id]
        require(len(rows) == per_worker, 'warmup per-worker count mismatch: ' + str(worker_id))
    require(all(r.get('completion_timestamp_ns') not in ('', None) and
                int(r['completion_timestamp_ns']) < t0 for r in warm),
            'warmup completion missing/after active start')
    phase_ids = [int(r['worker_id']) for r in phase]
    require(set(phase_ids) == expected_ids, 'phase worker IDs mismatch')
    for w in workers:
        worker_id = int(w['worker_id'])
        count = phase_ids.count(worker_id)
        require(w.get('records') == count, 'worker phase record count mismatch: ' + str(worker_id))
        require(w.get('record_calls') == 2 * (per_worker + count) and
                w.get('elapsed_calls') == count,
                'worker event accounting mismatch: ' + str(worker_id))
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': sorted(set(errors)),
            'planned_C': c, 'actual_contexts': len(resources),
            'actual_worker_entries': len(workers),
            'expected_warmup': c * per_worker, 'actual_warmup': len(warm)}
