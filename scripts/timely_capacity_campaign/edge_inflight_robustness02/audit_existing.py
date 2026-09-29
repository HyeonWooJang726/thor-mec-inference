"""Read-only audit of prior Edge E48 artifacts; no hardware or network access."""
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'results/timely_capacity_campaign/v2_2'
OUT = BASE / 'edge_inflight_robustness02'


def read_csv(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def q(values, fraction):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * fraction
    i = int(k)
    return values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (k - i)


def number(row, key):
    value = row.get(key)
    return None if value in (None, '') else int(value)


def summary_rows(name):
    path = BASE / name / 'analysis01/per_run.csv'
    return [r for r in read_csv(path) if r.get('stage') != 'WARMUP']


def position_audit():
    prior = BASE / 'edge_order_robustness01'
    results = []
    for repeat in range(1, 6):
        run_id = f'EDGEORDER01_E48_BASE{repeat}'
        rows = read_csv(prior / 'sessions' / run_id / 'source_frames.csv')
        server = read_csv(prior / 'received_edge' / run_id / 'requests.csv')
        by_id = {int(r['request_id']): r for r in server}
        if len(by_id) != len(server):
            raise RuntimeError(f'duplicate server IDs: {run_id}')
        for position in range(8):
            selected = [r for r in rows if r.get('admitted') == '1'
                        and r.get('dispatch_position') == str(position)]
            if len(selected) != 180:
                raise RuntimeError(f'wrong position exposure: {run_id}, {position}')
            latency, queue_wait, thor_wait, near = [], [], [], []
            timely = expired = rescued_upper = 0
            for row in selected:
                due = number(row, 'logical_arrival_ns')
                done = number(row, 'response_completion_ns')
                sent = number(row, 'socket_submission_ns')
                rid = number(row, 'edge_request_id')
                if row.get('terminal_state') == 'EXPIRED_DROP':
                    expired += 1
                if sent is not None:
                    thor_wait.append((sent - due) / 1e6)
                if done is None:
                    continue
                ms = (done - due) / 1e6
                latency.append(ms)
                timely += ms <= 100
                if rid not in by_id:
                    raise RuntimeError(f'missing server request: {run_id}/{rid}')
                srv = by_id[rid]
                wait = (number(srv, 'queue_start_ns') - number(srv, 'queue_enter_ns')) / 1e6
                if wait < 0:
                    raise RuntimeError('negative Edge queue wait')
                queue_wait.append(wait)
                if ms > 100 and ms - wait <= 100:
                    rescued_upper += 1
                if 90 <= ms <= 120:
                    near.append(ms)
            results.append(dict(run_id=run_id, repeat=repeat, dispatch_position=position,
                assigned=len(selected), completed=len(latency), timely=timely, expired=expired,
                observed_TIR=timely / len(selected), completion_latency_p50_ms=q(latency,.5),
                completion_latency_p95_ms=q(latency,.95), server_queue_wait_p50_ms=q(queue_wait,.5),
                server_queue_wait_p95_ms=q(queue_wait,.95), thor_presend_wait_p50_ms=q(thor_wait,.5),
                thor_presend_wait_p95_ms=q(thor_wait,.95), completions_90_to_120_ms=len(near),
                late_completions_crossing_100ms_if_observed_queue_wait_removed=rescued_upper,
                optimistic_TIR_upper_bound=(timely + rescued_upper) / len(selected)))
    return results


def main():
    if (OUT / 'existing_edge_audit.json').exists() or (OUT / 'position_queue_upper_bound.csv').exists():
        raise RuntimeError('Audit output already frozen')
    e48 = summary_rows('edge_e48_confirmation01')
    order = summary_rows('edge_order_robustness01')
    required = ('server_queue_wait_p50_ms','server_queue_wait_p95_ms',
                'server_inference_p50_ms','server_inference_p95_ms',
                'Thor_client_pending_peak','Thor_request_response_p50_ms',
                'Thor_request_response_p95_ms','Thor_offload_wait_p50_ms',
                'Thor_offload_wait_p95_ms','observed_transmitted_data_rate_Mbps')
    def compact(rows):
        return [{key: r.get(key) for key in ('run_id','pattern','dispatch_order_mode',
                 'TIR_admission','integrity_status') + required} for r in rows]
    data = {'status':'PASS', 'source':'existing raw/analysis01; read-only',
            'E48_confirmation': compact([r for r in e48 if r.get('rate') == '48']),
            'order_robustness':compact(order), 'RAW640_payload_bytes':691200,
            'unavailable_metrics':'No value inferred for blank telemetry fields.'}
    with (OUT/'existing_edge_audit.json').open('x') as stream:
        json.dump(data,stream,indent=2)
        stream.write('\n')
    positions = position_audit()
    with (OUT/'position_queue_upper_bound.csv').open('x', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(positions[0]))
        writer.writeheader(); writer.writerows(positions)
    totals = {'assigned':sum(r['assigned'] for r in positions),
              'timely':sum(r['timely'] for r in positions),
              'crossing_upper_bound':sum(r['late_completions_crossing_100ms_if_observed_queue_wait_removed'] for r in positions)}
    totals['observed_TIR'] = totals['timely']/totals['assigned']
    totals['optimistic_TIR_upper_bound']=(totals['timely']+totals['crossing_upper_bound'])/totals['assigned']
    totals['scope']='Observed completed requests only; subtract observed Edge queue wait, hold all else fixed. Not measured TIR, proof, or causal estimate.'
    with (OUT/'position_queue_upper_bound_summary.json').open('x') as stream:
        json.dump(totals,stream,indent=2);stream.write('\n')
    print(json.dumps(totals,indent=2))


if __name__ == '__main__':
    main()
