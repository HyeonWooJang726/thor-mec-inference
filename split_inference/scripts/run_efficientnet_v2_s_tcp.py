"""Official-image prefix client: persistent FP32 binary TCP, P9 local-only."""
import os
os.environ['TORCH_ALLOW_TF32_CUBLAS_OVERRIDE'] = '0'
os.environ['NVIDIA_TF32_OVERRIDE'] = '0'
import argparse
import csv
from pathlib import Path
import socket
import time
import traceback

import torch
from split_inference.src.common import split_tensor_protocol as wire
from split_inference.src.common.efficientnet_v2_s_pretrained_runtime import (
    EfficientNetV2SPartitions, GpuTimer, load_official, selected_input, to_bytes,
    from_bytes, check_tensor, snapshot, write_json, SELECTION_HASH, EVIDENCE_HASH,
)

from split_inference.src.common.image_evidence_metadata import image_metadata

CORRECT = ['sample_id', 'member', 'request_id', 'split_point', 'output_shape', 'finite',
           'top1', 'reference_top1', 'top1_matches', 'max_abs_error', 'mean_abs_error',
           'max_rel_error', 'assert_close_passed', 'error']
FIELDS = ['sample_id', 'member', 'request_id', 'split_point', 'activation_shape', 'payload_bytes',
          'request_wire_bytes', 'prefix_gpu_ms', 'activation_d2h_materialization_ms',
          'request_response_wall_ms', 'response_deserialize_ms', 'e2e_wall_ms',
          'local_logits_d2h_ms', 'response_payload_bytes', 'response_wire_bytes',
          'preprocess_wall_ms', 'network_used', 'request_payload_sha256', 'response_payload_sha256',
          'success', 'error']


def correctness(logits, reference, row):
    row['output_shape'] = str(list(logits.shape))
    row['finite'] = bool(torch.isfinite(logits).all().item())
    wire.require(tuple(logits.shape) == wire.LOGITS_SHAPE and row['finite'], 'invalid logits')
    delta = (logits - reference).abs()
    row.update(top1=logits.argmax(1).item(), reference_top1=reference.argmax(1).item(),
               top1_matches=bool(torch.equal(logits.argmax(1), reference.argmax(1))),
               max_abs_error=delta.max().item(), mean_abs_error=delta.mean().item(),
               max_rel_error=(delta / reference.abs().clamp_min(1e-8)).max().item())
    torch.testing.assert_close(logits, reference, rtol=1e-4, atol=1e-5)
    row['assert_close_passed'] = True


def run(args, metadata):
    model, identity, model_info = load_official(args.cache)
    parts, timer = EfficientNetV2SPartitions(model), GpuTimer()
    metadata.update(model=model_info, environment=snapshot(), model_loads=1)
    sock = None
    rid = 0
    try:
        if any(p < 9 for p in args.partitions):
            sock = socket.create_connection((args.host, args.port), timeout=args.timeout)
            wire.configure_socket(sock, args.timeout)
            metadata['connections'] = 1
            wire.send_frame(sock, wire.control_header(wire.Kind.HELLO), identity, args.max_payload_bytes)
            ready = wire.recv_frame(sock, args.max_payload_bytes)
            wire.match_response(ready, wire.Kind.READY, 0)
            wire.require(ready.payload == identity, 'model/group identity mismatch before inference')
            metadata['handshake'] = 'passed before any inference'
        else:
            metadata['handshake'] = 'P9-only: no socket created'
        with torch.inference_mode(), \
                (args.output / 'client_raw.csv').open('x', newline='', buffering=1) as cf, \
                (args.output / 'correctness.csv').open('x', newline='', buffering=1) as vf:
            writer, checks = csv.DictWriter(cf, fieldnames=FIELDS), csv.DictWriter(vf, fieldnames=CORRECT)
            writer.writeheader()
            checks.writeheader()
            for sid in args.sample_ids:
                prep = time.monotonic_ns()
                cpu, member, evidence = selected_input(args.zip, sid)
                preprocess_ms = (time.monotonic_ns() - prep) / 1e6
                metadata['images'].append(image_metadata(sid, evidence))
                x = cpu.cuda()
                torch.cuda.synchronize()  # Input GPU-ready, outside every E2E interval.
                reference = model(x).cpu()
                check_tensor(reference, 9)
                for point in args.partitions:
                    rid += 1
                    common = dict(sample_id=sid, member=member, request_id=rid, split_point=point)
                    row = dict.fromkeys(FIELDS, '')
                    row.update(common, success=False, preprocess_wall_ms=preprocess_ms, network_used=point < 9)
                    check = dict.fromkeys(CORRECT, '')
                    check.update(common, assert_close_passed=False)
                    torch.cuda.synchronize()
                    start = time.monotonic_ns()
                    try:
                        if point == 9:
                            logits, row['prefix_gpu_ms'] = timer.run(lambda: parts.prefix(x, 9))
                            stage = time.monotonic_ns()
                            logits = logits.cpu().contiguous()
                            row['local_logits_d2h_ms'] = (time.monotonic_ns() - stage) / 1e6
                            row['e2e_wall_ms'] = (time.monotonic_ns() - start) / 1e6
                            row.update(activation_shape=str(list(wire.SHAPES[9])), payload_bytes=0,
                                       request_wire_bytes=0, activation_d2h_materialization_ms=0,
                                       request_response_wall_ms=0, response_deserialize_ms=0,
                                       response_payload_bytes=0, response_wire_bytes=0)
                            metadata['local_only_executions'] += 1
                        else:
                            if point == 0:
                                activation, row['prefix_gpu_ms'] = x, 0.0  # Identity; no CUDA work.
                            else:
                                activation, row['prefix_gpu_ms'] = timer.run(lambda: parts.prefix(x, point))
                            stage = time.monotonic_ns()
                            check_tensor(activation, point)
                            payload = to_bytes(activation)
                            request = wire.tensor_header(wire.Kind.INFER, rid, point, args.verify_payload)
                            encoded = wire.encode(request, payload, args.max_payload_bytes)
                            row['activation_d2h_materialization_ms'] = (time.monotonic_ns() - stage) / 1e6
                            row.update(activation_shape=str(list(activation.shape)), payload_bytes=len(payload),
                                       request_wire_bytes=len(encoded), request_payload_sha256=encoded[-32:].hex() if args.verify_payload else '')
                            sent = time.monotonic_ns()
                            sock.sendall(encoded)
                            frame = wire.recv_frame(sock, args.max_payload_bytes)
                            received = time.monotonic_ns()
                            row['request_response_wall_ms'] = (received - sent) / 1e6
                            wire.match_response(frame, wire.Kind.RESULT, rid, point)
                            wire.require(bool(frame.header.flags & wire.SHA256_FLAG) == args.verify_payload, 'response integrity mode')
                            stage = time.monotonic_ns()
                            logits = from_bytes(frame.payload, frame.header.shape)
                            row['response_deserialize_ms'] = (time.monotonic_ns() - stage) / 1e6
                            row['e2e_wall_ms'] = (time.monotonic_ns() - start) / 1e6
                            row.update(response_payload_bytes=len(frame.payload), response_wire_bytes=wire.HEADER.size + len(frame.payload) + len(frame.digest),
                                       response_payload_sha256=frame.digest.hex(), local_logits_d2h_ms=0)
                            metadata['network_requests'] += 1
                        # Accuracy checks are outside the inference-ready -> restored CPU logits interval.
                        correctness(logits, reference, check)
                        row['success'] = True
                        print(f'SMOKE sample={sid} P{point} PASS', flush=True)
                    except BaseException as exc:
                        row['error'] = check['error'] = str(exc)
                        metadata['failed_executions'] += 1
                        raise
                    finally:
                        writer.writerow(row)
                        checks.writerow(check)
        if sock is not None:
            wire.close_session(sock, rid + 1, args.max_payload_bytes)
            metadata['shutdown'] = 'CLOSE/BYE'
    finally:
        if sock is not None:
            sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=50051)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--sample-ids', default='0,149,299')
    parser.add_argument('--partitions', default='0,1,2,3,4,5,6,7,8,9')
    parser.add_argument('--max-payload-bytes', type=int, default=wire.MAX_PAYLOAD)
    parser.add_argument('--verify-payload', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.sample_ids = [int(x) for x in args.sample_ids.split(',')]
    args.partitions = [int(x) for x in args.partitions.split(',')]
    wire.require(args.sample_ids and len(set(args.sample_ids)) == len(args.sample_ids) and all(0 <= x < 300 for x in args.sample_ids), 'unique sample IDs 0..299')
    wire.require(args.partitions and len(set(args.partitions)) == len(args.partitions) and all(0 <= x <= 9 for x in args.partitions), 'unique split points 0..9')
    wire.require(0 < args.port <= 65535 and 0 < args.timeout < float('inf'), 'port/timeout')
    wire.validate(wire.control_header(wire.Kind.CLOSE), args.max_payload_bytes)
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {'status': 'running', 'connections': 0, 'network_requests': 0, 'local_only_executions': 0,
                'model_loads': 0, 'failed_executions': 0, 'retries': 0, 'fallback': False, 'images': [],
                'sample_ids': args.sample_ids, 'partitions': args.partitions, 'verify_payload': args.verify_payload,
                'selection_sha256': SELECTION_HASH, 'evidence_sha256': EVIDENCE_HASH, 'rtol': 1e-4, 'atol': 1e-5,
                'relative_error_floor': 1e-8, 'input_ready_definition': 'preprocessed tensor already on GPU and synchronized',
                'e2e_end': 'full FP32 CPU logits restored, before correctness checks',
                'scope': 'functional TCP bring-up; localhost shared-GPU timings are not performance results'}
    try:
        run(args, metadata)
        metadata['status'] = 'passed'
        print('CLIENT_CORRECTNESS_PASS', flush=True)
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        write_json(args.output / 'client_manifest.json', metadata)


if __name__ == '__main__':
    main()
