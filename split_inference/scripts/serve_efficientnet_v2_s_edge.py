"""Sequential resident CUDA suffix server. Default bind is loopback only."""

import argparse
import json
from pathlib import Path
import signal
import socket
import time
import traceback

import torch

from split_inference.src.common.efficientnet_v2_s_runtime import (
    ROOT, EfficientNetV2SPartitions, GpuTimer, from_bytes, load_model, new_output,
    save_json, snapshot, to_bytes,
)
from split_inference.src.common.tcp_protocol import (
    DEFAULT_MAX_PAYLOAD, check_identity, header, recv_frame, require, send_frame,
)


def serve_connection(conn, partitions, identity, timer, log, counters, max_payload):
    hello, _, _ = recv_frame(conn, max_payload)
    require(hello['kind'] == 'hello', 'handshake required before inference')
    check_identity(hello, identity)
    send_frame(conn, header('ready', hello['request_id'], **identity), max_payload=max_payload)
    log({'event': 'handshake_pass', **identity})
    seen = set()
    while True:
        try:
            request, payload, receive_ms = recv_frame(conn, max_payload)
        except EOFError as exc:
            if str(exc) == 'peer closed before frame':
                return
            raise
        require(request['kind'] == 'infer', 'expected infer request')
        check_identity(request, identity)
        request_id, point = request['request_id'], request['partition_point']
        require(request_id not in seen, 'duplicate request ID')
        seen.add(request_id)
        start = time.monotonic_ns()
        activation = from_bytes(payload, request['shape']).cuda()
        torch.cuda.synchronize()
        h2d_ms = (time.monotonic_ns() - start) / 1e6
        result, suffix_ms = timer.run(lambda: partitions.suffix(activation, point))
        require(list(result.shape) == [1, 1000], 'suffix output shape')
        start = time.monotonic_ns()
        require(torch.isfinite(result).all().item(), 'nonfinite suffix logits')
        response = to_bytes(result)
        response_d2h_ms = (time.monotonic_ns() - start) / 1e6
        timings = {'server_receive_ms': receive_ms, 'server_deserialize_h2d_ms': h2d_ms,
                   'server_suffix_gpu_ms': suffix_ms, 'server_response_serialize_d2h_ms': response_d2h_ms}
        sent_ms = send_frame(conn, header('result', request_id, point, timings=timings, **identity),
                             response, max_payload)
        timings['server_response_send_ms'] = sent_ms
        # send duration is known only AFTER the logits frame has been sent.
        send_frame(conn, header('timings', request_id, point, timings=timings, **identity), max_payload=max_payload)
        counters[request['phase']] += 1
        log({'event': 'inference_pass', 'request_id': request_id, 'partition_point': point,
             'phase': request['phase'], 'output_shape': list(result.shape), 'timings': timings})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dict', type=Path, required=True)
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--port', type=int, default=50051)
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('--max-payload-bytes', type=int, default=DEFAULT_MAX_PAYLOAD)
    p.add_argument('--output-root', type=Path, default=ROOT / 'split_inference/results/e2e_requests')
    p.add_argument('--ready-file', type=Path)
    args = p.parse_args()
    require(0 <= args.port <= 65535 and 0 < args.timeout < float('inf'), 'port/timeout')
    require(0 < args.max_payload_bytes <= 64 * 1024 * 1024, 'max payload limit')
    output = new_output(args.output_root, 'server_')
    metadata = {'status': 'starting', 'args': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                'counts': {'warmup': 0, 'measurement': 0}, 'scope': 'sequential TCP suffix service'}
    print('RESULT_DIRECTORY=' + str(output), flush=True)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        model, identity = load_model(args.state_dict)
        partitions = EfficientNetV2SPartitions(model)
        timer = GpuTimer()
        metadata.update(identity=identity, environment=snapshot())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener, \
                (output / 'requests.jsonl').open('x', buffering=1) as records, torch.inference_mode():
            listener.settimeout(args.timeout)
            listener.bind((args.bind, args.port))
            listener.listen(1)
            metadata.update(status='listening', address=list(listener.getsockname()))
            save_json(output / 'metadata.json', metadata)
            ready = {'address': metadata['address'], 'output': str(output), **identity}
            if args.ready_file:
                with args.ready_file.open('x') as f:
                    json.dump(ready, f)
            print('READY ' + json.dumps(ready), flush=True)

            def log(record):
                records.write(json.dumps(record, allow_nan=False) + '\n')

            while True:
                try:
                    conn, peer = listener.accept()
                except TimeoutError:
                    continue
                with conn:
                    conn.settimeout(args.timeout)
                    try:
                        serve_connection(conn, partitions, identity, timer, log, metadata['counts'], args.max_payload_bytes)
                    except Exception as exc:
                        log({'event': 'connection_failed', 'peer': list(peer), 'error': str(exc),
                             'traceback': traceback.format_exc()})
                        try:
                            send_frame(conn, header('error', 'protocol-error', message=str(exc)[:512]),
                                       max_payload=args.max_payload_bytes)
                        except (OSError, ValueError):
                            pass
    except KeyboardInterrupt:
        metadata['status'] = 'stopped'
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        save_json(output / 'metadata.json', metadata)


if __name__ == '__main__':
    main()
