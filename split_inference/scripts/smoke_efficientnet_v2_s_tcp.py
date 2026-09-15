"""Run protocol tests, then exactly three ImageNet samples over localhost TCP."""
import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from split_inference.src.common import split_tensor_protocol as wire

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / 'split_inference/results/split_e2e_loopback_smoke'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, data):
    with path.open('x') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def validate(out):
    client = read_csv(out / 'client/client_raw.csv')
    server = read_csv(out / 'server/server_raw.csv')
    checks = read_csv(out / 'client/correctness.csv')
    cm = json.loads((out / 'client/client_manifest.json').read_text())
    sm = json.loads((out / 'server/server_manifest.json').read_text())
    assert len(client) == len(checks) == 30 and len(server) == 27
    assert cm['status'] == sm['status'] == 'passed'
    assert cm['network_requests'] == sm['network_requests'] == 27
    assert cm['local_only_executions'] == 3 and cm['connections'] == sm['connections'] == sm['handshakes'] == 1
    assert cm['model_loads'] == sm['model_loads'] == 1
    assert cm['failed_executions'] == sm['failed_requests'] == 0
    assert cm['retries'] == sm['retries'] == 0 and not cm['fallback'] and not sm['fallback']
    assert cm['shutdown'] == sm['shutdown'] == 'CLOSE/BYE'
    assert cm['model']['canonical_sha256'] == sm['model']['canonical_sha256'] == 'dcac15dc687d43926f62a7942918dc73d11372abbb612352336b4d5840ca4710'
    expected = {(sid, point) for sid in [0,149,299] for point in range(10)}
    assert {(int(r['sample_id']), int(r['split_point'])) for r in client} == expected
    assert {(int(r['sample_id']), int(r['split_point'])) for r in checks} == expected
    assert len({r['request_id'] for r in client}) == 30
    sr = {r['request_id']: r for r in server}
    assert len(sr) == 27
    assert set(sr) == {r['request_id'] for r in client if int(r['split_point']) < 9}
    for row in client:
        point = int(row['split_point'])
        assert row['success'] == 'True' and not row['error']
        assert tuple(ast.literal_eval(row['activation_shape'])) == wire.SHAPES[point]
        for key, value in row.items():
            if key.endswith('_ms'):
                assert math.isfinite(float(value)) and float(value) >= 0
        if point == 9:
            assert row['network_used'] == 'False' and row['request_id'] not in sr
            assert all(int(row[key]) == 0 for key in ['payload_bytes','request_wire_bytes','response_payload_bytes','response_wire_bytes'])
        else:
            peer = sr[row['request_id']]
            assert row['network_used'] == peer['success'] == 'True' and not peer['error']
            assert int(peer['split_point']) == point
            size = math.prod(wire.SHAPES[point]) * 4
            assert int(row['payload_bytes']) == int(peer['expected_payload_bytes']) == int(peer['actual_payload_bytes']) == size
            assert int(row['response_payload_bytes']) == int(peer['response_payload_bytes']) == 4000
            assert int(row['response_wire_bytes']) == int(peer['response_wire_bytes']) == 4080
            assert int(row['request_wire_bytes']) == size + 80
            assert row['request_payload_sha256'] == peer['request_payload_sha256'] and len(row['request_payload_sha256']) == 64
            assert row['response_payload_sha256'] == peer['response_payload_sha256'] and len(row['response_payload_sha256']) == 64
    for row in checks:
        assert row['assert_close_passed'] == row['finite'] == 'True' and not row['error']
        assert ast.literal_eval(row['output_shape']) == [1,1000]
        assert all(math.isfinite(float(row[k])) for k in ['max_abs_error','mean_abs_error','max_rel_error'])
    return {'passed': True, 'network_requests': 27, 'local_only_executions': 3,
            'connections': 1, 'correctness_rows': 30, 'p9_request_ids_absent_from_server': True,
            'request_response_ids_and_payload_hashes_match': True,
            'max_abs_error': max(float(r['max_abs_error']) for r in checks),
            'max_rel_error': max(float(r['max_rel_error']) for r in checks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    out = args.output_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    out.mkdir(parents=True, exist_ok=False)
    print('RESULT_DIRECTORY=' + str(out), flush=True)
    protected_paths = set()
    for base in [ROOT / 'split_inference/results/edge_processing_profile', ROOT / 'split_inference/docs']:
        protected_paths.update(p for p in base.rglob('*') if p.is_file())
    protected = {str(p): sha(p) for p in sorted(protected_paths)}
    save(out / 'preserved_before.json', protected)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TORCH_ALLOW_TF32_CUBLAS_OVERRIDE='0', NVIDIA_TF32_OVERRIDE='0')
    unit = [sys.executable, '-B', '-m', 'unittest', '-v', 'split_inference.tests.test_split_tensor_protocol']
    invocation = {'unit_tests': unit, 'cwd': str(ROOT), 'smoke_sample_ids': [0,149,299],
                  'host': '127.0.0.1', 'concurrency': 1, 'scope': 'correctness only, not performance',
                  'environment_overrides': {k:env[k] for k in ['PYTHONDONTWRITEBYTECODE','TORCH_ALLOW_TF32_CUBLAS_OVERRIDE','NVIDIA_TF32_OVERRIDE']}}
    result = {'status': 'running'}
    server = client = None
    handles = []
    try:
        with (out / 'unit_tests.stdout.log').open('x') as stdout, (out / 'unit_tests.stderr.log').open('x') as stderr:
            test = subprocess.run(unit, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, timeout=30)
        assert test.returncode == 0, 'protocol unit tests failed; smoke prohibited'
        result['unit_tests_exit_code'] = test.returncode
        print('PROTOCOL_UNIT_TESTS_PASS', flush=True)
        gpu = subprocess.run(['nvidia-smi','-q'], capture_output=True, text=True, timeout=15, check=True)
        (out / 'before_nvidia_smi.txt').write_text(gpu.stdout)
        processes = subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,process_name,used_gpu_memory','--format=csv,noheader'], text=True)
        (out / 'before_compute_processes.txt').write_text(processes)
        assert not processes.strip(), 'other compute process present; smoke prohibited'
        server_cmd = [sys.executable,'-B','-m','split_inference.scripts.serve_efficientnet_v2_s_tcp',
                      '--cache',str(args.cache),'--host','127.0.0.1','--port','0','--timeout','60',
                      '--verify-payload','--output',str(out/'server')]
        invocation['server'] = server_cmd
        for name in ['server.stdout.log','server.stderr.log','client.stdout.log','client.stderr.log']:
            handles.append((out/name).open('x'))
        server = subprocess.Popen(server_cmd, cwd=ROOT, env=env, stdout=handles[0], stderr=handles[1])
        deadline = time.monotonic() + 120
        ready = out / 'server/ready.json'
        while not ready.exists():
            assert server.poll() is None, 'server exited before readiness'
            assert time.monotonic() < deadline, 'server readiness deadline exceeded'
            time.sleep(.1)
        # Ready file is written once immediately before accept. The tiny file may
        # become visible before close, so wait for a newline (not a network retry).
        while not ready.read_text().endswith('\n'):
            assert time.monotonic() < deadline, 'ready file completion deadline'
            time.sleep(.01)
        port = json.loads(ready.read_text())['address'][1]
        client_cmd = [sys.executable,'-B','-m','split_inference.scripts.run_efficientnet_v2_s_tcp',
                      '--cache',str(args.cache),'--zip',str(args.zip),'--host','127.0.0.1','--port',str(port),
                      '--timeout','60','--sample-ids','0,149,299','--partitions','0,1,2,3,4,5,6,7,8,9',
                      '--verify-payload','--output',str(out/'client')]
        invocation['client'] = client_cmd
        save(out / 'invocation.json', invocation)
        client = subprocess.Popen(client_cmd, cwd=ROOT, env=env, stdout=handles[2], stderr=handles[3])
        result['client_exit_code'] = client.wait(timeout=180)
        assert result['client_exit_code'] == 0, 'client correctness failed; no retry'
        result['server_exit_code'] = server.wait(timeout=30)
        assert result['server_exit_code'] == 0, 'server did not stop cleanly'
        for handle in handles:
            handle.flush()
        assert not (out/'server.stderr.log').read_text() and not (out/'client.stderr.log').read_text(), 'runtime stderr not empty'
        result.update(validate(out), status='passed', server_pid=server.pid, client_pid=client.pid,
                      server_reaped=True, client_reaped=True, no_retries=True, no_fallback=True)
        assert all(sha(Path(path)) == digest for path,digest in protected.items()), 'protected artifact changed'
        result['preserved_files_unchanged'] = len(protected)
        print('LOCALHOST_CORRECTNESS_PASS 27 network / 3 local-only', flush=True)
    except BaseException:
        result.update(status='failed', error=traceback.format_exc())
        traceback.print_exc()
        raise
    finally:
        for proc in [client,server]:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                    result['forced_process_cleanup'] = True
        for handle in handles:
            handle.close()
        if not (out/'invocation.json').exists():
            save(out/'invocation.json',invocation)
        (out/'after_nvidia_smi.txt').write_text(subprocess.run(['nvidia-smi','-q'], capture_output=True, text=True, timeout=15).stdout)
        result['git_status'] = subprocess.check_output(['git','status','--short','--branch'], cwd=ROOT, text=True)
        save(out/'smoke_manifest.json', result)
        save(out/'protocol_manifest.json', {'magic':'ESFP','version':2,'header_struct':wire.HEADER.format,
             'header_bytes':wire.HEADER.size,'header_byte_order':'network/big endian','tensor_byte_order':'little endian FP32',
             'maximum_payload_bytes':wire.MAX_PAYLOAD,'payload_sha256':'enabled for this smoke only; default off',
             'server_telemetry_in_response':False,'shapes':wire.SHAPES,
             'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in
                [ROOT/'split_inference/src/common/split_tensor_protocol.py',ROOT/'split_inference/src/common/efficientnet_v2_s_pretrained_runtime.py',
                 ROOT/'split_inference/scripts/serve_efficientnet_v2_s_tcp.py',ROOT/'split_inference/scripts/run_efficientnet_v2_s_tcp.py',
                 Path(__file__).resolve(),ROOT/'split_inference/tests/test_split_tensor_protocol.py']}})
        save(out/'artifact_sha256.json', {str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})


if __name__ == '__main__':
    main()
