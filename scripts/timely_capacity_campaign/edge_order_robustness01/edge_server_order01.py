"""Edge launch adapter; frozen RAW640 C_E=1 backend/session code is unchanged."""
import argparse
import json
import socket
import traceback
from pathlib import Path

import formal_protocol as wire
import pruning_edge_server as prior
from formal_server import Backend


def expected_hello(c, digest, cache_sha):
    return {'mode': 'edge_order_robustness01', 'rate': c['rate'],
            'seconds': c['seconds'], 'repeat': c['repeat'], 'run_id': c['run_id'],
            'campaign_plan_sha256': digest, 'cache_sha256': cache_sha,
            'payload_origin': 'CACHED_REAL_RAW640_30; K8_30FPS_SOURCE_SLOT_SELECTION',
            'deadline_ms': 100, 'admission_pattern': c['pattern'],
            'phase_vector': c['phase_vector'], 'stage': c['stage'],
            'dispatch_order_mode': c['dispatch_order_mode']}


def main():
    parser = argparse.ArgumentParser()
    for key in ('plan', 'session-plan', 'engine', 'cache', 'output', 'approve-plan-sha256'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan)
    digest = wire.sha(plan_path)
    if digest != args.approve_plan_sha256:
        raise RuntimeError('Exact frozen Edge preflight plan SHA required')
    plan = json.loads(plan_path.read_text())
    session_path = Path(args.session_plan)
    session = json.loads(session_path.read_text())
    if wire.sha(session_path) != plan['session_plan_sha256'].get(session_path.name):
        raise RuntimeError('Session plan changed')
    if session.get('stage') != 'ORDER' or session['order'] != plan['order']:
        raise RuntimeError('Invalid Edge session stage')
    for name, expected in plan['edge_dependency_sha256'].items():
        if wire.sha(Path(__file__).with_name(name)) != expected:
            raise RuntimeError('Frozen Edge dependency drift: ' + name)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    try:
        helpers = wire.load_runtime_helpers()
        gpu = helpers.validate_edge(args)
        helpers.load_cache(args.cache)
        wire.save(output / 'campaign_manifest.json', {'plan_sha256': digest,
            'session_plan_sha256': wire.sha(session_path), 'sessions': session['order'],
            'GPU_preflight': gpu, 'C_E': 1, 'B': 1, 'port': 5000,
            'CUDA_Graph': False, 'dynamic_batching': False,
            'server_code': 'pruning_edge_server.serve_session + formal_server.Backend unchanged'})
        results = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0', 5000))
            listener.listen(1)
            print(f'LISTENING 5000: {len(session["order"])} {session["stage"]} sessions', flush=True)
            for c in session['order']:
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s = prior.serve_session(conn, output / c['run_id'],
                        expected_hello(c, digest, helpers.CACHE_SHA256), lambda: Backend(args))
                results.append({'run_id': c['run_id'], 'integrity_status': s['integrity_status']})
                print(results[-1], flush=True)
                if s['integrity_status'] != 'VALID':
                    break
        wire.save(output / 'campaign_status.json', {'planned': len(session['order']),
            'completed': len(results), 'runs': results})
        return 0 if len(results) == len(session['order']) and all(
            row['integrity_status'] == 'VALID' for row in results) else 1
    except BaseException:
        wire.save(output / 'failure.json', {'traceback': traceback.format_exc()})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
