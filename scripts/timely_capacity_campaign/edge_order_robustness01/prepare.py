"""CPU-only exclusive-create freeze. Never starts Edge/Thor sessions."""
import hashlib
import json
import sys
from pathlib import Path

import config

sys.path.insert(0, str(config.HERE.parent / 'common' / 'service_phase_b1f'))
import cpu_state
from make_cpu_commands import render


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def copy(source, target):
    with Path(source).open('rb') as src, Path(target).open('xb') as dst:
        dst.write(src.read())
    if config.sha(source) != config.sha(target):
        raise RuntimeError('Bundle copy mismatch')


def tree_hash(root):
    entries = {str(p.relative_to(root)): config.sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    out = config.OUT
    if any((out / name).exists() for name in ('plan.json', 'campaign_attempt.json', 'sessions')):
        raise RuntimeError('Order namespace already frozen/consumed')
    old = config.ROOT / 'results/timely_capacity_campaign/v2_2/edge_e48_confirmation01'
    protected = [old, config.ROOT / 'results/timely_capacity_campaign/v2_2/block_a_phase_pilot02',
                 config.ROOT / 'results/timely_capacity_campaign/v2_2/edge_preflight_final02']
    before = {str(p): tree_hash(p) for p in protected}
    prior = json.loads((old / 'plan.json').read_text())
    mask = list(config.q6())
    matrix = config.exposure()
    if any(value not in (22, 23) for row in matrix for value in row) or any(max(row)-min(row)>1 for row in matrix):
        raise RuntimeError('ROTATE exposure 22/23 check failed')
    if prior['edge_ip'] != '192.168.0.6' or config.sha(config.ROOT / prior['cache']['path']) != prior['cache']['sha256']:
        raise RuntimeError('Reference endpoint/cache drift')
    endpoint = json.loads((old / 'EDGE_ENDPOINT_MANIFEST.json').read_text())
    write(out / 'EDGE_ENDPOINT_MANIFEST.json', endpoint)
    write(out / 'DISPATCH_ORDER_MANIFEST.json', {
        'q6': mask, 'q6_ascii_sha256': hashlib.sha256(''.join(map(str, mask)).encode()).hexdigest(),
        'E48_ALIGNED_mask_per_stream': [mask] * 8,
        'BASE': list(range(8)), 'REVERSE': list(range(7, -1, -1)),
        'ROTATE': 'active-slot j starts at 0 each run; [(j+i)%8 for i=0..7]',
        'ROTATE_exposure_stream_by_position': matrix, 'ROTATE_exposure_values_only_22_or_23': True,
        'ROTATE_row_gap_at_most_1': True, 'active_slots_30s': 180,
        'warmup': 'E48 STAGGERED 15s, excluded from scoring'})
    write(out / 'mechanism_expectations.json', {
        'binding_to_verdict': False, 'BASE_G_id': '>0 expected', 'REVERSE_G_id': '<0 expected',
        'ROTATE': 'per-stream loss distributed; aggregate eight-frame burst remains',
        'primary_rule': 'BASE 5/5 G_id>0 AND REVERSE 5/5 G_id<0'})
    write(out / 'session_plan.json', {'stage': 'ORDER', 'order': config.frozen_order(),
        'warmup_index': 0, 'measured_indices': list(range(1, 16)),
        'first_INVALID': 'stop; no retry/resume/overwrite'})
    state = cpu_state.snapshot()
    if len(state['policies']) != 7 or any(row['fields']['scaling_max_freq'] != '2601000' for row in state['policies']):
        raise RuntimeError('Expected seven 2601000-kHz CPU policies')
    for row in state['policies']:
        row['fields']['scaling_available_governors'] = (Path(row['path']) / 'scaling_available_governors').read_text().strip()
    write(out / 'CPU_STATE_BEFORE.json', state)
    for name, restore in (('CPU_PIN_COMMANDS.sh', False), ('CPU_RESTORE_COMMANDS.sh', True)):
        with (out / name).open('x') as stream:
            stream.write(render(state, restore=restore))
    bundle = out / 'edge_bundle'
    bundle.mkdir(exist_ok=False)
    dependencies = {}
    for name in ('formal_protocol.py', 'formal_server.py', 'profile_edge_concurrency.py', 'pruning_edge_server.py'):
        copy(old / 'edge_bundle' / name, bundle / name)
        dependencies[name] = config.sha(bundle / name)
    server = config.HERE / 'edge_server_order01.py'
    copy(server, bundle / server.name)
    dependencies[server.name] = config.sha(server)
    names = [config.HERE / n for n in ('config.py', 'run_thor.py', 'analyze.py', 'prepare.py', 'edge_server_order01.py', 'test_cpu.py')]
    names += [config.ROOT / rel for rel in (
        'scripts/timely_capacity_campaign/common/dispatch_observation.py',
        'scripts/timely_capacity_campaign/common/campaign_config.py',
        'scripts/timely_capacity_campaign/common/reuse.py',
        'scripts/timely_capacity_campaign/common/service_phase_b1f/cpu_state.py',
        'scripts/timely_capacity_campaign/common/service_phase_b1f/make_cpu_commands.py',
        'scripts/timely_capacity_campaign/block_b_split/v2/wifi_v2.py',
        'scripts/expired_work_pruning/pruning_common.py',
        'scripts/hybrid_capacity_extension/edge_link.py')]
    source = {str(p.relative_to(config.ROOT)): config.sha(p) for p in names}
    write(out / 'source_sha256.json', source)
    plan = {'campaign': 'EDGE_ORDER_ROBUSTNESS01', 'freeze_status': 'PREPARED_NOT_EXECUTED',
        'K': 8, 'source_FPS_per_stream': 30, 'rate': 48, 'deadline_ms': 100,
        'edge_C': 1, 'edge_B': 1, 'payload_bytes': config.PAYLOAD_BYTES,
        'cache': prior['cache'], 'edge_ip': endpoint['edge_ip'], 'edge_host': endpoint['edge_ip'],
        'edge_port': 5000, 'edge_engine_SHA256': prior['edge_engine_SHA256'],
        'endpoint_manifest_sha256': config.sha(out / 'EDGE_ENDPOINT_MANIFEST.json'),
        'source_sha256': source, 'idle_seconds': 10,
        'order': config.frozen_order(),
        'session_plan_sha256': {'session_plan.json': config.sha(out / 'session_plan.json')},
        'edge_dependency_sha256': dependencies,
        'artifact_sha256': {name: config.sha(out / name) for name in
            ('DISPATCH_ORDER_MANIFEST.json', 'mechanism_expectations.json', 'CPU_STATE_BEFORE.json')},
        'primary_verdict': 'BASE 5/5 G_id>0 and REVERSE 5/5 G_id<0',
        'G_id': 'TIR(stream0)-TIR(stream7)',
        'warmup': 'first 15s E48 STAGGERED; integrity/drain/pending-zero; scoring excluded',
        'no_TCP_preflight_probe': True}
    write(out / 'plan.json', plan)
    with (out / 'plan.sha256').open('x') as stream:
        stream.write(config.sha(out / 'plan.json') + '\n')
    for name in ('plan.json', 'session_plan.json'):
        copy(out / name, bundle / name)
    with (bundle / 'SHA256SUMS').open('x') as stream:
        for path in sorted(p for p in bundle.iterdir() if p.name != 'SHA256SUMS'):
            stream.write(config.sha(path) + '  ' + path.name + '\n')
    after = {str(p): tree_hash(p) for p in protected}
    write(out / 'preservation.json', {'status': 'PASS' if before == after else 'FAIL',
        'protected_tree_sha256_before': before, 'protected_tree_sha256_after': after})
    if before != after:
        raise RuntimeError('Protected namespace changed')
    print(json.dumps({'plan_sha256': config.sha(out / 'plan.json'), 'sessions': len(config.frozen_order()),
                      'ROTATE_exposure_PASS': True, 'preservation': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()
