"""Pure post-run phase arithmetic; no runtime imports, live telemetry or file mutation."""
import math
import statistics

SEGMENTS = {
    'pop_to_expiry_check_ms': ('t_worker_pop', 't_expiry_check_done'),
    'expiry_check_to_preinfer_ms': ('t_expiry_check_done', 't_pre_infer'),
    'infer_call_duration_ms': ('t_pre_infer', 't_infer_return'),
    'postinfer_to_bookkeeping_ms': ('t_infer_return', 't_bookkeeping_begin'),
    'bookkeeping_duration_ms': ('t_bookkeeping_begin', 't_bookkeeping_end'),
    'existing_service_duration_ms': ('service_start', 'service_end'),
    'lock_wait_duration_ms': ('t_lock_request', 't_lock_acquired'),
    'accounting_locked_duration_ms': ('t_lock_acquired', 't_expiry_check_done'),
    'tensor_release_duration_ms': ('t_tensor_release_begin', 't_tensor_release_end'),
    'gpu_elapsed_query_duration_ms': ('t_gpu_elapsed_query_begin', 't_gpu_elapsed_query_end'),
}


def metrics(row):
    result = dict(row)
    for name, (a, b) in SEGMENTS.items():
        x, y = row.get(a), row.get(b)
        result[name] = (int(y) - int(x)) / 1e6 if x not in ('', None) and y not in ('', None) else None
    gpu = row.get('gpu_exec_duration_ms')
    gpu = float(gpu) if gpu not in ('', None) else None
    result['gpu_exec_duration_ms'] = gpu
    call = result['infer_call_duration_ms']
    result['host_wakeup_delay_ms'] = call - gpu if call is not None and gpu is not None else None
    result['residual_scope'] = 'host_call_minus_GPU_stream_TRT_span_NOT_OS_GIL_delay'
    return result


def event_validation(rows):
    executed = [r for r in rows if r['terminal_state'] == 'COMPLETED']
    values = [float(r['gpu_exec_duration_ms']) for r in executed if r.get('gpu_exec_duration_ms') not in ('', None)]
    missing = len(executed) - len(values)
    invalid = sum(not math.isfinite(v) or v < 0 for v in values)
    zero_only = bool(values) and all(v == 0 for v in values)
    statuses = sum(r.get('gpu_event_status') not in ('OK', 'ZERO') for r in executed)
    return dict(status='PASS' if executed and not (missing or invalid or zero_only or statuses) else 'INCONCLUSIVE',
                completed=len(executed), missing=missing, negative_or_nonfinite=invalid,
                zero_only=zero_only, error_status_count=statuses,
                no_values_removed=True, hardware_validation_required=True)


def startup_bins(rows, raw_rows, active_start_ns):
    """First 3s; event-time counts, start-time phase statistics, exact host overlap.

    p95 is reported descriptively only for n>=20, a pre-frozen reporting rule
    (not a performance/validity threshold). Zero-sample means are None.
    """
    raw = {(int(r['stream_id']), int(r['frame_id'])): r for r in raw_rows if r.get('phase') == 'active'}
    phase = [metrics(r) for r in rows]
    def percentile95(values):
        if len(values) < 20:
            return None
        v = sorted(values); pos = (len(v)-1)*.95; lo = int(pos); hi = min(lo+1,len(v)-1)
        return v[lo] + (pos-lo)*(v[hi]-v[lo])
    result = []
    for i in range(30):
        a = int(active_start_ns) + i*100_000_000; b = a+100_000_000
        selected = [r for r in phase if r.get('service_start') not in ('',None) and a <= int(r['service_start']) < b]
        record = dict(startup_bin=i, start_ns=a, end_ns=b, executed_starts=len(selected))
        for key in ('gpu_exec_duration_ms','infer_call_duration_ms','host_wakeup_delay_ms'):
            values = [r[key] for r in selected if r.get(key) is not None and math.isfinite(float(r[key]))]
            record[key+'_mean'] = statistics.mean(values) if values else None
            record[key+'_n'] = len(values)
            record[key+'_invalid_or_missing_count'] = len(selected) - len(values)
            if key == 'gpu_exec_duration_ms':
                record[key+'_p95'] = percentile95(values)
        area = 0; completed = expired = late = 0; queue_area = 0
        for r in raw.values():
            if r.get('placement') != 'LOCAL':
                continue
            s,c,x,q = (r.get(k) for k in ('inference_start_timestamp_ns','completion_timestamp_ns','expired_drop_ns','ready_timestamp_ns'))
            if s not in ('',None) and c not in ('',None):
                area += max(0,min(b,int(c))-max(a,int(s)))
            if c not in ('',None) and a<=int(c)<b:
                completed += 1
                late += int(c)>int(r['absolute_deadline_ns'])
            if x not in ('',None) and a<=int(x)<b:
                expired += 1
            terminal = s if s not in ('',None) else x
            if q not in ('',None) and terminal not in ('',None):
                queue_area += max(0,min(b,int(terminal))-max(a,int(q)))
        record.update(local_completed_count=completed,local_expired_count=expired,local_late_count=late,
                      host_active_concurrency_mean=area/(b-a),conceptual_local_waiting_queue_mean=queue_area/(b-a))
        result.append(record)
    return result
