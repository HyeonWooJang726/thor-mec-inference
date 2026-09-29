"""Read-only evidence validation, then exclusive READY marker; never contacts Edge."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import config

OUT = config.OUT
EVIDENCE = OUT / 'edge_preflight_evidence'
READY = OUT / 'EDGE_PREFLIGHT_READY.json'
NAMES = ('edge_preflight_CE1.json', 'edge_preflight_CE2.json', 'edge_preflight_stdout.txt')


def validate_evidence(plan):
    if any(not (EVIDENCE / name).is_file() for name in NAMES):
        raise RuntimeError('Both real-Edge preflight JSON files and stdout are required')
    stdout = (EVIDENCE / NAMES[2]).read_text()
    digests = {name: config.sha(EVIDENCE / name) for name in NAMES}
    for c in (1, 2):
        name = f'edge_preflight_CE{c}.json'
        row = json.loads((EVIDENCE / name).read_text())
        required = {
            'status': 'PASS', 'campaign': 'EDGE_INFLIGHT_ROBUSTNESS02',
            'C_E': c, 'B': 1, 'plan_sha256': config.sha(config.PLAN),
            'bundle_sha256': plan['bundle_sha256'],
            'server_source_sha256': plan['edge_dependency_sha256']['edge_server.py'],
            'engine_sha256': plan['edge_engine_SHA256'],
            'cache_sha256': plan['cache']['sha256'],
            'TensorRT_import': 'PASS', 'engine_deserialization': 'PASS',
            'helpers_trt_binding': 'PASS', 'worker_count': c,
            'context_count': c, 'stream_count': c,
            'no_resource_alias': True, 'dtype_mapping': 'PASS',
            'warmup_status': 'PASS', 'real_inference_status': 'PASS',
            'output_validity': 'PASS', 'clean_teardown': True,
        }
        for key, value in required.items():
            if row.get(key) != value or type(row.get(key)) is not type(value):
                raise RuntimeError(f'C_E={c} preflight mismatch: {key}')
        if not row.get('TensorRT_version') or row.get('errors') != [] or not row.get('timestamp_utc'):
            raise RuntimeError(f'C_E={c} preflight runtime/error evidence incomplete')
        workers = row.get('workers')
        if not isinstance(workers, list) or len(workers) != c or \
                sorted(w.get('worker_id') for w in workers) != list(range(c)):
            raise RuntimeError(f'C_E={c} worker IDs/cardinality invalid')
        resources = [w.get('resources', {}) for w in workers]
        contexts = [r.get('context_object_id') for r in resources]
        streams = [r.get('cuda_stream_pointer') for r in resources]
        device = [p for r in resources for p in r.get('device_buffers', {}).values()]
        host = [p for r in resources for p in r.get('pinned_host_buffers', {}).values()]
        if None in contexts or None in streams or len(set(contexts)) != c or len(set(streams)) != c or \
                len(device) != 3*c or len(host) != 3*c or \
                len(set(device)) != len(device) or len(set(host)) != len(host):
            raise RuntimeError(f'C_E={c} context/stream/buffer alias or cardinality')
        if any(w.get('warmup_completed') != 2 or w.get('real_inference_completed') != 1 or
               w.get('finite_expected_output') is not True or w.get('clean_teardown') is not True
               for w in workers):
            raise RuntimeError(f'C_E={c} worker inference/teardown evidence invalid')
        if f'PASS C_E={c} Edge-local backend smoke' not in stdout:
            raise RuntimeError(f'C_E={c} stdout PASS line absent')
    return digests


def require_ready(plan):
    if not READY.is_file():
        raise RuntimeError('EDGE_PREFLIGHT_REQUIRED: real-Edge C_E=1/2 evidence not verified')
    marker = json.loads(READY.read_text())
    if marker.get('status') != 'EDGE_INFLIGHT_ROBUSTNESS02_READY_WAITING_FOR_EXECUTION_APPROVAL' or \
            marker.get('plan_sha256') != config.sha(config.PLAN) or \
            marker.get('bundle_sha256') != plan['bundle_sha256'] or \
            marker.get('engine_sha256') != plan['edge_engine_SHA256']:
        raise RuntimeError('Stale/wrong Edge preflight READY marker')
    if marker.get('evidence_sha256') != validate_evidence(plan):
        raise RuntimeError('Edge preflight evidence changed after verification')
    return marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-plan-sha256', required=True)
    args = parser.parse_args()
    plan = config.load_plan()
    if args.approve_plan_sha256 != config.sha(config.PLAN):
        raise RuntimeError('Exact frozen plan SHA required')
    if READY.exists():
        raise RuntimeError('Preflight READY marker already exists; no overwrite')
    digests = validate_evidence(plan)
    record = {'status': 'EDGE_INFLIGHT_ROBUSTNESS02_READY_WAITING_FOR_EXECUTION_APPROVAL',
              'verified_utc': datetime.now(timezone.utc).isoformat(),
              'plan_sha256': config.sha(config.PLAN),
              'bundle_sha256': plan['bundle_sha256'],
              'engine_sha256': plan['edge_engine_SHA256'],
              'evidence_sha256': digests,
              'scope': 'Real Edge-local C_E=1/2 backend smoke only; no measured session'}
    with READY.open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    print(record['status'])


if __name__ == '__main__':
    main()
