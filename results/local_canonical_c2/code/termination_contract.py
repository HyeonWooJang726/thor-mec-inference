"""Post-drain lifecycle validation. EOS observation never synthesized."""
def validate_termination(e):
    errors = []
    n, k = e['frames_per_stream'], e['streams']
    bounded = []
    if e['mode'] not in ('bounded', 'full_source'):
        errors.append('invalid source mode')
    for i in range(k):
        stream = e['per_stream'][i]
        ok = (stream['source_samples_pulled'] == n
              and stream['frame_ids'] == list(range(n))
              and stream['source_loop_normal_return']
              and stream['source_joined'] and stream['pipeline_shutdown_requested']
              and stream['pipeline_NULL_confirmed']
              and not stream['worker_exception'] and not stream['gstreamer_errors'])
        bounded.append(bool(ok))
        if not ok:
            errors.append(f'stream {i}: bounded source lifecycle incomplete')
        if e['mode'] == 'full_source' and not stream['eos_observed']:
            errors.append(f'stream {i}: natural EOS not observed')
    if set(e['counts'].values()) != {n*k}:
        errors.append('global counts incomplete')
    if any(e['timing'].values()):
        errors.append('timing/decomposition failure')
    if e['waiting_after_drain'] != 0 or e['active_after_drain'] != 0 or e['negative_waiting_depth_events'] != 0:
        errors.append('queue/active drain failure')
    if not e['all_workers_joined']:
        errors.append('worker join failure')
    if e['watchdog_triggered']:
        errors.append('watchdog triggered')
    if e['runtime_errors']:
        errors.append('runtime/GStreamer/worker/cleanup errors')
    return {'validation': 'FAIL' if errors else 'PASS', 'mode': e['mode'],
            'bounded_complete': bounded,
            'eos_observed': [s['eos_observed'] for s in e['per_stream']],
            'missing_bus_EOS_stream_ids': [i for i,s in enumerate(e['per_stream']) if not s['eos_observed']],
            'errors': errors}
