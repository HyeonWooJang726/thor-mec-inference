"""CPU-only, exclusive-create pilot02 freeze; never starts a workload."""
import csv
import hashlib
import json
import sys
from pathlib import Path

from pilot02_config import HERE, PILOT, ROOT, PRIOR, OUT, PLAN, PHASES, order, sha, run_source

sys.path.insert(0, str(PILOT.parent / 'common' / 'service_phase_b1f'))
from make_cpu_commands import render
from run_pilot02 import cpu


def put(name, data):
    target = OUT / name
    with target.open('x') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def copy(name):
    with (PRIOR / name).open('rb') as source, (OUT / name).open('xb') as target:
        target.write(source.read())


def main():
    if any((OUT / name).exists() for name in ('plan.json', 'campaign_attempt.json', 'plan.sha256')):
        raise RuntimeError('Fresh pilot02 namespace already consumed/prepared; no overwrite')
    old = json.loads((PRIOR / 'plan.json').read_text())
    if sha(PRIOR / 'plan.json') != (PRIOR / 'plan.sha256').read_text().strip():
        raise RuntimeError('Pilot01 frozen plan SHA mismatch')
    frozen = ('CANONICAL_208_PATTERN.json', 'ALIGNED_SCHEDULE.json',
              'STAGGERED_PHASE_SEARCH.json', 'STAGGERED_SCHEDULE.json',
              'TEMPORAL_PATTERN_VALIDATION.json', 'mechanism_expectations.json',
              'historical_208_reference.csv', 'historical_208_provenance.json',
              'DISPATCH_ORDER_DEFINITION.md')
    for name in frozen:
        copy(name)
        if sha(OUT / name) != sha(PRIOR / name):
            raise RuntimeError('Frozen pilot01 artifact copy mismatch: ' + name)
    if json.loads((OUT / 'STAGGERED_SCHEDULE.json').read_text())['phases'] != list(PHASES):
        raise RuntimeError('Pilot01 frozen phase tuple changed')
    state = cpu.snapshot()
    if len(state['policies']) != 7 or any(p['fields']['scaling_max_freq'] != '2601000' for p in state['policies']):
        raise RuntimeError('CPU topology/max differs from frozen control')
    for policy in state['policies']:
        policy['fields']['scaling_available_governors'] = (Path(policy['path']) / 'scaling_available_governors').read_text().strip()
    put('CPU_STATE_BEFORE.json', state)
    with (OUT / 'CPU_PIN_COMMANDS.sh').open('x') as stream:
        stream.write(render(state, restore=False))
    with (OUT / 'CPU_RESTORE_COMMANDS.sh').open('x') as stream:
        stream.write(render(state, restore=True))

    plan = dict(old)
    plan['order'] = order()
    plan['D100_pairs'] = [[f'V22_BLOCKA_D100_A{i}_P02', f'V22_BLOCKA_D100_S{i}_P02'] for i in (1, 2)]
    plan['attempt_namespace'] = 'block_a_phase_pilot02'
    plan['summary_adapter_ref'] = str((HERE / 'block_a_summary.py').relative_to(ROOT))
    plan['summary_adapter_sha256'] = sha(HERE / 'block_a_summary.py')
    plan['prior_failure_status'] = 'POST_RUN_SUMMARY_COMPATIBILITY_FAILURE'
    plan['prior_failure_reference'] = str((PRIOR / 'V22_BLOCKA_D100_S1_P01/summary.json').relative_to(ROOT))
    plan['prior_failure_reference_sha256'] = sha(PRIOR / 'V22_BLOCKA_D100_S1_P01/summary.json')
    plan['artifact_sha256'] = {name: sha(OUT / name) for name in old['artifact_sha256']}
    if plan['placement'] != old['placement'] or plan['idle_seconds'] != old['idle_seconds'] \
            or plan['deadlines_ms'] != old['deadlines_ms'] or plan['source_phase_ns'] != old['source_phase_ns'] \
            or plan['mechanism_expectations_verdict_effect'] != old['mechanism_expectations_verdict_effect']:
        raise RuntimeError('Pilot02 workload semantics differ')
    if hashlib.sha256(run_source().encode()).hexdigest() != old['frozen_worker_sha256']:
        raise RuntimeError('Frozen worker source changed')
    put('plan.json', plan)
    with (OUT / 'plan.sha256').open('x') as stream:
        stream.write(sha(PLAN) + '\n')
    source_paths = list(HERE.glob('*.py')) + [PILOT / 'phase_schedule.py', PILOT / 'pilot_fidelity.py',
                   PILOT.parent / 'timely_capacity_scan' / 'attempt02' / 'gpu_precheck.py']
    source_hashes = {str(path.relative_to(ROOT)): sha(path) for path in sorted(source_paths)}
    put('source_sha256.json', source_hashes)
    put('RUNTIME_SOURCE_PRESERVATION.json', {'frozen_V22_worker_SHA256': old['frozen_worker_sha256'],
        'actual_V22_worker_SHA256': hashlib.sha256(run_source().encode()).hexdigest(),
        'worker_byte_identical': True, 'pilot01_plan_SHA256': sha(PRIOR / 'plan.json'),
        'pilot02_plan_SHA256': sha(PLAN), 'summary_adapter_SHA256': sha(HERE / 'block_a_summary.py'),
        'source_SHA256': source_hashes})
    put('FROZEN_8_RUN_MANIFEST.json', {'plan_sha256': sha(PLAN), 'order': plan['order'],
        'historical_pilot01_runs_in_new_repeat_count': 0,
        'phase_search_rerun': False, 'frozen_phases': list(PHASES)})
    with (OUT / 'frozen_run_order.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=('order_index', 'run_id', 'deadline_ms',
                                'admission_pattern', 'repeat', 'target_service_FPS'))
        writer.writeheader()
        for row in plan['order']:
            writer.writerow({key: row[key] for key in writer.fieldnames})
    print(json.dumps({'prepared': True, 'plan_sha256': sha(PLAN),
                      'order': [row['run_id'] for row in plan['order']]}, indent=2))


if __name__ == '__main__':
    main()
