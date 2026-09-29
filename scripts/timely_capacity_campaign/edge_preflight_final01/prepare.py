"""CPU-only one-time freeze of Edge temporal calibration; no launch or system writes."""
import csv
import hashlib
import json
import sys
from pathlib import Path

import config

sys.path.insert(0, str(config.HERE.parent / 'common' / 'service_phase_b1f'))
import cpu_state
from make_cpu_commands import render


def write_json(name, value):
    with (config.OUT / name).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def copy_exact(source, dest):
    with Path(source).open('rb') as inp, Path(dest).open('xb') as out:
        out.write(inp.read())
    if config.sha(source) != config.sha(dest):
        raise RuntimeError('Edge bundle copy mismatch: ' + str(source))


def main():
    out = config.OUT
    if any((out / name).exists() for name in ('plan.json', 'plan.sha256', 'campaign_attempt.json')):
        raise RuntimeError('Fresh final01 namespace already frozen/consumed; no overwrite')
    old_bundle = config.ROOT / 'results/timely_capacity_campaign/block_b_split/v2/edge_bundle_v2'
    old_plan = json.loads((config.ROOT / 'results/timely_capacity_campaign/block_b_split/v2/preflight_plan.json').read_text())
    cache = old_plan['cache']
    if config.sha(config.ROOT / cache['path']) != cache['sha256']:
        raise RuntimeError('Existing RAW640 cache SHA mismatch')
    bundle = out / 'edge_bundle'
    dependencies = {}
    for name in ('formal_protocol.py', 'formal_server.py', 'profile_edge_concurrency.py',
                 'pruning_edge_server.py'):
        source = old_bundle / name
        copy_exact(source, bundle / name)
        dependencies[name] = config.sha(source)
    server_source = config.HERE / 'edge_server_final01.py'
    copy_exact(server_source, bundle / 'edge_server_final01.py')
    dependencies['edge_server_final01.py'] = config.sha(server_source)

    rates = {}
    for rate in config.RATES:
        q = config.q(rate)
        bits = ''.join(map(str, q))
        rates[str(rate)] = {'per_stream_rate': rate // 8, 'q_bits': bits,
            'q': list(q), 'q_SHA256_ASCII_bits': hashlib.sha256(bits.encode('ascii')).hexdigest(),
            'generator': 'campaign_config.schedule(rate, edge=0, pattern=ALIGNED): canonical floor accumulator'}
    write_json('EDGE_RATE_PATTERNS.json', rates)
    aligned = {str(rate): config.schedule(rate, 'ALIGNED') for rate in config.RATES}
    staggered = {str(rate): config.schedule(rate, 'STAGGERED') for rate in config.RATES}
    write_json('ALIGNED_EDGE_SCHEDULES.json', aligned)
    write_json('STAGGERED_EDGE_SCHEDULES.json', staggered)
    write_json('TEMPORAL_PATTERN_VALIDATION.json', {'status': 'PASS', 'phase_vector': list(config.PHASES),
        'source_arrival_rule': 't0+floor(frame_index*1e9/30), all K8 streams phase0',
        'no_deferred_admission': True, 'frame_reorder': False,
        'slot_diagnostics': {str(rate): {'ALIGNED': aligned[str(rate)],
                                        'STAGGERED': staggered[str(rate)]} for rate in config.RATES},
        'global_optimality_claim': False, 'phase_search_used': False})
    write_json('mechanism_expectations.json', {'verdict_effect': 'NONE',
        'expectations': ['TIR_STAGGERED >= TIR_ALIGNED at equal E, descriptive only',
                         'server queue p95_STAGGERED <= p95_ALIGNED, descriptive only'],
        'historical_indication': 'Older globally paced E72 ~0.90-0.98 TIR; E80 boundary/failure possible; not a classifier input'})

    previous = config.ROOT / 'results/timely_capacity_campaign/block_b_split/v2/preflight01/selection.json'
    historical = json.loads(previous.read_text())
    with (out / 'historical_edge_reference.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=('run_id', 'rate', 'repeat', 'Edge_timely_ratio',
                                 'integrity_status', 'provenance', 'new_classification_eligible'))
        writer.writeheader()
        for row in historical['runs']:
            writer.writerow({key: row.get(key) for key in ('run_id', 'rate', 'repeat',
                             'Edge_timely_ratio', 'integrity_status')} |
                             {'provenance': 'Historical globally paced V2 preflight, CPU not final-controlled',
                              'new_classification_eligible': False})
    write_json('historical_edge_provenance.json', {'source': str(previous.relative_to(config.ROOT)),
        'source_SHA256': config.sha(previous), 'historical_runs': len(historical['runs']),
        'new_classification_eligible': False})

    state = cpu_state.snapshot()
    if len(state['policies']) != 7 or any(p['fields']['scaling_max_freq'] != '2601000' for p in state['policies']):
        raise RuntimeError('CPU topology/max changed')
    for policy in state['policies']:
        policy['fields']['scaling_available_governors'] = (Path(policy['path']) / 'scaling_available_governors').read_text().strip()
    write_json('CPU_STATE_BEFORE.json', state)
    with (out / 'CPU_PIN_COMMANDS.sh').open('x') as stream:
        stream.write(render(state, restore=False))
    with (out / 'CPU_RESTORE_COMMANDS.sh').open('x') as stream:
        stream.write(render(state, restore=True))

    session_files = {}
    for name, obj in [('base_session_plan.json', {'stage': 'BASE', 'branch': None,
                                                   'order': config.base_order()})] + [
            (f'extension_{branch}.json', {'stage': 'EXTENSION', 'branch': branch, 'order': rows})
            for branch, rows in config.extension_orders().items()]:
        write_json(name, obj)
        session_files[name] = config.sha(out / name)

    protected_sources = [config.HERE / name for name in ('config.py', 'run_thor.py',
        'edge_server_final01.py', 'analyze.py', 'prepare.py', 'test_cpu.py')]
    protected_sources += [config.ROOT / name for name in (
        'scripts/timely_capacity_campaign/common/campaign_config.py',
        'scripts/timely_capacity_campaign/common/edge_preflight.py',
        'scripts/timely_capacity_campaign/common/reuse.py',
        'scripts/timely_capacity_campaign/block_b_split/v2/wifi_v2.py',
        'scripts/timely_capacity_campaign/common/service_phase_b1f/cpu_state.py',
        'scripts/timely_capacity_campaign/common/service_phase_b1f/make_cpu_commands.py',
        'scripts/expired_work_pruning/pruning_common.py',
        'scripts/hybrid_capacity_extension/edge_link.py')]
    sources = {str(path.relative_to(config.ROOT)): config.sha(path) for path in protected_sources}
    write_json('source_sha256.json', sources)
    plan = {'campaign': 'EDGE_PREFLIGHT_FINAL01_TEMPORAL_PHASE',
        'freeze_status': 'FROZEN_PREPARATION_REQUIRES_APPROVAL',
        'purpose': 'Edge-only Block B capacity calibration; not hybrid capacity or final contribution',
        'deadline_ms': 100, 'seconds': config.SECONDS, 'idle_seconds': config.IDLE_SECONDS,
        'K': 8, 'source_FPS_per_stream': 30,
        'source_due': 't0+floor(frame_index*1e9/30), eight synchronized streams',
        'phase_vector': list(config.PHASES), 'payload_bytes': config.PAYLOAD_BYTES,
        'payload_scope': 'RAW640 image bytes; network interface counter also includes unrelated traffic/protocol overhead',
        'cache': cache, 'edge_host': old_plan['edge_host'], 'edge_port': 5000,
        'edge_engine_SHA256': 'c94050f1969bca2fef9622c14fd9e307277ba26b0630bf5a669a980a8bad75e9',
        'base_order': config.base_order(), 'extension_orders': config.extension_orders(),
        'extension_rule': 'Pattern-specific E80 2/2 EDGE_USABLE -> that pattern E88x2; four frozen branches',
        'classification': {'EDGE_USABLE': '2/2 TIR_admission >= 0.90',
                           'EDGE_FAIL': '2/2 TIR_admission < 0.80',
                           'EDGE_BOUNDARY': 'all other valid two-repeat outcomes'},
        'session_plan_sha256': session_files, 'edge_dependency_sha256': dependencies,
        'artifact_sha256': {name: config.sha(out / name) for name in (
            'EDGE_RATE_PATTERNS.json', 'ALIGNED_EDGE_SCHEDULES.json',
            'STAGGERED_EDGE_SCHEDULES.json', 'TEMPORAL_PATTERN_VALIDATION.json',
            'mechanism_expectations.json', 'historical_edge_reference.csv',
            'CPU_STATE_BEFORE.json')},
        'historical_edge_reference_use': 'read-only descriptive; never new two-repeat classification',
        'server_queue_stall_count': 'N/A native counter; queue timestamps/peak reused',
        'Thor_GPU_frequency_control': 'NONE; no Local inference',
        'Edge_server_runtime': 'pruning_edge_server.serve_session and formal_server.Backend byte-identical verified bundle'}
    write_json('plan.json', plan)
    with (out / 'plan.sha256').open('x') as stream:
        stream.write(config.sha(config.PLAN) + '\n')
    for name in ('plan.json', 'base_session_plan.json') + tuple(
            f'extension_{branch}.json' for branch in config.extension_orders()):
        copy_exact(out / name, bundle / name)
    files = sorted(p for p in bundle.iterdir() if p.is_file())
    with (bundle / 'SHA256SUMS').open('x') as stream:
        for path in files:
            stream.write(config.sha(path) + '  ' + path.name + '\n')
    write_json('BUNDLE_SHA256.json', {path.name: config.sha(path) for path in files})
    print(json.dumps({'plan_SHA256': config.sha(config.PLAN), 'base_runs': 8,
                      'maximum_runs': 12, 'q': {rate: rates[str(rate)]['q_bits'] for rate in config.RATES},
                      'bundle_files': len(files)}, indent=2))


if __name__ == '__main__':
    main()
