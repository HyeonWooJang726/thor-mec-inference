#!/usr/bin/env python3
"""Prerequisite only: local semantic replay and unchanged TCP baseline sender.

Stops if receiver unavailable. Does not deploy or start an Edge inference server.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
from raw640 import serialize, remaining_preprocess, PAYLOAD_BYTES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/edge_raw_capacity_gate'
for directory in ('common', 'local'):
    sys.path.insert(0, str(ROOT / 'scripts' / directory))
from rtdetr_preprocess import preprocess_bgr


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(name, value):
    with (OUT / name).open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def inventory():
    paths = []
    for rel in ('results/edge_payload_gate', 'results/local_capacity_characterization',
                'results/capacity_model_validity', 'paper/figures/local_capacity'):
        paths.extend(p for p in (ROOT / rel).rglob('*') if p.is_file())
    paths.extend(p for p in (ROOT / 'scripts').rglob('*') if p.is_file() and 'edge_raw_capacity_gate' not in p.parts)
    paths.append(ROOT / 'server/tensor_e2e_server.py')
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def semantic_check(samples):
    from profile_local_e2e import Gst, GstVideo, build_pipeline
    Gst.init(None)
    selected = [samples[(i * 399 + 14) // 29] for i in range(30)]
    rows, payloads, tensors = [], [], []
    for stream in range(8):
        wanted = {int(r['frame_index']): r for r in selected if int(r['stream_id']) == stream}
        source = next(iter(wanted.values()))
        pipeline, _, sink = build_pipeline(source['source_path'])
        try:
            assert pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE
            for index in range(max(wanted) + 1):
                sample = sink.emit('try-pull-sample', 10 * Gst.SECOND)
                if sample is None:
                    error = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                    raise RuntimeError(str(error.parse_error()) if error else 'missing decoded source frame')
                if index not in wanted:
                    continue
                info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                assert (info.width, info.height, info.finfo.name) == (1920, 1080, 'BGR')
                buffer = sample.get_buffer()
                assert int(buffer.pts) == int(wanted[index]['decoder_pts_ns'])
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                assert ok
                try:
                    frame = np.ndarray((1080, 1920, 3), np.uint8, buffer=mapped.data,
                                       strides=(info.stride[0], 3, 1)).copy()
                finally:
                    buffer.unmap(mapped)
                assert digest(frame.tobytes()) == wanted[index]['decoded_bgr_sha256']
                raw = serialize(frame)
                assert len(raw) == PAYLOAD_BYTES
                received_locally = np.frombuffer(raw, np.uint8).reshape(360, 640, 3).copy().tobytes()
                reference = preprocess_bgr(frame)
                replay = remaining_preprocess(received_locally)
                difference = np.abs(reference - replay)
                row = dict(sample_id=wanted[index]['sample_id'], stream_id=stream, frame_index=index,
                           payload_bytes=len(raw), sender_payload_sha256=digest(raw),
                           local_roundtrip_payload_sha256=digest(received_locally),
                           reference_tensor_sha256=digest(reference.tobytes()),
                           local_edge_tail_tensor_sha256=digest(replay.tobytes()),
                           max_abs_diff=float(difference.max()), mean_abs_diff=float(difference.mean()),
                           local_tensor_exact=np.array_equal(reference, replay),
                           edge_received_sha256='NOT_MEASURED', edge_tensor_sha256='NOT_MEASURED',
                           scope='LOCAL_REPLAY_ONLY')
                rows.append(row)
                payloads.append(np.frombuffer(raw, np.uint8).reshape(360, 640, 3).copy())
                tensors.append(row['reference_tensor_sha256'])
                assert row['local_tensor_exact'] and row['sender_payload_sha256'] == row['local_roundtrip_payload_sha256']
        finally:
            pipeline.set_state(Gst.State.NULL)
            pipeline.get_state(5 * Gst.SECOND)
        print('SEMANTIC_STREAM_PASS', stream, 'frames', len(wanted), flush=True)
    assert len(rows) == 30
    with (OUT / 'semantic_equivalence.csv').open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with (OUT / 'raw/semantic_raw640_30.npz').open('xb') as f:
        np.savez_compressed(f, raw640=np.stack(payloads), sample_ids=np.array([int(r['sample_id']) for r in rows]),
                            reference_tensor_sha256=np.array(tensors))
    return rows


def main():
    assert Path.cwd() == ROOT
    assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'rate-dvfs-gate'
    assert (OUT / 'EXPERIMENT_PLAN.md').is_file()
    assert not (OUT / 'verification.json').exists()
    (OUT / 'raw').mkdir(exist_ok=False)
    before = inventory()
    write_json('preservation_before.json', before)
    with (ROOT / 'results/edge_payload_gate/sample_manifest.csv').open() as f:
        samples = list(csv.DictReader(f))
    assert len(samples) == 400 and len({(r['source_path'], r['frame_index']) for r in samples}) == 400
    for p, expected in {(r['source_path'], r['source_sha256']) for r in samples}:
        assert sha(p) == expected, p
    command = [sys.executable, '-B', '-u', 'scripts/profile_tcp_throughput.py', '--mode', 'send',
               '--host', '192.168.0.7', '--port', '5001', '--runs', '3', '--total-bytes', '268435456',
               '--chunk-bytes', '1048576', '--interval-s', '2', '--csv', 'results/edge_raw_capacity_gate/tcp_sender.csv']
    write_json('input_manifest.json', dict(sample_manifest_sha256=sha(ROOT / 'results/edge_payload_gate/sample_manifest.csv'),
               source_hashes={r['source_path']: r['source_sha256'] for r in samples},
               semantic_sample_positions=[(i * 399 + 14) // 29 for i in range(30)],
               source_sha256={str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'scripts/edge_raw_capacity_gate').glob('*.py')},
               existing_tcp_script_sha256=sha(ROOT / 'scripts/profile_tcp_throughput.py'),
               plan_sha256=sha(OUT / 'EXPERIMENT_PLAN.md'), tcp_sender_command=command,
               timestamp_utc=datetime.now(timezone.utc).isoformat()))
    rows = semantic_check(samples)
    print('LOCAL_SEMANTIC_PASS_30; actual Edge receipt not yet verified', flush=True)
    start = datetime.now(timezone.utc).isoformat()
    with (OUT / 'raw/tcp_sender.log').open('x') as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        print('TCP_SENDER_PID', child.pid, flush=True)
        rc = child.wait()
    text = (OUT / 'raw/tcp_sender.log').read_text()
    print(text, flush=True)
    status = 'TCP_BASELINE_COMPLETE' if rc == 0 else 'WAITING_FOR_EDGE_TCP_RECEIVER'
    write_json('tcp_attempt.json', dict(start_utc=start, end_utc=datetime.now(timezone.utc).isoformat(),
               command=command, child_pid=child.pid, child_returncode=rc, status=status,
               completed_runs=text.count(' PASS bytes='), stdout_stderr_file='raw/tcp_sender.log'))
    after = inventory()
    assert before == after, 'existing artifact changed'
    write_json('verification.json', dict(status=status, local_semantic_equivalence='PASS', local_frames=len(rows),
               edge_received_payload_equivalence='NOT_MEASURED', edge_runtime_equivalence='NOT_MEASURED',
               tcp_returncode=rc, protected_file_count=len(before), existing_artifact_preservation='PASS',
               primary_planned=12, primary_completed=0, primary_valid=0, primary_invalid=0,
               edge_concurrency='NOT_MEASURED', primary_edge_concurrency=None,
               final_verdict='INCONCLUSIVE', hybrid_240fps_ready=False))
    with (OUT / 'edge_capacity_verdict.md').open('x') as f:
        f.write(f'# RAW640 Edge Residual-Capacity Gate\n\n{status}\n\n'
                'Final verdict: INCONCLUSIVE. Primary completed 0/12. No Edge concurrency measurement.\n\n'
                'Local semantic replay: 30/30 exact payload and final tensor hashes; zero max/mean absolute difference. '
                'Actual Edge receipt/tensor equivalence remains NOT_MEASURED.\n\n'
                'TCP evidence: raw/tcp_sender.log and tcp_attempt.json. No fabricated throughput CSV or unmeasured summaries.\n\n'
                'No integrated run or hybrid 240-FPS experiment was executed. Existing protected artifacts are byte-identical.\n')
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    with (OUT / 'final_git_status.txt').open('x') as f:
        f.write(subprocess.check_output(['git', 'status', '--short', '--branch'], cwd=ROOT, text=True, env=env))
    print(status, flush=True)


if __name__ == '__main__':
    main()
