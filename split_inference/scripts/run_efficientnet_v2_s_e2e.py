"""Thor-side CUDA prefix client with directly timed E2E wall-clock samples."""

import argparse
import csv
import math
from pathlib import Path
import socket
import time
import traceback
import uuid

import torch

from split_inference.src.common.efficientnet_v2_s_runtime import (
    ROOT, EfficientNetV2SPartitions, GpuTimer, from_bytes, load_model, new_output,
    save_json, snapshot, to_bytes,
)
from split_inference.src.common.tcp_protocol import (
    DEFAULT_MAX_PAYLOAD, check_identity, header, recv_frame, require, send_frame,
)

SERVER_TIMES = ('server_receive_ms', 'server_deserialize_h2d_ms', 'server_suffix_gpu_ms',
                'server_response_serialize_d2h_ms', 'server_response_send_ms')
FIELDS = ['request_id', 'phase', 'sample', 'partition_point', 'prefix_gpu_ms',
          'activation_serialize_d2h_ms', 'request_send_ms', *SERVER_TIMES,
          'response_wait_receive_ms', 'response_active_receive_ms', 'response_deserialize_ms',
          'e2e_wall_ms', 'failure_elapsed_ms', 'max_abs_diff', 'max_rel_diff', 'output_shape',
          'success', 'error']


def handshake(sock, identity, max_payload):
    request_id = uuid.uuid4().hex
    send_frame(sock, header('hello', request_id, **identity), max_payload=max_payload)
    reply, _, _ = recv_frame(sock, max_payload)
    require(reply['kind'] == 'ready', reply.get('message', 'handshake rejected'))
    require(reply['request_id'] == request_id, 'handshake ID mismatch')
    check_identity(reply, identity)


def receive(sock, kind, request_id, point, identity, max_payload):
    h, payload, duration = recv_frame(sock, max_payload)
    require(h['kind'] == kind, h.get('message', 'unexpected response kind'))
    require(h['request_id'] == request_id and h['partition_point'] == point, 'response ID/point mismatch')
    check_identity(h, identity)
    return h, payload, duration


def run(args, output, metadata):
    model, identity = load_model(args.state_dict)
    partitions = EfficientNetV2SPartitions(model)
    timer = GpuTimer()
    metadata.update(identity=identity, environment=snapshot())
    sock = None
    try:
        if any(p < 9 for p in args.partitions):
            sock = socket.create_connection((args.host, args.port), timeout=args.timeout)
            sock.settimeout(args.timeout)
            handshake(sock, identity, args.max_payload_bytes)
            metadata['handshake'] = 'passed before any forward/prefix/suffix inference'
        else:
            metadata['handshake'] = 'not applicable: P9-only, no socket created'
        # Only after matching hashes, prepare the fixed input and reference.
        torch.manual_seed(args.input_seed)
        with torch.inference_mode(), (output / 'requests.csv').open('x', newline='', buffering=1) as f:
            x = torch.randn(1, 3, 384, 384, dtype=torch.float32, device='cuda')
            reference = model(x).cpu()
            require(list(reference.shape) == [1, 1000] and torch.isfinite(reference).all().item(), 'reference output')
            torch.cuda.synchronize()
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for point in args.partitions:
                for phase, count in [('warmup', args.warmup), ('measurement', args.requests_per_point)]:
                    for sample in range(count):
                        request_id = uuid.uuid4().hex
                        row = dict.fromkeys(FIELDS, '')
                        row.update(request_id=request_id, phase=phase, sample=sample,
                                   partition_point=f'P{point}', success=False)
                        # Input is already prepared and GPU-ready. Reference is outside this interval.
                        torch.cuda.synchronize()
                        start = time.monotonic_ns()
                        try:
                            if point == 9:
                                logits, row['prefix_gpu_ms'] = timer.run(lambda: partitions.prefix(x, 9))
                                row['e2e_wall_ms'] = (time.monotonic_ns() - start) / 1e6
                                for name in ('activation_serialize_d2h_ms', 'request_send_ms', *SERVER_TIMES,
                                             'response_wait_receive_ms', 'response_active_receive_ms', 'response_deserialize_ms'):
                                    row[name] = 0.0  # Defined absent work, no network measurement.
                                logits = logits.cpu()
                            else:
                                if point == 0:
                                    activation, row['prefix_gpu_ms'] = x, 0.0
                                else:
                                    activation, row['prefix_gpu_ms'] = timer.run(lambda: partitions.prefix(x, point))
                                stage = time.monotonic_ns()
                                payload = to_bytes(activation)
                                row['activation_serialize_d2h_ms'] = (time.monotonic_ns() - stage) / 1e6
                                request = header('infer', request_id, point, phase=phase, **identity)
                                row['request_send_ms'] = send_frame(sock, request, payload, args.max_payload_bytes)
                                stage = time.monotonic_ns()
                                _, payload, row['response_active_receive_ms'] = receive(
                                    sock, 'result', request_id, point, identity, args.max_payload_bytes)
                                received = time.monotonic_ns()
                                row['response_wait_receive_ms'] = (received - stage) / 1e6
                                row['e2e_wall_ms'] = (received - start) / 1e6
                                stage = time.monotonic_ns()
                                logits = from_bytes(payload, [1, 1000])
                                row['response_deserialize_ms'] = (time.monotonic_ns() - stage) / 1e6
                                trailer, _, _ = receive(sock, 'timings', request_id, point, identity, args.max_payload_bytes)
                                timings = trailer.get('timings')
                                require(type(timings) is dict, 'missing server timings')
                                for name in SERVER_TIMES:
                                    v = timings.get(name)
                                    require(type(v) in (int, float) and math.isfinite(v) and v >= 0,
                                            'invalid server timing: ' + name)
                                    row[name] = v
                            row['output_shape'] = str(list(logits.shape))
                            diff = (logits - reference).abs()
                            row['max_abs_diff'] = diff.max().item()
                            row['max_rel_diff'] = (diff / reference.abs().clamp_min(1e-8)).max().item()
                            torch.testing.assert_close(logits, reference, rtol=1e-5, atol=1e-6)
                            for name in FIELDS:
                                if name.endswith('_ms') and row[name] != '':
                                    require(math.isfinite(row[name]) and row[name] >= 0, 'invalid sample timing')
                            row['success'] = True
                        except BaseException as exc:
                            row['error'] = str(exc)
                            row['failure_elapsed_ms'] = (time.monotonic_ns() - start) / 1e6
                            raise
                        finally:
                            writer.writerow(row)
                        print(f"{phase} P{point} sample {sample}: PASS", flush=True)
    finally:
        if sock is not None:
            sock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dict', type=Path, required=True)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=50051)
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('--max-payload-bytes', type=int, default=DEFAULT_MAX_PAYLOAD)
    p.add_argument('--partitions', default='0,1,2,3,4,5,6,7,8,9')
    p.add_argument('--warmup', type=int, default=1)
    p.add_argument('--requests-per-point', type=int, default=1)
    p.add_argument('--input-seed', type=int, default=0)
    p.add_argument('--output-root', type=Path, default=ROOT / 'split_inference/results/e2e_requests')
    args = p.parse_args()
    args.partitions = [int(v) for v in args.partitions.split(',')]
    require(args.partitions and len(set(args.partitions)) == len(args.partitions)
            and all(0 <= i <= 9 for i in args.partitions), 'partitions must be unique P0-P9 indices')
    require(args.warmup >= 1 and args.requests_per_point >= 1, 'warmup and request counts must be positive')
    require(0 < args.timeout < float('inf') and 0 <= args.port <= 65535, 'timeout/port')
    require(0 < args.max_payload_bytes <= 64 * 1024 * 1024, 'max payload limit')
    output = new_output(args.output_root, 'client_')
    metadata = {'status': 'running', 'args': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                'input': 'seeded CUDA torch.randn [1,3,384,384], FP32; no dataset download',
                'state': 'explicit local state_dict, no pretrained download',
                'rtol': 1e-5, 'atol': 1e-6, 'relative_error_floor': 1e-8,
                'timing': 'single client monotonic clock: GPU input ready to logits frame received; P9 ends at local GPU logits ready',
                'caveat': 'components overlap; response_wait_receive_ms includes server execution; no one-way network latency claim',
                'provenance': 'direct observations; warmup rows separate; P0 prefix and P9 network zeros are defined absent work'}
    print('RESULT_DIRECTORY=' + str(output), flush=True)
    try:
        run(args, output, metadata)
        metadata['status'] = 'passed'
        print('E2E_REQUESTS_PASS', flush=True)
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        save_json(output / 'metadata.json', metadata)


if __name__ == '__main__':
    main()
