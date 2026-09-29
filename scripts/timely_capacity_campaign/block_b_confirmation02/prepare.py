"""CPU-only Confirmation02 freeze. No workload, network or clock writes."""
import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

import grid_config as c

sys.path.insert(0,str(c.HERE.parent/'common'/'service_phase_b1f'))
import cpu_state
from make_cpu_commands import render


def write(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False)
        stream.write('\n')


def text(path,value):
    with Path(path).open('x') as stream:stream.write(value)


def copy(source,target):
    with Path(source).open('rb') as src,Path(target).open('xb') as dst:
        dst.write(src.read())
    if c.sha(source)!=c.sha(target):raise RuntimeError('Bundle copy SHA mismatch')


def tree_hash(root):
    files={str(p.relative_to(root)):c.sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def mask_hash(mask):
    return hashlib.sha256(json.dumps(mask,separators=(',',':')).encode()).hexdigest()


def preregistration(selection,prior_plan_sha):
    return f"""# BLOCK_B_CONFIRMATION02 preregistration

This document is frozen **before any confirmation workload**. The 30 Grid02 measured runs are exploratory selection evidence only. Grid02's H1 verdict remains `H1_NOT_SUPPORTED`; the new 25 measured runs alone determine C1–C5. No confirmation outcome has been observed.

Confirmation01 was aborted before any workload because the CPU execution-state lifecycle was consumed during setup. No confirmation performance outcome was observed. Confirmation02 preserves the preregistered scientific design unchanged.

Research question: does the empirically selected placement-aware feasible configuration reproduce its stream-level deadline service and same-round advantages in an independent execution namespace?

Selection provenance: recomputed from every Grid02 active per-frame trace and cross-checked against `analysis01/per_run.csv`. At eta=0.99, all five repeats must have `worst_stream_TIR>=0.99`; among such Grid02 configurations, choose the highest Local assigned FPS. A tie at that rate must be reported as `MULTIPLE_CANDIDATES`. The exact recomputation artifact is `GRID02_SELECTION_RECOMPUTE.json` (SHA-256 {c.sha(c.OUT/'GRID02_SELECTION_RECOMPUTE.json')}). Its sole feasible cell and candidate are `{selection['candidate']}`. Grid02 plan SHA-256 is `{prior_plan_sha}`. This is exploratory selection, not formal Grid02 superiority.

The previously fixed scalar rule `lambda_L < mu_backlog_lower` is **rejected for candidate selection**: its 197-FPS conservative empirical lower envelope selected no tested rate. `mu_high`, backlog, and carry-over remain secondary descriptive diagnostics and cannot change C1–C5.

## Frozen conditions and controls

Five cells, each five repeats: L216A (216/24), L200A (200/40), L200S (200/40), L208S (208/32), L192S (192/48), where the two rates are Local/Edge FPS. K=8 synchronized streams ×30 FPS =240 source FPS; D=100 ms; measured active 60 s; warm-up L200S 15 s excluded. Local C_L=2, TRT B=1, GPU target 1575 MHz; Edge C_E=1, B=1, CUDA Graph OFF, dynamic batching OFF. Thor CPU seven policies performance/min=max=2601000 kHz during campaign; user restores schedutil/min=972000/max=2601000 kHz before analysis. Model, preprocess, RAW640 payload, protocol, pruning, queue, TensorRT/CUDA order and instrumentation are unchanged from Grid02. Source arrival timestamps remain fixed. Edge mask is the exact Local complement. ALIGNED uses phase zero; STAGGERED uses [0,1,2,3,4,5,6,7]. Minimum post-drain inter-session idle is 10 s. No retry, resume or overwrite.

## Exact 26-session order

Warm-up: `BCONF02_WARMUP_L200_S` (15 s, excluded). Measured 60-s runs, by round:

1. `BCONF02_L216_A1`, `BCONF02_L200_A1`, `BCONF02_L200_S1`, `BCONF02_L208_S1`, `BCONF02_L192_S1`
2. `BCONF02_L200_A2`, `BCONF02_L200_S2`, `BCONF02_L208_S2`, `BCONF02_L192_S2`, `BCONF02_L216_A2`
3. `BCONF02_L200_S3`, `BCONF02_L208_S3`, `BCONF02_L192_S3`, `BCONF02_L216_A3`, `BCONF02_L200_A3`
4. `BCONF02_L208_S4`, `BCONF02_L192_S4`, `BCONF02_L216_A4`, `BCONF02_L200_A4`, `BCONF02_L200_S4`
5. `BCONF02_L192_S5`, `BCONF02_L216_A5`, `BCONF02_L200_A5`, `BCONF02_L200_S5`, `BCONF02_L208_S5`

Each cell occupies each within-round ordinal position once. All comparisons below are same-round. Five-of-five engineering rules are not statistical significance tests.

## Primary rules, frozen at eta=0.99

- C1 L200S feasibility: `worst_stream_TIR(L200S_j)>=0.99` in all five runs → `L200S_FEASIBILITY_CONFIRMED`; otherwise `L200S_FEASIBILITY_NOT_CONFIRMED`.
- C2 temporal placement at L200: every round `TimelyFPS(L200S_j)>TimelyFPS(L200A_j)` **and** `WorstTIR(L200S_j)>=WorstTIR(L200A_j)` → `L200_TEMPORAL_EFFECT_CONFIRMED`; otherwise `L200_TEMPORAL_EFFECT_NOT_CONFIRMED`.
- C3 aggressive baseline: every round `TimelyFPS(L200S_j)>TimelyFPS(L216A_j)` **and** `WorstTIR(L200S_j)>=WorstTIR(L216A_j)` → `L200S_VS_L216A_CONFIRMED`; otherwise `L200S_VS_L216A_NOT_CONFIRMED`.
- C4 max-Local check: if L208S has `worst_stream_TIR>=0.99` in all five runs, `MAX_LOCAL_SELECTION_NOT_CONFIRMED`; otherwise `MAX_LOCAL_SELECTION_CONSISTENT`. This is no superiority claim.
- C5 lower-rate sensitivity: check L192S by the same five-of-five feasibility rule. If L200S and L192S both pass, report 40 versus 48 Edge-assigned FPS, an 8-FPS assignment difference. No equivalence, formal winner, or post-hoc ranking claim.

## Validity and descriptive evidence

Each run must have exact 14,400 source-frame IDs, Local XOR Edge, no duplicates/missing IDs, exact terminal accounting, zero unfinished after drain, GPU frequency restore PASS, Thor CPU pin before/after PASS, Edge protocol/integrity VALID, zero transport errors, and no automatic retry. Warm-up failure blocks measured runs; first measured INVALID stops the campaign. Network/setup/protocol failures are INVALID, never performance failures. CPU restore PASS and Edge raw collection precede analysis.

Descriptive outputs include total timely FPS/TIR, per-stream worst/best/gap, Local/Edge timely FPS and assigned TIR, Local queue/service/GPU stream span/host residual/concurrency, Edge offload wait/request-response/pending/server queue/inference, late/expired counts, OC3/temperature/frequency/CPU evidence, network TX and errors. L208S feasible-run count and timely-FPS spread are reported. An optional post-restore carry-over replay may report B_Q recoveries/HIGH seconds/end B_Q but cannot alter C1–C5. Thor VIN 60-s active-window energy is optional descriptive evidence; it excludes Edge energy and full-run energy, and missing energy does not invalidate service results.
"""


def main():
    out=c.OUT
    if (out/'plan.json').exists() or (out/'campaign_attempt.json').exists():
        raise RuntimeError('Confirmation02 namespace already frozen/consumed')
    if any((out/name).exists() for name in ('NETWORK_REACHABILITY_CHECK.json',
            'CPU_PIN_READBACK.json','CPU_RESTORE_READBACK.json',
            'EDGE_LISTENER_READY_CONFIRMATION.json','operator_evidence')):
        raise RuntimeError('Confirmation02 pre-execution namespace is not fresh')
    selection=json.loads((out/'GRID02_SELECTION_RECOMPUTE.json').read_text())
    if selection.get('status')!='PASS' or selection.get('candidate')!='L200S' or selection.get('eta')!=.99:
        raise RuntimeError('Grid02 candidate is not L200S; STOP preparation')
    root=out.parent;grid02=root/'block_b_grid02'
    confirmation01=root/'block_b_confirmation01'
    abort=json.loads((confirmation01/'SETUP_ABORT_BEFORE_WORKLOAD.json').read_text())
    old_confirmation_plan_sha=c.sha(confirmation01/'plan.json')
    old_confirmation_order=json.loads((confirmation01/'session_plan.json').read_text())['order']
    if abort.get('status')!='SETUP_ABORTED_BEFORE_WORKLOAD' or \
            abort.get('plan_sha256')!=old_confirmation_plan_sha or \
            abort.get('actual_workload_executed') is not False or \
            abort.get('warmup_executed') is not False or \
            abort.get('measured_sessions_executed')!=0 or \
            abort.get('confirmation_outcome_observed') is not False or \
            (confirmation01/'campaign_attempt.json').exists() or \
            any((confirmation01/row['run_id']).exists() for row in old_confirmation_order):
        raise RuntimeError('Confirmation01 setup-abort provenance does not prove zero workloads')
    write(out/'CONFIRMATION01_ABORT_REFERENCE.json',{
        'status':'SETUP_ABORTED_BEFORE_WORKLOAD',
        'Confirmation01_plan_sha256':old_confirmation_plan_sha,
        'Confirmation01_preregistration_sha256':c.sha(confirmation01/'CONFIRMATION_PREREGISTRATION.md'),
        'Confirmation01_abort_record_sha256':c.sha(confirmation01/'SETUP_ABORT_BEFORE_WORKLOAD.json'),
        'child_workload_sessions':0,'warmup_sessions':0,'measured_sessions':0,
        'confirmation_performance_outcome_observed':False,
        'Confirmation01_not_reused':True})
    old_plan=json.loads((grid02/'plan.json').read_text())
    if json.loads((grid02/'analysis01/H1_summary.json').read_text())['verdict']!='H1_NOT_SUPPORTED':
        raise RuntimeError('Grid02 H1 changed')
    protected=[root/name for name in ('block_b_grid01','block_b_grid02',
        'block_b_confirmation01',
        'edge_order_robustness01','block_a_phase_pilot01','block_a_phase_pilot02')]
    before={str(p):tree_hash(p) for p in protected}
    prior_masks=json.loads((grid02/'BLOCK_B_MASK_MANIFEST.json').read_text())
    manifest={};reuse={}
    for rate,token in c.CONDITIONS:
        label=f'L{rate}{token}';pattern='ALIGNED' if token=='A' else 'STAGGERED'
        mask=c.masks(rate,pattern)
        mask['local_mask_sha256']=mask_hash(mask['local_masks'])
        mask['edge_mask_sha256']=mask_hash(mask['edge_masks'])
        if label in prior_masks:
            prior=prior_masks[label]
            matching=(json.loads(json.dumps(mask))==prior)
            reuse[label]={'Grid02_mask_sha256':prior['local_mask_sha256'],
                'Confirmation02_mask_sha256':mask['local_mask_sha256'],
                'Grid02_mask_entry_sha256':mask_hash(prior),
                'Confirmation02_mask_entry_sha256':mask_hash(mask),
                'status':'PASS' if matching else 'FAIL'}
            if not matching:raise RuntimeError('Reused Grid02 mask changed: '+label)
        manifest[label]=mask
    reuse['L192S']={'status':'NEW_P24_SAME_CANONICAL_FLOOR_RULE'}
    write(out/'REUSED_MASK_EQUALITY.json',reuse)
    write(out/'CONFIRMATION_MASK_MANIFEST.json',manifest)
    write(out/'ASSIGNMENT_COUNTS.json',{
        label:{'Local_per_stream_30':mask['local_count_per_stream_per_30'][0],
               'Edge_per_stream_30':mask['edge_count_per_stream_per_30'][0],
               'Local_60s':rate*60,'Edge_60s':(240-rate)*60,
               'Local_slot_peak':max(mask['m_L']),'Edge_slot_peak':max(mask['m_E']),
               'Local_mask_sha256':mask['local_mask_sha256'],'Edge_mask_sha256':mask['edge_mask_sha256']}
        for label,mask in manifest.items() for rate in [int(label[1:4])]})
    write(out/'session_plan.json',{'stage':'CONFIRMATION','order':c.order(),
        'warmup_index':0,'measured_indices':list(range(1,26)),
        'warmup':'15s L200S, excluded from C1-C5',
        'first_INVALID':'stop; no retry/resume/overwrite'})
    prior_sha=c.sha(grid02/'plan.json')
    text(out/'CONFIRMATION_PREREGISTRATION.md',preregistration(selection,prior_sha))
    endpoint=json.loads((grid02/'EDGE_ENDPOINT_MANIFEST.json').read_text())
    if endpoint['edge_ip']!='192.168.0.6':
        raise RuntimeError('Frozen reference endpoint changed; operator must verify live')
    write(out/'EDGE_ENDPOINT_MANIFEST.json',endpoint)
    state=cpu_state.snapshot()
    if len(state['policies'])!=7 or any(
        row['fields'].get('scaling_governor')!='schedutil' or
        row['fields'].get('scaling_min_freq')!='972000' or
        row['fields'].get('scaling_max_freq')!='2601000' for row in state['policies']):
        raise RuntimeError('Expected seven restored 972000..2601000 schedutil CPU policies')
    for row in state['policies']:
        row['fields']['scaling_available_governors']=(Path(row['path'])/'scaling_available_governors').read_text().strip()
    write(out/'CPU_STATE_BEFORE.json',state)
    text(out/'CPU_PIN_COMMANDS.sh',render(state,restore=False))
    text(out/'CPU_RESTORE_COMMANDS.sh',render(state,restore=True))
    copy(grid02/'BLOCK_B_ENERGY_SOURCE_MANIFEST.json',out/'BLOCK_B_ENERGY_SOURCE_MANIFEST.json')
    bundle=out/'edge_bundle';bundle.mkdir(exist_ok=False)
    old_bundle=grid02/'edge_bundle';deps={}
    for name in ('formal_protocol.py','formal_server.py','profile_edge_concurrency.py','pruning_edge_server.py'):
        copy(old_bundle/name,bundle/name);deps[name]=c.sha(bundle/name)
    server=c.HERE/'edge_server_grid02.py'
    copy(server,bundle/server.name);deps[server.name]=c.sha(server)
    source_names=[c.HERE/name for name in ('grid_config.py','block_b_summary.py','run_thor.py',
        'validate.py','analyze.py','prepare.py','edge_server_grid02.py',
        'select_candidate.py','confirmation_rules.py','mechanism_after.py','test_cpu.py')]
    source_names += [c.ROOT/'scripts/timely_capacity_campaign/common/dispatch_observation.py',
                     c.ROOT/'scripts/timely_capacity_campaign/common/campaign_config.py']
    sources={str(path.relative_to(c.ROOT)):c.sha(path) for path in source_names}
    write(out/'source_sha256.json',sources)
    worker_sha=hashlib.sha256(c.run_source().encode()).hexdigest()
    if worker_sha!=old_plan['frozen_worker_sha256']:
        raise RuntimeError('Frozen V2.2 worker changed')
    write(out/'CONFIRMATION_RUNTIME_MANIFEST.json',{
        'V22_worker_SHA256':worker_sha,'Grid02_V22_worker_SHA256':old_plan['frozen_worker_sha256'],
        'worker_byte_identical':True,'Local_C':2,'Local_B':1,'GPU_target_MHz':1575,
        'Edge_C':1,'Edge_B':1,'CUDA_Graph':False,'dynamic_batching':False,
        'K':8,'source_FPS_per_stream':30,'deadline_ms':100,
        'measured_seconds':60,'warmup_seconds':15,'idle_seconds':10,
        'CPU_policies':7,'CPU_pinned_governor':'performance','CPU_pinned_min_max_kHz':2601000,
        'CPU_restore_governor':'schedutil','CPU_restore_min_kHz':972000,
        'CPU_restore_max_kHz':2601000,
        'engine_SHA256':old_plan['edge_engine_SHA256'],
        'no_runtime_or_hot_path_change':True})
    plan=dict(old_plan)
    plan.update(campaign='BLOCK_B_CONFIRMATION02',freeze_status='PREPARED_NOT_EXECUTED',
        frozen_utc=datetime.now(timezone.utc).isoformat(),
        order=c.order(),smoke=[],deadlines_ms=[100],source_phase_ns=[0]*8,
        idle_seconds=10,network_interface='wlP1p1s0',edge_host=endpoint['edge_ip'],
        placement=manifest,attempt_namespace='block_b_confirmation02',
        frozen_worker_sha256=worker_sha,
        source_sha256={**old_plan['source_sha256'],**sources},
        edge_dependency_sha256=deps,
        session_plan_sha256={'session_plan.json':c.sha(out/'session_plan.json')},
        endpoint_manifest_sha256=c.sha(out/'EDGE_ENDPOINT_MANIFEST.json'),
        previous_grid02_plan_sha256=prior_sha,
        previous_confirmation01_plan_sha256=old_confirmation_plan_sha,
        confirmation01_setup_abort_sha256=c.sha(confirmation01/'SETUP_ABORT_BEFORE_WORKLOAD.json'),
        scientific_design_equal_to_confirmation01=True,
        Grid02_H1_unchanged='H1_NOT_SUPPORTED',
        exploratory_selection={'eta':.99,'candidate':'L200S',
            'source':'Grid02 raw 30 measured runs; worst-stream TIR five-of-five',
            'recompute_sha256':c.sha(out/'GRID02_SELECTION_RECOMPUTE.json')},
        preregistration_sha256=c.sha(out/'CONFIRMATION_PREREGISTRATION.md'),
        confirmation_rules_sha256=c.sha(c.HERE/'confirmation_rules.py'),
        mu_backlog_lower_selection_use=False,
        artifact_sha256={name:c.sha(out/name) for name in (
            'GRID02_SELECTION_RECOMPUTE.json','REUSED_MASK_EQUALITY.json',
            'CONFIRMATION_MASK_MANIFEST.json','ASSIGNMENT_COUNTS.json',
            'CONFIRMATION_PREREGISTRATION.md','CONFIRMATION_RUNTIME_MANIFEST.json',
            'CPU_STATE_BEFORE.json','EDGE_ENDPOINT_MANIFEST.json',
            'BLOCK_B_ENERGY_SOURCE_MANIFEST.json','CONFIRMATION01_ABORT_REFERENCE.json')},
        no_TCP_preflight_probe=True,
        energy_status='Thor VIN active-window only if coverage validates; no energy-based performance validity gate')
    # Remove prior campaign's frozen interpretation/prediction hooks; the new
    # preregistration and pure C1-C5 module are the confirmation source of truth.
    for key in ('interpretation','stop','allowed_scope','mechanism_expectations_verdict_effect',
                'timely_rule'):
        plan.pop(key,None)
    write(out/'plan.json',plan)
    text(out/'plan.sha256',c.sha(out/'plan.json')+'\n')
    for name in ('plan.json','session_plan.json'):copy(out/name,bundle/name)
    with (bundle/'SHA256SUMS').open('x') as stream:
        for path in sorted(p for p in bundle.iterdir() if p.name!='SHA256SUMS'):
            stream.write(c.sha(path)+'  '+path.name+'\n')
    after={str(p):tree_hash(p) for p in protected}
    write(out/'preservation.json',{'status':'PASS' if before==after else 'FAIL',
        'protected_tree_sha256_before':before,'protected_tree_sha256_after':after,
        'protected_namespaces':[p.name for p in protected],
        'Grid02_H1':'H1_NOT_SUPPORTED'})
    if before!=after:raise RuntimeError('Protected result namespace changed')
    print(json.dumps({'status':'PREPARED','candidate':'L200S','eta':.99,
        'plan_sha256':c.sha(out/'plan.json'),
        'preregistration_sha256':c.sha(out/'CONFIRMATION_PREREGISTRATION.md'),
        'sessions':len(c.order()),'reused_masks':reuse,'L192S':manifest['L192S']['local_mask_sha256'],
        'preservation':'PASS'},indent=2))


if __name__=='__main__':main()
