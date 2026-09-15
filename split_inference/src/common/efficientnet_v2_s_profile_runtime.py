"""Opt-in profiling runtime; the existing smoke and ESFP wire stay unchanged."""
from collections import Counter
from contextlib import redirect_stderr
from datetime import datetime, timezone
import csv
import ipaddress
from itertools import groupby
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import traceback

import torch
from . import split_tensor_protocol as wire
from . import split_latency_profile as data
from .efficientnet_v2_s_pretrained_runtime import (
    ROOT, DOC, EfficientNetV2SPartitions, load_official, selected_input,
    check_tensor, to_bytes, from_bytes, snapshot, write_json,
)
from .image_evidence_metadata import image_metadata
from split_inference.scripts.run_efficientnet_v2_s_tcp import correctness


class WallCudaTimer:
    """Caller records wall boundaries; event queries happen after that interval."""
    def __init__(self):
        self.start = torch.cuda.Event(enable_timing=True)
        self.end = torch.cuda.Event(enable_timing=True)
        self.start.record()
        self.end.record()
        self.end.synchronize()

    def run(self, operation):
        self.start.record()
        result = operation()
        self.end.record()
        self.end.synchronize()
        return result

    def elapsed(self):
        return data.milliseconds(self.start.elapsed_time(self.end), 'CUDA Event')


def source_hashes():
    names = ['src/common/split_tensor_protocol.py', 'src/common/efficientnet_v2_s_partitions.py',
             'src/common/efficientnet_v2_s_runtime.py', 'src/common/efficientnet_v2_s_pretrained_runtime.py',
             'src/common/image_evidence_metadata.py', 'src/common/split_latency_profile.py',
             'src/common/efficientnet_v2_s_profile_runtime.py', 'scripts/run_efficientnet_v2_s_tcp.py',
             'scripts/profile_efficientnet_v2_s_tcp.py', 'scripts/serve_efficientnet_v2_s_tcp.py',
             'scripts/profile_efficientnet_v2_s_imagenet.py']
    return {name: data.sha(ROOT / 'split_inference' / name) for name in names}


def observed_settings():
    def read(path):
        try:
            return {'value': path.read_text().strip(), 'path': str(path)}
        except OSError as exc:
            return {'unavailable': str(exc), 'path': str(path)}
    settings = {'changes_by_profiler': 'none'}
    try:
        p = subprocess.run(['nvpmodel', '-q'], capture_output=True, text=True, timeout=10)
        settings['power_mode'] = {'command': ['nvpmodel', '-q'], 'exit_code': p.returncode,
                                  'stdout': p.stdout, 'stderr': p.stderr}
        if p.returncode:
            settings['power_mode']['unavailable'] = 'read-only query failed; no sudo attempted'
    except (OSError, subprocess.TimeoutExpired) as exc:
        settings['power_mode'] = {'unavailable': str(exc)}
    settings['cpu_clock'] = {str(p): read(p) for p in Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_cur_freq')}
    if not settings['cpu_clock']:
        settings['cpu_clock'] = {'unavailable': 'cpufreq scaling_cur_freq files not exposed'}
    settings['emc_clock'] = read(Path('/sys/kernel/debug/bpmp/debug/clk/emc/rate'))
    settings['gpu_power_and_clocks'] = 'nvidia-smi -q in environment snapshot; unavailable fields retained verbatim'
    return settings


class StderrTee:
    def __init__(self, file):
        self.file, self.outer = file, sys.stderr

    def write(self, text):
        self.file.write(text)
        self.file.flush()
        return self.outer.write(text)

    def flush(self):
        self.file.flush()
        self.outer.flush()


def execute(args, role, operation):
    cfg = data.config(args.profile_mode, args.profile_run_id)
    data.require(args.verify_payload, 'profiling requires explicit --verify-payload')
    data.require(0 < args.timeout < float('inf'), 'finite positive timeout required')
    if cfg['mode'] == 'pilot':
        data.require(ipaddress.ip_address(args.host).is_loopback, 'pilot is loopback-only')
    wire.validate(wire.control_header(wire.Kind.CLOSE), args.max_payload_bytes)
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {'role': role, 'status': 'running', 'config': cfg, 'scope': data.SCOPE,
                'provenance': 'measured', 'research_result': cfg['mode'] == 'formal',
                'connections': 0, 'handshakes': 0, 'model_loads': 0, 'failed_requests': 0,
                'retries': 0, 'fallback': False, 'phase_counts': {}, 'source_sha256': source_hashes(),
                'argv': sys.argv, 'executable': sys.executable, 'host': args.host, 'port': args.port,
                'timeout_seconds': args.timeout, 'max_payload_bytes': args.max_payload_bytes,
                'correctness_tolerance': {'rtol': 1e-4, 'atol': 1e-5},
                'started_utc': datetime.now(timezone.utc).isoformat(),
                'wall_clock': dict(name='time.perf_counter_ns', **vars(time.get_clock_info('perf_counter'))),
                'timing': {'primary': 'synchronized local wall durations', 'cuda_event': 'auxiliary only',
                    'device_wall': 'inference-ready GPU input through device DNN completion synchronization',
                    'remote_roundtrip': 'device activation ready through verified deserialized CPU FP32 logits',
                    'edge_wall': 'H2D synchronized activation through edge DNN completion synchronization',
                    'offloading_overhead': 'remote_roundtrip_ms minus edge_inference_wall_ms; not pure network latency',
                    'e2e': 'inference-ready GPU input through final CPU FP32 logits; preprocessing excluded'},
                'p99_interpretation': 'descriptive per-split samples; no independent-environment tail guarantee or confidence interval'}
    def stop(signum, _frame):
        raise InterruptedError(f'signal {signum}; no retry')
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with (args.output / 'stderr.log').open('x') as stderr, redirect_stderr(StderrTee(stderr)):
            try:
                operation(args, metadata)
                data.require(metadata['phase_counts'] == data.counts(cfg, network=role == 'server'), 'incomplete phase counts')
                data.require(metadata.get('shutdown') == 'CLOSE/BYE', 'missing normal shutdown')
                metadata['status'] = 'passed'
            except BaseException:
                metadata.update(status='failed', error=traceback.format_exc())
                traceback.print_exc()
                write_json(args.output / 'failure_manifest.json', metadata)
                raise
    finally:
        metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(args.output / 'run_manifest.json', metadata)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def load(args, metadata):
    model, identity, info = load_official(args.cache)
    actual = {k: info[k] for k in ['canonical_sha256', 'checkpoint_sha256', 'manifest_sha256', 'partitions_sha256']}
    actual.update(selection_sha256=data.sha(DOC / 'selected_imagenet_members.txt'),
                  evidence_sha256=data.sha(DOC / 'selected_image_evidence.csv'))
    data.require(actual == data.IDENTITY, 'official model/data/group identity changed')
    metadata.update(identity=actual, model=info, model_loads=1, environment=snapshot(),
                    observed_settings=observed_settings())
    return model, EfficientNetV2SPartitions(model), identity, WallCudaTimer()


def csv_writer(file, fields):
    writer = csv.DictWriter(file, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    return writer


def serve_profile(args):
    execute(args, 'server', server_session)


def server_session(args, metadata):
    _model, parts, identity, timer = load(args, metadata)
    plan = list(data.schedule(metadata['config']))
    phase_counts = Counter()
    with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False), \
            (args.output / 'server_raw.csv').open('x', newline='', buffering=1) as file, \
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        writer = csv_writer(file, data.SERVER_FIELDS)
        wire.configure_socket(listener, args.timeout)
        listener.bind((args.host, args.port))
        listener.listen(1)
        metadata['address'] = list(listener.getsockname())
        write_json(args.output / 'ready.json', {'address': metadata['address'], 'run_id': metadata['config']['run_id']})
        print('READY', metadata['address'], flush=True)
        conn, peer = listener.accept()
        with conn:
            metadata.update(connections=1, peer=list(peer))
            wire.configure_socket(conn, args.timeout)
            hello = wire.recv_frame(conn, args.max_payload_bytes)
            wire.match_response(hello, wire.Kind.HELLO, 0)
            wire.require(hello.payload == identity, 'model/group identity mismatch')
            wire.send_frame(conn, wire.control_header(wire.Kind.READY), identity, args.max_payload_bytes)
            metadata['handshakes'] = 1
            for planned in plan:
                if planned['split_point'] == 9:
                    continue
                row = dict.fromkeys(data.SERVER_FIELDS, data.NA)
                row.update(planned, success=False, error='')
                metadata['active_request'] = planned
                try:
                    frame = wire.recv_frame(conn, args.max_payload_bytes)
                    h = frame.header
                    wire.match_response(frame, wire.Kind.INFER, planned['request_id'], planned['split_point'])
                    wire.require(h.flags == wire.SHA256_FLAG, 'mandatory SHA-256 trailer missing')
                    row.update(activation_shape=json.dumps(list(h.shape)), payload_bytes=len(frame.payload),
                               request_payload_sha256=frame.digest.hex())
                    cpu = from_bytes(frame.payload, h.shape)
                    activation = cpu.cuda()
                    torch.cuda.synchronize()  # H2D is offloading overhead, outside edge-side DNN time.
                    started = time.perf_counter_ns()
                    logits = timer.run(lambda: parts.suffix(activation, h.point))
                    finished = time.perf_counter_ns()
                    row['edge_inference_wall_ms'] = data.milliseconds((finished - started) / 1e6, 'edge wall')
                    row['edge_inference_cuda_ms'] = timer.elapsed()
                    check_tensor(logits, 9)
                    payload = to_bytes(logits)
                    reply = wire.tensor_header(wire.Kind.RESULT, h.request_id, h.point, True)
                    encoded = wire.encode(reply, payload, args.max_payload_bytes)
                    row.update(output_shape=json.dumps(list(logits.shape)), response_payload_bytes=len(payload),
                               response_payload_sha256=encoded[-32:].hex())
                    conn.sendall(encoded)  # Unmodified RESULT: status + logits, no timing telemetry.
                    row['success'] = True
                    phase_counts[planned['phase']] += 1
                    metadata['phase_counts'] = dict(phase_counts)
                except BaseException as exc:
                    row['error'] = str(exc)
                    metadata['failed_requests'] += 1
                    raise
                finally:
                    writer.writerow(row)
            close = wire.recv_frame(conn, args.max_payload_bytes)
            wire.match_response(close, wire.Kind.CLOSE, len(plan) + 1)
            wire.send_frame(conn, wire.control_header(wire.Kind.BYE, len(plan) + 1), max_payload=args.max_payload_bytes)
            metadata['shutdown'] = 'CLOSE/BYE'
    print('SERVER_PROFILE_PASS', dict(phase_counts), flush=True)


def client_session(args, metadata):
    model, parts, identity, timer = load(args, metadata)
    plan = list(data.schedule(metadata['config']))
    phase_counts, images = Counter(), {}
    with socket.create_connection((args.host, args.port), timeout=args.timeout) as conn, \
            torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False), \
            (args.output / 'client_raw.csv').open('x', newline='', buffering=1) as raw, \
            (args.output / 'correctness.csv').open('x', newline='', buffering=1) as checks:
        writer, checker = csv_writer(raw, data.CLIENT_FIELDS), csv_writer(checks, data.CORRECT_FIELDS)
        wire.configure_socket(conn, args.timeout)
        metadata['connections'] = 1
        wire.send_frame(conn, wire.control_header(wire.Kind.HELLO), identity, args.max_payload_bytes)
        ready = wire.recv_frame(conn, args.max_payload_bytes)
        wire.match_response(ready, wire.Kind.READY, 0)
        wire.require(ready.payload == identity, 'model/group identity mismatch')
        metadata['handshakes'] = 1
        key = lambda p: (p['phase'], p['round'], p['iteration'], p['sample_id'])
        for (phase, round_id, _iteration, sid), requests in groupby(plan, key=key):
            metadata['active_input'] = {'phase': phase, 'round': round_id, 'sample_id': sid}
            cpu, _member, evidence = selected_input(args.zip, sid)
            images[sid] = image_metadata(sid, evidence)
            metadata['images'] = list(images.values())
            x = cpu.cuda()
            torch.cuda.synchronize()  # ZIP/decode/transform/input H2D excluded from every interval.
            reference = model(x).cpu().contiguous() if phase == 'preflight' else None
            if reference is not None:
                check_tensor(reference, 9)
            for planned in requests:
                point, rid = planned['split_point'], planned['request_id']
                row = dict.fromkeys(data.CLIENT_FIELDS, data.NA)
                row.update(planned, network_used=point < 9, success=False, error='',
                           activation_shape=json.dumps(list(wire.SHAPES[point])))
                check = dict.fromkeys(data.CORRECT_FIELDS, data.NA)
                check.update(planned, assert_close_passed=False, error='')
                metadata['active_request'] = planned
                try:
                    torch.cuda.synchronize()
                    if point == 0:
                        activation = x
                        start = activation_ready = time.perf_counter_ns()  # Identity; device DNN time is zero.
                    else:
                        start = time.perf_counter_ns()
                        activation = timer.run(lambda: parts.prefix(x, point))
                        activation_ready = time.perf_counter_ns()
                    if point == 9:
                        logits = activation.cpu().contiguous()
                        finished = time.perf_counter_ns()
                        row.update(payload_bytes=0, response_payload_bytes=0)
                    else:
                        check_tensor(activation, point)
                        payload = to_bytes(activation)
                        header = wire.tensor_header(wire.Kind.INFER, rid, point, True)
                        encoded = wire.encode(header, payload, args.max_payload_bytes)
                        conn.sendall(encoded)
                        frame = wire.recv_frame(conn, args.max_payload_bytes)
                        wire.match_response(frame, wire.Kind.RESULT, rid, point)
                        wire.require(frame.header.flags == wire.SHA256_FLAG, 'response SHA-256 trailer missing')
                        logits = from_bytes(frame.payload, frame.header.shape)
                        finished = time.perf_counter_ns()
                        row.update(payload_bytes=len(payload), request_payload_sha256=encoded[-32:].hex(),
                                   response_payload_bytes=len(frame.payload), response_payload_sha256=frame.digest.hex(),
                                   remote_roundtrip_ms=(finished - activation_ready) / 1e6)
                    # All row bookkeeping, event queries, correctness and CSV I/O are outside E2E.
                    row.update(device_inference_wall_ms=(activation_ready - start) / 1e6,
                               device_inference_cuda_ms=0.0 if point == 0 else timer.elapsed(),
                               e2e_inference_ms=(finished - start) / 1e6, output_shape=json.dumps(list(logits.shape)))
                    check_tensor(logits, 9)
                    for name in ['device_inference_wall_ms', 'device_inference_cuda_ms', 'e2e_inference_ms'] + ([] if point == 9 else ['remote_roundtrip_ms']):
                        data.milliseconds(row[name], name)
                    if phase == 'preflight':
                        correctness(logits, reference, check)
                        data.require(check['top1_matches'], 'preflight top1 mismatch')
                    row['success'] = True
                    phase_counts[phase] += 1
                    metadata['phase_counts'] = dict(phase_counts)
                except BaseException as exc:
                    row['error'] = check['error'] = str(exc)
                    metadata['failed_requests'] += 1
                    raise
                finally:
                    writer.writerow(row)
                    if phase == 'preflight':
                        checker.writerow(check)
            if phase == 'measurement' and sid == metadata['config']['sample_ids'][-1]:
                print('MEASUREMENT_ROUND_COMPLETE', round_id, flush=True)
        wire.close_session(conn, len(plan) + 1, args.max_payload_bytes)
        metadata['shutdown'] = 'CLOSE/BYE'
    print('CLIENT_PROFILE_PASS', dict(phase_counts), flush=True)
