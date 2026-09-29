"""Non-measured Edge-local real-TensorRT backend smoke; no sockets or campaign sessions."""
import argparse
import hashlib
import json
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

import edge_server
import formal_protocol as wire


def bundle_digest(deps):
    canonical = json.dumps(deps, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_frozen(args):
    plan_path = Path(args.plan).resolve()
    plan_sha = wire.sha(plan_path)
    if plan_sha != args.approve_plan_sha256:
        raise RuntimeError('Exact frozen plan SHA required')
    plan = json.loads(plan_path.read_text())
    here = Path(__file__).resolve().parent
    if plan['campaign'] != 'EDGE_INFLIGHT_ROBUSTNESS02' or plan['B'] != 1:
        raise RuntimeError('Wrong campaign or batch size')
    deps = plan['edge_dependency_sha256']
    if bundle_digest(deps) != plan['bundle_sha256']:
        raise RuntimeError('Bundle digest mismatch')
    for name, expected in deps.items():
        if Path(name).name != name or wire.sha(here / name) != expected:
            raise RuntimeError('Frozen bundle source mismatch: ' + name)
    for line in (here / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if Path(name).name != name or wire.sha(here / name) != digest:
            raise RuntimeError('Frozen assembled bundle mismatch: ' + name)
    if wire.sha(args.engine) != plan['edge_engine_SHA256']:
        raise RuntimeError('Exact engine identity mismatch')
    if wire.sha(args.cache) != plan['cache']['sha256']:
        raise RuntimeError('Exact RAW640 cache identity mismatch')
    return plan, plan_sha


def smoke(args):
    plan, plan_sha = validate_frozen(args)
    factory = edge_server.BackendFactory(args)
    workers = []
    errors = []
    lock = threading.Lock()
    constructed = threading.Barrier(args.c_e)

    def worker(worker_id):
        backend = None
        row = {'worker_id': worker_id, 'warmup_completed': 0,
               'real_inference_completed': 0, 'clean_teardown': False}
        try:
            backend = factory(worker_id)
            row['resources'] = backend.info()['resources']
            constructed.wait(timeout=120)
            raw = backend.payloads[0]
            if len(raw) != wire.RAW_BYTES:
                raise RuntimeError('Frozen RAW640 sample size mismatch')
            for _ in range(2):
                _, payload = backend.process(raw)
                wire.decode_outputs(payload)
                row['warmup_completed'] += 1
            _, payload = backend.process(raw)
            output = wire.decode_outputs(payload)
            row['real_inference_completed'] = 1
            row['finite_expected_output'] = (
                len(payload) == wire.OUTPUT_BYTES and
                tuple(output['pred_logits'].shape) == (1, 300, 7) and
                tuple(output['pred_boxes'].shape) == (1, 300, 4))
        except BaseException:
            with lock:
                errors.append({'worker_id': worker_id, 'traceback': traceback.format_exc()})
            constructed.abort()
        finally:
            if backend is not None:
                try:
                    backend.close()
                    row['clean_teardown'] = True
                except BaseException:
                    with lock:
                        errors.append({'worker_id': worker_id, 'teardown_traceback': traceback.format_exc()})
            with lock:
                workers.append(row)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True,
                                name=f'edge-local-preflight-C{args.c_e}-{i}')
               for i in range(args.c_e)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=180)
    alive = any(thread.is_alive() for thread in threads)
    engine_deserialized = factory.engine is not None
    if alive:
        errors.append({'thread_lifecycle': 'worker did not stop within 180 s'})
    else:
        try:
            factory.close()
        except BaseException:
            errors.append({'factory_teardown_traceback': traceback.format_exc()})
    workers.sort(key=lambda row: row['worker_id'])
    resources = [row.get('resources', {}) for row in workers]
    contexts = [row.get('context_object_id') for row in resources]
    streams = [row.get('cuda_stream_pointer') for row in resources]
    device_buffers = [ptr for row in resources for ptr in row.get('device_buffers', {}).values()]
    host_buffers = [ptr for row in resources for ptr in row.get('pinned_host_buffers', {}).values()]
    no_alias = (len(set(contexts)) == len(set(streams)) == args.c_e and
                None not in contexts and None not in streams and
                len(device_buffers) == len(host_buffers) == 3 * args.c_e and
                len(set(device_buffers)) == len(device_buffers) and
                len(set(host_buffers)) == len(host_buffers))
    bound = factory.helpers is not None and factory.helpers.trt is sys.modules.get('tensorrt')
    passed = (not errors and not alive and len(workers) == args.c_e and no_alias and bound and
              all(row['warmup_completed'] == 2 and row['real_inference_completed'] == 1 and
                  row.get('finite_expected_output') is True and row['clean_teardown']
                  for row in workers))
    return {'status': 'PASS' if passed else 'FAIL',
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'campaign': plan['campaign'], 'C_E': args.c_e, 'B': 1,
            'plan_sha256': plan_sha, 'bundle_sha256': plan['bundle_sha256'],
            'server_source_sha256': plan['edge_dependency_sha256']['edge_server.py'],
            'engine_sha256': wire.sha(args.engine), 'engine_path': str(Path(args.engine).resolve()),
            'cache_sha256': wire.sha(args.cache),
            'TensorRT_version': getattr(factory, 'trt_version', None),
            'TensorRT_import': 'PASS' if 'tensorrt' in sys.modules else 'FAIL',
            'engine_deserialization': 'PASS' if engine_deserialized else 'FAIL',
            'helpers_trt_binding': 'PASS' if bound else 'FAIL',
            'worker_count': len(workers), 'context_count': len(contexts),
            'stream_count': len(streams), 'no_resource_alias': no_alias,
            'dtype_mapping': 'PASS' if passed else 'FAIL',
            'warmup_status': 'PASS' if all(row['warmup_completed'] == 2 for row in workers) and len(workers)==args.c_e else 'FAIL',
            'real_inference_status': 'PASS' if all(row['real_inference_completed'] == 1 for row in workers) and len(workers)==args.c_e else 'FAIL',
            'output_validity': 'PASS' if all(row.get('finite_expected_output') is True for row in workers) and len(workers)==args.c_e else 'FAIL',
            'clean_teardown': not alive and all(row['clean_teardown'] for row in workers) and len(workers)==args.c_e,
            'workers': workers, 'errors': errors,
            'scope': 'Edge-local non-measured real TensorRT/CUDA backend smoke; no network client or listener'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--approve-plan-sha256', required=True)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--c-e', type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    output = Path(args.output_dir) / f'edge_preflight_CE{args.c_e}.json'
    if output.exists():
        raise RuntimeError('Preflight evidence already exists; no overwrite')
    try:
        result = smoke(args)
    except BaseException:
        result = {'status': 'FAIL', 'C_E': args.c_e, 'B': 1,
                  'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                  'errors': [traceback.format_exc()]}
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(f"{result['status']} C_E={args.c_e} Edge-local backend smoke; evidence={output}", flush=True)
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
