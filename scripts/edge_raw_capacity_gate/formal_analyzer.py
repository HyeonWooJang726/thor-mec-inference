#!/usr/bin/env python3
"""Read-only raw replay; writes only a new explicitly named analysis directory."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import formal_protocol as p

THOR_KEYS = ('logical_arrival_ns', 'payload_ready_ns', 'socket_submission_ns',
             'socket_send_complete_ns', 'response_completion_ns')
EDGE_KEYS = ('receive_complete_ns', 'queue_enter_ns', 'queue_start_ns',
             'preprocess_start_ns', 'preprocess_end_ns', 'inference_start_ns',
             'inference_end_ns', 'response_ready_ns')


def quantiles(values):
    if not values:
        return dict.fromkeys(('mean', 'p50', 'p95', 'p99'))
    return dict(zip(('mean', 'p50', 'p95', 'p99'),
                    map(float, [np.mean(values), *np.percentile(values, [50, 95, 99])])))


def backlog(rows, start, end, window_seconds):
    """Continuous-time OLS of sum of unfinished-request indicators.

    Same indicator integral as canonical Rate-DVFS queue_slope; missing completion
    extends to the right window boundary. Never regress on drain observations.
    """
    left = end - int(window_seconds * 1e9)
    duration = (end - left) / 1e9
    numerator = 0.0
    events = {}
    for row in rows:
        a, c = row['logical_arrival_ns'], row.get('response_completion_ns')
        if c is not None and c < a:
            raise ValueError('negative unfinished backlog interval')
        events[a] = events.get(a, 0) + 1
        if c is not None:
            events[c] = events.get(c, 0) - 1
        x, y = max(a, left), min(c if c is not None else end, end)
        if y > x:
            x, y = (x-left)/1e9-duration/2, (y-left)/1e9-duration/2
            numerator += (y*y-x*x)/2
    n = peak = 0
    for stamp, delta in sorted(events.items()):
        if stamp >= end:
            break
        n += delta
        if n < 0:
            raise ValueError('negative backlog')
        peak = max(peak, n)
    return dict(g_B_E=numerator/(duration**3/12), peak_backlog=peak,
                active_end_backlog=n,
                after_drain_backlog=sum(r.get('response_completion_ns') is None for r in rows),
                regression_start_ns=left, regression_end_ns=end)


def summarize(manifest, rows, final, errors):
    errors = list(errors)
    start, end = manifest['active_start_ns'], manifest['active_end_ns']
    duration = manifest['seconds']
    planned = manifest['rate'] * duration
    ids = [r['request_id'] for r in rows]
    if len(ids) != planned or set(ids) != set(range(planned)):
        errors.append('logical request identity/count corruption')
    for row in rows:
        if not start <= row['logical_arrival_ns'] < end:
            errors.append('arrival outside active window')
        # sender sendall may finish bookkeeping after a fast response arrives.
        for keys in [THOR_KEYS[:4], (THOR_KEYS[0], THOR_KEYS[2], THOR_KEYS[4]), EDGE_KEYS]:
            values = [row.get(k) for k in keys]
            known = [v for v in values if v is not None]
            if known != sorted(known):
                errors.append(f'timestamp ordering: request {row["request_id"]}, {keys}')
        if row.get('response_completion_ns') is not None:
            if any(row.get(k) is None for k in (*THOR_KEYS, *EDGE_KEYS)):
                errors.append('completed request has incomplete trace')
            if row.get('payload_sha256') != row.get('raw_sha256'):
                errors.append('wire payload SHA256 mismatch')
    counts = dict(logically_admitted=len(rows),
                  payload_ready=sum(r.get('payload_ready_ns') is not None for r in rows),
                  submitted=sum(r.get('socket_send_complete_ns') is not None for r in rows),
                  Edge_received=final.get('received'), Edge_completed=final.get('completed'),
                  Thor_completed=sum(r.get('response_completion_ns') is not None for r in rows))
    if any(v != planned for v in counts.values()):
        errors.append('stage accounting incomplete/mismatch')
    if not manifest.get('active_phase_completed') or not manifest.get('threads_exited'):
        errors.append('client lifecycle incomplete')
    if (final.get('integrity_status') != 'VALID' or not final.get('cleanup_completed')
            or not final.get('worker_thread_exited') or not final.get('drain_completed')):
        errors.append('server clean drain/cleanup not confirmed')
    if final.get('errors'):
        errors.extend(final['errors'])
    duplicate = manifest.get('duplicate_responses', 0)
    if duplicate:
        errors.append('duplicate response')
    try:
        bg = backlog(rows, start, end, 30 if duration == 60 else duration/2)
    except ValueError as error:
        errors.append(str(error))
        bg = dict(g_B_E=None, peak_backlog=None, active_end_backlog=None,
                  after_drain_backlog=planned-counts['Thor_completed'])
    def active(key):
        return sum(r.get(key) is not None and start <= r[key] < end for r in rows)
    completed, submitted = active('response_completion_ns'), active('socket_send_complete_ns')
    lat = {}
    # Latencies cover all returned active-logical requests, including drain completions.
    for name, a, b in [('E2E', 'logical_arrival_ns', 'response_completion_ns'),
                       ('client_pending', 'logical_arrival_ns', 'socket_submission_ns'),
                       ('socket_send', 'socket_submission_ns', 'socket_send_complete_ns'),
                       ('Edge_queue', 'queue_enter_ns', 'queue_start_ns'),
                       ('preprocess', 'preprocess_start_ns', 'preprocess_end_ns'),
                       ('inference', 'inference_start_ns', 'inference_end_ns')]:
        lat[name] = quantiles([(r[b]-r[a])/1e6 for r in rows if r.get(a) is not None and r.get(b) is not None])
    integrity = 'INVALID' if errors else 'VALID'
    stable = (integrity == 'VALID' and bg['g_B_E'] <= 0.5
              and not final.get('queue_cap_saturation') and not final.get('drops')
              and bg['after_drain_backlog'] == 0)
    return dict(run_id=manifest['run_id'], mode=manifest['mode'], repeat=manifest['repeat'],
                offered_FPS=len(rows)/duration, submitted_FPS=submitted/duration,
                completed_FPS=completed/duration, completion_offered_ratio=completed/planned,
                stage_counts=counts, **bg, latency_ms=lat,
                latency_population='all returned active-logical requests; includes natural drain',
                application_payload_Mbps=len(rows)/duration*p.RAW_BYTES*8/1e6,
                submitted_application_Mbps=submitted/duration*p.RAW_BYTES*8/1e6,
                TCP_baseline_mean_Mbps=manifest['TCP_baseline_mean_Mbps'],
                application_load_ratio=(len(rows)/duration*p.RAW_BYTES*8/1e6)/manifest['TCP_baseline_mean_Mbps'],
                errors=errors, error_count=len(errors), missing_requests=planned-counts['Thor_completed'],
                duplicate_responses=duplicate, drops=final.get('drops'),
                queue_cap_saturation=final.get('queue_cap_saturation'),
                integrity_status=integrity, stability='STABLE' if stable else 'UNSTABLE' if integrity=='VALID' else 'INVALID',
                bottleneck_classification='NONE_OBSERVED' if stable else 'MIXED/UNRESOLVED',
                attribution_note='No automated GPU/network attribution from cross-host timestamps. Inspect raw stage evidence.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    summaries = []
    for path in sorted(Path(args.input).glob('*/manifest.json')):
        manifest = json.loads(path.read_text())
        if 'client_hello' in manifest:
            continue  # Edge request logs use a separate clock; never pool them as Thor runs.
        if 'active_start_ns' not in manifest:
            summaries.append(dict(run_id=manifest['run_id'], mode=manifest['mode'],
                             repeat=manifest['repeat'], integrity_status='INVALID', stability='INVALID',
                             errors=['preflight/handshake failed before active interval']))
            continue
        with (path.parent/'requests.csv').open() as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            for key in ('request_id', 'sample_id', *THOR_KEYS, *EDGE_KEYS):
                if key in row:
                    row[key] = int(row[key]) if row[key] else None
        final = json.loads((path.parent/'server_final.json').read_text())
        errors = json.loads((path.parent/'errors.json').read_text())
        summaries.append(summarize(manifest, rows, final, errors))
    if not summaries:
        raise ValueError('no completed raw run directories; inspect preflight/failure records')
    p.save(out/'replayed_summaries.json', summaries)
    fields = ('run_id','mode','repeat','offered_FPS','submitted_FPS','completed_FPS',
              'completion_offered_ratio',
              'g_B_E','peak_backlog','active_end_backlog','after_drain_backlog',
              'application_payload_Mbps','application_load_ratio','error_count','missing_requests',
              'duplicate_responses','drops','queue_cap_saturation',
              'integrity_status','stability','bottleneck_classification')
    latency_fields = tuple(f'{stage}_{q}_ms' for stage in ('E2E','Edge_queue','preprocess','inference')
                           for q in ('mean','p50','p95','p99'))
    with (out/'edge_rate_summary.csv').open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields+latency_fields, extrasaction='ignore')
        w.writeheader()
        for summary in summaries:
            flat = dict(summary)
            for stage, stats in summary.get('latency_ms', {}).items():
                flat.update({f'{stage}_{q}_ms': value for q,value in stats.items()})
            w.writerow(flat)
    primary = [r for r in summaries if r['mode']=='campaign']
    forty = [r for r in primary if r.get('offered_FPS')==40]
    verdict = 'INCONCLUSIVE'
    if len(forty)==3 and all(r['integrity_status']=='VALID' for r in forty):
        if all(r['stability']=='STABLE' for r in forty):
            verdict='EDGE_40FPS_SUSTAINABLE'
        elif all(r['stability']=='UNSTABLE' for r in forty):
            verdict='EDGE_40FPS_NOT_SUSTAINABLE'
    p.save(out/'verdict.json', dict(verdict=verdict, primary_runs=len(primary),
           note='Smoke excluded. Mixed/invalid 40-FPS repeats remain INCONCLUSIVE. No hybrid result implied.'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
