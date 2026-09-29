#!/usr/bin/env python3
"""Thor paced RAW640 client. Running this CLI explicitly starts network workload."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import queue
import socket
import struct
import threading
import time
import traceback

import formal_protocol as p
from formal_analyzer import EDGE_KEYS, THOR_KEYS, summarize


def baseline(path):
    # Read the authoritative sender CSV; never substitute a hardcoded measurement.
    with Path(path).open() as f:
        rows = list(csv.DictReader(f))
    key = 'throughput_mbps'
    if len(rows) != 3 or key not in rows[0]:
        raise ValueError('unexpected authoritative TCP sender schema/count')
    return sum(float(r[key]) for r in rows)/len(rows)


def run_session(conn, out, hello, payloads, sample_ids, baseline_mean):
    """One connection per run, persistent across all requests, including drain.

    Main thread is the arrival producer. Sender and receiver are independent.
    Rows contain the frozen logical timeline even if Python scheduling is late.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    errors, rows = [], []
    final = {}
    manifest = dict(**hello, TCP_baseline_mean_Mbps=baseline_mean, provenance=p.provenance(),
                    input_isolation='cached 30 Warehouse RAW640 frames, cyclic; no decode or Local inference',
                    active_phase_completed=False, threads_exited=False, duplicate_responses=0,
                    client_queue_policy='unbounded FIFO of references; no intentional drop',
                    submitted_definition='sendall complete; socket_submission marks sendall start',
                    clock_rule='Thor E2E and Edge internal durations only; no cross-host subtraction')
    outgoing = queue.Queue()
    stop = threading.Event()
    threads = []

    def fail():
        errors.append(traceback.format_exc())
        stop.set()
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    try:
        p.send_message(conn, p.HELLO, metadata=hello)
        kind, _, ready, _ = p.recv_message(conn)
        if (kind != p.READY or ready.get('warmup_inferences') != 50
                or ready.get('run_id') != hello['run_id']):
            raise ValueError('invalid READY')
        backend = ready['backend']
        helpers = p.load_runtime_helpers()
        if (backend.get('C_E') != 1 or backend.get('B') != 1
                or backend.get('CUDA_Graph') is not False or backend.get('dynamic_batching') is not False
                or backend.get('engine_sha256') != helpers.ENGINE_SHA256
                or backend.get('cache_sha256') != helpers.CACHE_SHA256
                or backend.get('opencv_required') is not False
                or backend.get('color_conversion') != 'numpy_channel_reverse_BGR_to_RGB'):
            raise ValueError('server configuration mismatch')
        p.save(out/'server_ready.json', ready)
        start = time.monotonic_ns() + 200_000_000
        end = start + hello['seconds']*1_000_000_000
        manifest.update(active_start_ns=start, active_end_ns=end)
        hashes = [hashlib.sha256(raw).hexdigest() for raw in payloads]
        for rid, stamp in enumerate(p.arrivals(start, hello['rate'], hello['seconds'])):
            rows.append(dict(request_id=rid, sample_id=sample_ids[rid % len(payloads)],
                        logical_arrival_ns=stamp, payload_sha256=hashes[rid % len(payloads)]))

        def sender():
            submitted = 0
            try:
                while not stop.is_set():
                    try:
                        rid = outgoing.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if rid is None:
                        p.send_message(conn, p.END, metadata=dict(submitted=submitted))
                        break
                    rows[rid]['socket_submission_ns'] = time.monotonic_ns()
                    p.send_message(conn, p.REQUEST, rid, payload=payloads[rid % len(payloads)])
                    rows[rid]['socket_send_complete_ns'] = time.monotonic_ns()
                    submitted += 1
            except BaseException:
                fail()

        def receiver():
            seen = set()
            try:
                with (out/'responses.bin').open('xb') as outputs:
                    while not stop.is_set():
                        kind, rid, meta, raw = p.recv_message(conn)
                        completion = time.monotonic_ns()
                        if kind == p.FINAL:
                            final.update(meta)
                            if len(seen) != len(rows):
                                raise ValueError('FINAL before all responses')
                            break
                        if kind != p.RESPONSE or not 0 <= rid < len(rows):
                            raise ValueError('unexpected response kind/id')
                        if rid in seen:
                            manifest['duplicate_responses'] += 1
                            raise ValueError('duplicate response')
                        p.decode_outputs(raw)
                        if meta.get('raw_sha256') != rows[rid]['payload_sha256']:
                            raise ValueError('RAW640 transfer hash mismatch')
                        if any(type(meta.get(key)) is not int for key in EDGE_KEYS):
                            raise ValueError('missing/corrupt server timestamps')
                        seen.add(rid)
                        # Only explicit Edge fields are copied; never overwrite Thor timestamps.
                        rows[rid].update({key: meta[key] for key in (*EDGE_KEYS, 'raw_sha256')})
                        rows[rid]['response_completion_ns'] = completion
                        # Lossless output evidence, network-endian uint64 ID + little-endian FP32 arrays.
                        outputs.write(struct.pack('!Q', rid))
                        outputs.write(raw)
            except BaseException:
                fail()

        threads = [threading.Thread(target=sender, name='Thor-sender'),
                   threading.Thread(target=receiver, name='Thor-response-receiver')]
        for thread in threads:
            thread.start()
        for row in rows:
            delay = (row['logical_arrival_ns']-time.monotonic_ns())/1e9
            if delay > 0:
                time.sleep(delay)
            # Payload is already cached. Scheduling lag is recorded, not removed from workload.
            row['payload_ready_ns'] = time.monotonic_ns()
            outgoing.put(row['request_id'])
        delay = (end-time.monotonic_ns())/1e9
        if delay > 0:
            time.sleep(delay)
        manifest['active_phase_completed'] = True
        outgoing.put(None)
        for thread in threads:
            thread.join()
    except BaseException:
        fail()
    finally:
        if errors:
            stop.set()
        outgoing.put(None)
        for thread in threads:
            thread.join()
        manifest['threads_exited'] = all(not t.is_alive() for t in threads)
        manifest['client_cleanup_ns'] = time.monotonic_ns()
        with (out/'requests.csv').open('x', newline='') as f:
            fields = ['request_id', 'sample_id', *THOR_KEYS, *EDGE_KEYS, 'payload_sha256', 'raw_sha256']
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        p.save(out/'manifest.json', manifest)
        p.save(out/'server_final.json', final)
        p.save(out/'errors.json', errors)
        (out/'stderr.log').write_text('\n'.join(errors))
    if 'active_start_ns' not in manifest:
        summary = dict(integrity_status='INVALID', stability='INVALID', errors=errors,
                       reason='handshake/preflight failed; no active interval')
    else:
        summary = summarize(manifest, rows, final, errors)
    p.save(out/'summary.json', summary)
    return summary


def smoke_ok(path):
    root = Path(path)
    manifest = json.loads((root/'manifest.json').read_text())
    summary = json.loads((root/'summary.json').read_text())
    if (manifest.get('mode') != 'smoke' or manifest.get('rate') != 8 or manifest.get('seconds') != 10
            or summary.get('integrity_status') != 'VALID' or not manifest.get('threads_exited')
            or summary.get('after_drain_backlog') != 0 or summary.get('queue_cap_saturation')
            or summary.get('drops')):
        raise ValueError('8 FPS/10 s smoke integrity PASS required before campaign')
    # Avoid treating a smoke from a different implementation as approval evidence.
    if manifest['provenance']['source_sha256'] != p.provenance()['source_sha256']:
        raise ValueError('smoke source hash differs from current formal path')
    return {name: p.sha(root/name) for name in ('manifest.json','summary.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['smoke', 'campaign'])
    parser.add_argument('--host', default='192.168.0.7')
    parser.add_argument('--cache', required=True)
    parser.add_argument('--tcp-baseline', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--smoke-result', help='Required for campaign; exact smoke run directory')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    try:
        helpers = p.load_runtime_helpers()
        payloads, ids = helpers.load_cache(args.cache)
        mean = baseline(args.tcp_baseline)
        prior = None
        if args.mode == 'campaign':
            if not args.smoke_result:
                raise ValueError('--smoke-result required')
            prior = smoke_ok(args.smoke_result)
        order = [(0,8)] if args.mode == 'smoke' else p.ORDER
        p.save(out/'campaign_manifest.json', dict(mode=args.mode, order=order, host=args.host,
               port=p.PORT, provenance=p.provenance(), smoke_evidence=prior,
               cache_sha256=helpers.CACHE_SHA256, tcp_baseline_path=str(Path(args.tcp_baseline).resolve()),
               tcp_baseline_sha256=p.sha(args.tcp_baseline), TCP_baseline_mean_Mbps=mean,
               requested_system_changes='NONE', C_E=1, B=1))
        runs = []
        for index, (repeat, rate) in enumerate(order):
            hello = dict(mode=args.mode, rate=rate, repeat=repeat,
                         seconds=10 if args.mode=='smoke' else 60,
                         run_id=f'{args.mode}_{index+1:02d}', cache_sha256=helpers.CACHE_SHA256)
            try:
                with socket.create_connection((args.host, p.PORT), timeout=300) as conn:
                    result = run_session(conn, out/hello['run_id'], hello, payloads, ids, mean)
                result.setdefault('run_id', hello['run_id'])
                runs.append(result)
                print(hello['run_id'], result['integrity_status'], flush=True)
            except BaseException:
                failure = dict(run_id=hello['run_id'], integrity_status='INVALID', traceback=traceback.format_exc())
                p.save(out/(hello['run_id']+'_connection_failure.json'), failure)
                runs.append(failure)
                # Server session index is unknown after connection/protocol failure.
                # No automatic retry/reconnection that could mislabel the frozen order.
                break
        p.save(out/'campaign_status.json', dict(planned=len(order), attempted=len(runs), runs=runs))
        return 0 if len(runs)==len(order) and all(r['integrity_status']=='VALID' for r in runs) else 1
    except BaseException:
        p.save(out/'client_failure.json', dict(traceback=traceback.format_exc()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
