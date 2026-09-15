"""One GPU loopback pilot, without retry: preflight, warm-up, measurement, merge."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from split_inference.scripts.analyze_efficientnet_v2_s_profile import analyze, save
from split_inference.src.common.split_latency_profile import require, sha

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory; never overwrite or resume')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output.resolve()
    metadata = {'status': 'starting', 'scope': 'localhost GPU pilot; not a research result',
                'attempts': 1, 'retries': 0, 'started_utc': datetime.now(timezone.utc).isoformat()}
    processes, handles = [], []
    try:
        query = ['nvidia-smi', '--query-compute-apps=pid,process_name,used_gpu_memory', '--format=csv,noheader']
        p = subprocess.run(query, capture_output=True, text=True, timeout=20)
        save(out / 'before_compute.json', {'command': query, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        require(p.returncode == 0 and not p.stdout.strip(), 'other GPU compute process present; pilot prohibited')
        common = ['--cache', str(args.cache.resolve()), '--host', '127.0.0.1', '--timeout', '120',
                  '--verify-payload', '--profile-mode', 'pilot', '--profile-run-id', out.name]
        server_cmd = [sys.executable, '-B', '-m', 'split_inference.scripts.serve_efficientnet_v2_s_tcp',
                      *common, '--port', '0', '--output', str(out / 'server')]
        metadata['server_command'] = server_cmd
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TORCH_ALLOW_TF32_CUBLAS_OVERRIDE='0', NVIDIA_TF32_OVERRIDE='0')
        for name in ['server.stdout.log', 'server.stderr.log', 'client.stdout.log', 'client.stderr.log']:
            handles.append((out / name).open('x'))
        server = subprocess.Popen(server_cmd, cwd=ROOT, env=env, stdout=handles[0], stderr=handles[1])
        processes.append(server)
        metadata['server_pid'] = server.pid
        ready = out / 'server/ready.json'
        deadline = time.monotonic() + 120
        while not ready.exists() or not ready.read_text().endswith('\n'):
            require(server.poll() is None, 'pilot server exited before READY')
            require(time.monotonic() < deadline, 'pilot READY timeout')
            time.sleep(.05)
        address, port = json.loads(ready.read_text())['address']
        require(address == '127.0.0.1' and 0 < port <= 65535, 'pilot must use loopback ephemeral port')
        client_cmd = [sys.executable, '-B', '-m', 'split_inference.scripts.profile_efficientnet_v2_s_tcp',
                      *common, '--port', str(port), '--zip', str(args.zip.resolve()), '--output', str(out / 'client')]
        metadata['client_command'] = client_cmd
        save(out / 'invocation.json', metadata)
        client = subprocess.Popen(client_cmd, cwd=ROOT, env=env, stdout=handles[2], stderr=handles[3])
        processes.append(client)
        metadata['client_pid'] = client.pid
        metadata['client_exit_code'] = client.wait(timeout=300)
        require(client.returncode == 0, 'pilot client failed; no retry permitted')
        metadata['server_exit_code'] = server.wait(timeout=30)
        require(server.returncode == 0, 'pilot server failed')
        for handle in handles:
            handle.flush()
        require(not (out / 'client.stderr.log').read_bytes() and not (out / 'server.stderr.log').read_bytes(), 'pilot subprocess stderr not empty')
        result = analyze(out / 'client', out / 'server', out / 'analysis')
        require(result['client_rows'] == 32 and result['server_rows'] == 24 and result['correctness_rows'] == 12, 'pilot row counts')
        require(result['client_phase_counts'] == {'preflight': 12, 'warmup': 8, 'measurement': 12}, 'pilot Client phases')
        require(result['server_phase_counts'] == {'preflight': 9, 'warmup': 6, 'measurement': 9}, 'pilot Server phases')
        metadata.update(status='passed', analysis=result)
        print('LOCALHOST_PILOT_PASS 32 client / 24 server / 12 correctness; measurement 12 client / 9 server', flush=True)
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        (out / 'stderr.log').write_text(metadata['error'])
        save(out / 'failure_manifest.json', metadata)
        traceback.print_exc()
        raise
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            metadata.setdefault('reaped_processes', []).append({'pid': proc.pid, 'exit_code': proc.returncode})
        for handle in handles:
            handle.close()
        metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
        save(out / 'pilot_manifest.json', metadata)
        save(out / 'artifact_sha256.json', {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()})


if __name__ == '__main__':
    main()
