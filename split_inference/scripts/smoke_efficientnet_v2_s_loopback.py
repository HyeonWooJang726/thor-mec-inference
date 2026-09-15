"""Loopback functional validation only, with a local seed-0 state_dict.

Keeps local artifacts, never downloads weights, always reaps the server child.
"""

import argparse
import csv
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback

import torch
import torchvision

from split_inference.src.common.efficientnet_v2_s_runtime import ROOT, new_output, save_json
from split_inference.src.common.tcp_protocol import header, recv_frame, require, send_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'split_inference/results/e2e_loopback')
    args = parser.parse_args()
    output = new_output(args.output_root, '')
    metadata = {'status': 'running', 'scope': '127.0.0.1 loopback functionality, not Thor-Edge LAN measurement',
                'weights': None, 'seed': 0, 'server_reaped': False}
    print('RESULT_DIRECTORY=' + str(output), flush=True)
    server = None
    try:
        torch.manual_seed(0)
        model = torchvision.models.efficientnet_v2_s(weights=None).float().eval()
        state = output / 'seed0_state_dict.pt'
        torch.save(model.state_dict(), state)
        del model
        ready_file = output / 'ready.json'
        cmd = [sys.executable, '-B', '-m', 'split_inference.scripts.serve_efficientnet_v2_s_edge',
               '--state-dict', str(state), '--bind', '127.0.0.1', '--port', '0',
               '--ready-file', str(ready_file), '--output-root', str(output)]
        metadata['server_command'] = cmd
        with (output / 'server.stdout.log').open('x') as stdout, (output / 'server.stderr.log').open('x') as stderr:
            server = subprocess.Popen(cmd, cwd=ROOT, stdout=stdout, stderr=stderr)
        metadata['server_pid'] = server.pid
        deadline = time.monotonic() + 60
        while not ready_file.exists():
            require(server.poll() is None, 'server exited before readiness; see logs')
            require(time.monotonic() < deadline, 'server readiness timeout')
            time.sleep(.1)
        # File content may still be in the writer's buffer; read after the process publishes stdout READY.
        while True:
            try:
                ready = json.loads(ready_file.read_text())
                break
            except json.JSONDecodeError:
                require(time.monotonic() < deadline, 'readiness JSON timeout')
                time.sleep(.05)
        port = ready['address'][1]
        require(ready['address'][0] == '127.0.0.1', 'non-loopback bind prohibited')

        # Wrong state identity is rejected before the server executes any suffix.
        with socket.create_connection(('127.0.0.1', port), timeout=10) as conn:
            conn.settimeout(10)
            identity = {k: ready[k] for k in ('state_dict_sha256', 'manifest_sha256', 'partitions_sha256')}
            send_frame(conn, header('hello', 'mismatch-test', **{**identity, 'state_dict_sha256': '0' * 64}))
            reject, _, _ = recv_frame(conn)
            require(reject['kind'] == 'error' and 'state_dict_sha256 mismatch' in reject['message'], 'hash mismatch not rejected')
        metadata['mismatch_rejected'] = True

        def client(label, points):
            cmd = [sys.executable, '-B', '-m', 'split_inference.scripts.run_efficientnet_v2_s_e2e',
                   '--state-dict', str(state), '--host', '127.0.0.1', '--port', str(port),
                   '--partitions', points, '--warmup', '1', '--requests-per-point', '1',
                   '--output-root', str(output)]
            with (output / (label + '.stdout.log')).open('x') as out, (output / (label + '.stderr.log')).open('x') as err:
                result = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=err, timeout=120)
            require(result.returncode == 0, f'{label} failed; see logs')
            lines = (output / (label + '.stdout.log')).read_text().splitlines()
            client_output = Path(next(v.split('=', 1)[1] for v in lines if v.startswith('RESULT_DIRECTORY=')))
            require(json.loads((client_output / 'metadata.json').read_text())['status'] == 'passed', label)
            with (client_output / 'requests.csv').open() as f:
                rows = list(csv.DictReader(f))
            expected = [f'P{p}' for p in points.split(',')]
            for phase in ('warmup', 'measurement'):
                subset = [r for r in rows if r['phase'] == phase]
                require([r['partition_point'] for r in subset] == expected, 'missing or duplicated partitions')
            require(len(rows) == len(expected) * 2, 'sample count mismatch')
            require(all(r['success'] == 'True' and r['output_shape'] == '[1, 1000]' for r in rows), 'output validation')
            return {'output': str(client_output), 'rows': rows}

        metadata['p0_p9'] = client('client_all', '0,1,2,3,4,5,6,7,8,9')
        server.terminate()
        server.wait(timeout=15)
        metadata['server_reaped'] = server.poll() is not None
        metadata['server_exit_code'] = server.returncode
        require(server.returncode == 0, 'unexpected server exit')
        server_data = json.loads((Path(ready['output']) / 'metadata.json').read_text())
        require(server_data['counts'] == {'warmup': 9, 'measurement': 9}, 'P9 must not reach server')
        metadata['server_counts'] = server_data['counts']
        events = [json.loads(line) for line in (Path(ready['output']) / 'requests.jsonl').read_text().splitlines()]
        require(events[0]['event'] == 'connection_failed' and 'state_dict_sha256 mismatch' in events[0]['error'],
                'hash rejection must precede inference')
        # Prove P9 makes no connection by running it with the server already stopped.
        metadata['p9_server_stopped'] = client('client_p9_only', '9')
        metadata['status'] = 'passed'
        print('LOOPBACK_P0_P9_PASS; HASH_MISMATCH_REJECTED; P9_WITHOUT_SERVER_PASS', flush=True)
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        if server is not None:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=15)
            metadata['server_reaped'] = server.poll() is not None
            metadata['server_exit_code'] = server.returncode
        save_json(output / 'metadata.json', metadata)


if __name__ == '__main__':
    main()
