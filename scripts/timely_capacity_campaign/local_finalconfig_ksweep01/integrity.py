"""C- and K-dependent post-run cardinality checks for this K sweep."""


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
    # A worker may warm up correctly yet receive no active frames at low K.
    # All three worker entries and warm-up ledgers are still mandatory; every
    # observed active phase ID must belong to the planned set, and per-worker
    # records/event counts below must match exactly (including zero).
    require(set(phase_ids).issubset(expected_ids), 'phase worker IDs mismatch')
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


def validate_source(condition, manifest, raw, summary):
    """Reject extra/missing streams, source IDs and per-stream summary rows."""
    from config import PLAN, sha
    k = int(condition['K'])
    seconds = int(condition['seconds'])
    expected_streams = set(range(k))
    expected_frames = set(range(30*seconds))
    active = [r for r in raw if r.get('phase') == 'active']
    errors = []
    def require(ok, why):
        if not ok: errors.append(why)
    require(int(manifest.get('K', -1)) == k, 'planned/actual K mismatch')
    require(int(manifest.get('C', -1)) == int(condition['C']), 'planned/actual C mismatch')
    require(int(manifest.get('batch_size', -1)) == 1, 'B != 1')
    require(manifest.get('plan_sha256') == sha(PLAN), 'plan SHA mismatch')
    for key in ('target_service_FPS', 'deadline_ms'):
        require(manifest.get(key) == condition[key], key+' mismatch')
    require(manifest.get('measurement_seconds') == seconds, 'active duration mismatch')
    require(manifest.get('local_r') == 30 and manifest.get('edge_r') == 0 and
            manifest.get('admission_pattern') == 'ALIGNED' and
            manifest.get('pruning_enabled') is False, 'Local-only runtime condition mismatch')
    require(len(active) == k*30*seconds, 'K-specific source count mismatch')
    ids = [(int(r['stream_id']), int(r['frame_id'])) for r in active]
    require(len(ids) == len(set(ids)), 'duplicate source IDs')
    require({sid for sid, _ in ids} == expected_streams, 'source stream ID set mismatch')
    require(all(sid in expected_streams and fid in expected_frames for sid, fid in ids),
            'out-of-range source ID')
    for sid in expected_streams:
        require({fid for stream, fid in ids if stream == sid} == expected_frames,
                'missing/extra per-stream frame IDs: '+str(sid))
    per = summary.get('per_stream') or []
    require(len(per) == k and {int(r['stream_id']) for r in per} == expected_streams,
            'per-stream accounting cardinality mismatch')
    require(all(int(r.get('source_frames', -1)) == 30*seconds for r in per),
            'per-stream source count mismatch')
    require(summary.get('active_concurrency_peak') is not None and
            summary['active_concurrency_peak'] <= int(condition['C']),
            'active concurrency exceeds C_L')
    return dict(status='PASS' if not errors else 'FAIL', errors=errors,
                planned_K=k, actual_streams=sorted({sid for sid, _ in ids}),
                expected_source_count=k*30*seconds, actual_source_count=len(active))
