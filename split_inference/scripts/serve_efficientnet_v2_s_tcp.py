"""Single-session, sequential official pretrained suffix server (binary TCP v2)."""
import os
os.environ['TORCH_ALLOW_TF32_CUBLAS_OVERRIDE'] = '0'
os.environ['NVIDIA_TF32_OVERRIDE'] = '0'
import argparse
import csv
import math
from pathlib import Path
import signal
import socket
import time
import traceback

import torch
from split_inference.src.common import split_tensor_protocol as wire
from split_inference.src.common.efficientnet_v2_s_pretrained_runtime import (
    EfficientNetV2SPartitions, GpuTimer, load_official, from_bytes, to_bytes,
    check_tensor, snapshot, write_json,
)

FIELDS = ['request_id', 'split_point', 'expected_payload_bytes', 'actual_payload_bytes',
          'receive_complete_monotonic_ns', 'deserialize_ms', 'h2d_wall_ms', 'suffix_gpu_ms',
          'logits_d2h_serialization_ms', 'response_payload_bytes', 'response_wire_bytes',
          'request_payload_sha256', 'response_payload_sha256', 'success', 'error']


def serve(conn, parts, identity, timer, writer, metadata, maximum, verify_payload):
    hello = wire.recv_frame(conn, maximum)
    wire.match_response(hello, wire.Kind.HELLO, 0)
    wire.require(hello.payload == identity, 'model/group identity mismatch before inference')
    wire.send_frame(conn, wire.control_header(wire.Kind.READY), identity, maximum)
    metadata['handshakes'] += 1
    last_id = 0
    with torch.inference_mode():
        while True:
            row = dict.fromkeys(FIELDS, '')
            row['success'] = False
            try:
                frame = wire.recv_frame(conn, maximum)
                received = time.monotonic_ns()
                h = frame.header
                if h.kind == wire.Kind.CLOSE:
                    wire.require(h.request_id > last_id, 'close request ID must increase')
                    wire.send_frame(conn, wire.control_header(wire.Kind.BYE, h.request_id), max_payload=maximum)
                    metadata['shutdown'] = 'CLOSE/BYE'
                    return
                wire.require(h.kind == wire.Kind.INFER, 'expected inference request')
                row.update(request_id=h.request_id, split_point=h.point,
                           expected_payload_bytes=4 * math.prod(wire.SHAPES[h.point]),
                           actual_payload_bytes=len(frame.payload), receive_complete_monotonic_ns=received,
                           request_payload_sha256=frame.digest.hex())
                wire.require(h.request_id > last_id, 'request IDs must strictly increase')
                wire.require(bool(h.flags & wire.SHA256_FLAG) == verify_payload, 'payload verification mode mismatch')
                last_id = h.request_id
                start = time.monotonic_ns()
                cpu = from_bytes(frame.payload, h.shape)
                row['deserialize_ms'] = (time.monotonic_ns() - start) / 1e6
                start = time.monotonic_ns()
                activation = cpu.cuda()
                torch.cuda.synchronize()
                row['h2d_wall_ms'] = (time.monotonic_ns() - start) / 1e6
                logits, row['suffix_gpu_ms'] = timer.run(lambda: parts.suffix(activation, h.point))
                start = time.monotonic_ns()
                check_tensor(logits, 9)
                payload = to_bytes(logits)
                reply = wire.tensor_header(wire.Kind.RESULT, h.request_id, h.point, verify_payload)
                response = wire.encode(reply, payload, maximum)
                row['logits_d2h_serialization_ms'] = (time.monotonic_ns() - start) / 1e6
                row.update(response_payload_bytes=len(payload), response_wire_bytes=len(response),
                           response_payload_sha256=response[-32:].hex() if verify_payload else '')
                conn.sendall(response)  # No server time/queue/service telemetry on the wire.
                row['success'] = True
                metadata['network_requests'] += 1
                writer.writerow(row)
            except wire.PeerClosed:
                metadata['shutdown'] = 'peer EOF at frame boundary'
                return
            except BaseException as exc:
                row['error'] = str(exc)
                writer.writerow(row)
                metadata['failed_requests'] += 1
                # Invalid/truncated frames terminate the connection; no resync/retry/fallback.
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True, help='Existing torch hub directory containing checkpoints/')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=50051)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--max-payload-bytes', type=int, default=wire.MAX_PAYLOAD)
    parser.add_argument('--verify-payload', action='store_true', help='Smoke-only SHA-256 trailers (off by default)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile-mode', choices=['formal', 'pilot'], help='Opt-in offline latency profiling; default smoke unchanged')
    parser.add_argument('--profile-run-id', help='Same run ID on profiling Client and Server')
    args = parser.parse_args()
    wire.require(0 <= args.port <= 65535, 'port range')
    if args.profile_mode is not None:
        from split_inference.src.common.efficientnet_v2_s_profile_runtime import serve_profile
        serve_profile(args)
        return
    wire.validate(wire.control_header(wire.Kind.CLOSE), args.max_payload_bytes)
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {'status': 'starting', 'network_requests': 0, 'failed_requests': 0, 'connections': 0,
                'handshakes': 0, 'model_loads': 0, 'concurrency': 1, 'retries': 0, 'fallback': False,
                'verify_payload': args.verify_payload, 'server_telemetry': 'local CSV only'}
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        model, identity, model_info = load_official(args.cache)
        metadata.update(model=model_info, environment=snapshot(), model_loads=1)
        parts, timer = EfficientNetV2SPartitions(model), GpuTimer()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener, \
                (args.output / 'server_raw.csv').open('x', newline='', buffering=1) as log:
            wire.configure_socket(listener, args.timeout)
            listener.bind((args.host, args.port))
            listener.listen(1)
            metadata['address'] = list(listener.getsockname())
            writer = csv.DictWriter(log, fieldnames=FIELDS)
            writer.writeheader()
            write_json(args.output / 'ready.json', {'address': metadata['address']})
            print('READY', metadata['address'], flush=True)
            conn, peer = listener.accept()
            with conn:
                metadata['connections'] = 1
                metadata['peer'] = list(peer)
                wire.configure_socket(conn, args.timeout)
                serve(conn, parts, identity, timer, writer, metadata, args.max_payload_bytes, args.verify_payload)
        metadata['status'] = 'passed'
        print('SERVER_SESSION_PASS', metadata['network_requests'], flush=True)
    except KeyboardInterrupt:
        metadata.update(status='stopped', shutdown='signal')
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        write_json(args.output / 'server_manifest.json', metadata)


if __name__ == '__main__':
    main()
