"""CPU-only Block B freeze, prior-mask replay and protected-artifact hashes."""
import csv
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import grid_config as c

sys.path.insert(0, str(c.HERE.parent / 'common' / 'service_phase_b1f'))
import cpu_state
from make_cpu_commands import render


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def copy(source, target):
    with Path(source).open('rb') as src, Path(target).open('xb') as dst:
        dst.write(src.read())
    if c.sha(source) != c.sha(target):
        raise RuntimeError('Edge bundle copy SHA mismatch')


def tree_hash(root):
    files = {str(p.relative_to(root)): c.sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def mask_hash(mask):
    return hashlib.sha256(json.dumps(mask, separators=(',',':')).encode()).hexdigest()


def actual_prior_mask(path):
    seen = {}
    with gzip.open(path, 'rt', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['phase'] != 'active': continue
            sid, frame = int(row['stream_id']), int(row['frame_id'])
            if frame >= 30: continue
            if (sid,frame) in seen: raise RuntimeError('Duplicate prior source ID')
            seen[sid,frame] = int(row['placement'] == 'LOCAL')
    if len(seen) != 240: raise RuntimeError('Prior first-period source universe incomplete')
    return [[seen[sid,frame] for frame in range(30)] for sid in range(8)]


def prior_match():
    refs = {
        'L208A': 'block_a_phase_pilot02/V22_BLOCKA_D100_A1_P02',
        'L208S': 'block_a_phase_pilot02/V22_BLOCKA_D100_S1_P02',
        'L216A': 'timely_capacity_scan02/V22_TIMELY_D100_R1_L216_P01',
        'L200A': 'timely_capacity_scan02/V22_TIMELY_D100_R1_L200_P01',
    }
    root = c.ROOT / 'results/timely_capacity_campaign/v2_2'
    out = {}
    for label, relative in refs.items():
        path = root / relative / 'per_frame.csv.gz'
        rate = int(label[1:4]); pattern = 'ALIGNED' if label.endswith('A') else 'STAGGERED'
        old, new = actual_prior_mask(path), c.masks(rate,pattern)['local_masks']
        out[label] = {'source_artifact':str(path.relative_to(c.ROOT)),
                      'source_sha256':c.sha(path), 'prior_run_id':path.parent.name,
                      'prior_mask_hash':mask_hash(old),'new_mask_hash':mask_hash(new),
                      'status':'PASS' if old==new else 'FAIL'}
    out['L216S'] = {'status':'NO_DIRECT_MATCHED_PRIOR'}
    out['L200S'] = {'status':'NO_DIRECT_MATCHED_PRIOR'}
    if any(out[label]['status']!='PASS' for label in refs):
        raise RuntimeError('BLOCK_B_PRIOR_MASK_MISMATCH_REVIEW_REQUIRED')
    return out


def main():
    out = c.OUT
    if any((out/name).exists() for name in ('plan.json','campaign_attempt.json')):
        raise RuntimeError('Block B namespace already frozen/consumed')
    base = c.ROOT/'results/timely_capacity_campaign/v2_2'
    prior_roots = [base/name for name in ('block_a_phase_pilot02','timely_capacity_scan02',
                    'edge_e48_confirmation01','edge_preflight_final02',
                    'edge_order_robustness01','block_b_grid01')]
    before = {str(p):tree_hash(p) for p in prior_roots}
    grid01 = base/'block_b_grid01'
    old_plan_sha = c.sha(grid01/'plan.json')
    if old_plan_sha != '6766c351b0dcb3ecdab439d5e20f4bb108e3c1207ac23ecdaef491496a870db7':
        raise RuntimeError('Grid01 failure provenance plan changed')
    write(out/'GRID01_FAILURE_PROVENANCE.json', {
        'previous_plan_sha256':old_plan_sha,
        'failed_run_id':'BLOCKB01_WARMUP_L200_E40_S',
        'Grid01_verdict':'INVALID',
        'diff_reason':'POST_DRAIN_SUMMARY_RATE_SUPPORT_FIX_ONLY',
        'scientific_condition_diff':'NONE',
        'Grid01_summary_sha256':c.sha(grid01/'BLOCKB01_WARMUP_L200_E40_S/summary.json'),
        'Grid01_raw_sha256':c.sha(grid01/'BLOCKB01_WARMUP_L200_E40_S/per_frame.csv.gz'),
        'Grid01_namespace_preservation':'READ_ONLY'})
    old = json.loads((base/'block_a_phase_pilot02/plan.json').read_text())
    endpoint = json.loads((base/'edge_e48_confirmation01/EDGE_ENDPOINT_MANIFEST.json').read_text())
    if endpoint['edge_ip'] != '192.168.0.6':
        raise RuntimeError('Frozen endpoint differs from prior; operator must verify live endpoint again')
    write(out/'EDGE_ENDPOINT_MANIFEST.json', endpoint)
    prior = prior_match()
    write(out/'BLOCK_B_PRIOR_MASK_MATCH.json', prior)
    manifest = {}
    for rate in c.RATES:
        for pattern in ('ALIGNED','STAGGERED'):
            name = f'L{rate}'+('A' if pattern=='ALIGNED' else 'S')
            entry = c.masks(rate,pattern)
            entry['local_mask_sha256'] = mask_hash(entry['local_masks'])
            entry['edge_mask_sha256'] = mask_hash(entry['edge_masks'])
            manifest[name] = entry
    if [manifest[f'L{r}S']['edge_peak'] for r in c.RATES] != [1,2,2]:
        raise RuntimeError('BLOCK_B_SLOT_SHAPE_REVIEW_REQUIRED')
    write(out/'BLOCK_B_MASK_MANIFEST.json', manifest)
    write(out/'BLOCK_B_SPLIT_MANIFEST.json', {
        'source':'K8 x 30 FPS synchronized, 240 FPS total',
        'source_due':'active_start_ns+floor(frame_index*1e9/30)',
        'Local':'canonical floor p27/p26/p25; shifted p[(n-k)%30] for STAGGERED',
        'Edge':'exact Boolean complement of Local',
        'source_frames_per_stream_60s':1800,'total_source_frames_60s':14400,
        'counts_60s':{str(rate):{'Local_per_stream':rate//8*60,
                                  'Edge_per_stream':(240-rate)//8*60} for rate in c.RATES},
        'phase_vector':[0,1,2,3,4,5,6,7], 'dispatch_order':'canonical stream 0..7 per path/slot; no REVERSE/ROTATE',
        'Local_XOR_Edge':True,'no_deferred_admission':True})
    write(out/'BLOCK_B_POLICY_HYPOTHESIS.json', {
        'H1':'same-round L208S timely FPS > L216A AND worst-stream TIR >= L216A; 5/5 required',
        'H1_supported':'all five rounds satisfy both inequalities',
        'L208S_provenance':'block_a_phase_pilot02 D100 STAGGERED 208, TIR 1.0/1.0; highest tested feasible Local rate',
        'L200A_provenance':'timely_capacity_scan02 D100 ALIGNED 200; highest tested 2/2 feasible Local rate',
        'limitations':'engineering paired rule, no significance/global-optimum claim'})
    copy(base/'block_b_grid01/mechanism_expectations.json',out/'mechanism_expectations.json')
    write(out/'session_plan.json', {'stage':'GRID','order':c.order(),'warmup_index':0,
        'measured_indices':list(range(1,31)), 'warmup':'15s L200E40 STAGGERED; excluded',
        'first_INVALID':'stop; no retry/resume/overwrite'})
    state = cpu_state.snapshot()
    if len(state['policies'])!=7 or any(row['fields']['scaling_max_freq']!='2601000' for row in state['policies']):
        raise RuntimeError('Seven 2601000-kHz CPU policies required')
    for row in state['policies']:
        row['fields']['scaling_available_governors']=(Path(row['path'])/'scaling_available_governors').read_text().strip()
    write(out/'CPU_STATE_BEFORE.json',state)
    for name,restore in (('CPU_PIN_COMMANDS.sh',False),('CPU_RESTORE_COMMANDS.sh',True)):
        with (out/name).open('x') as stream:stream.write(render(state,restore=restore))
    write(out/'BLOCK_B_ENERGY_SOURCE_MANIFEST.json', {
        'status':'THOR_VIN_ACTIVE_SOURCE_VERIFIED_RUN_SCOPE_REVIEW_REQUIRED',
        'field':'VIN first instantaneous mW before slash in raw_tegrastats',
        'parser_source':'scripts/equal_service_map/analyze_map.py::rail_integrals',
        'trace_source':'power_trace.csv.gz from V2.2 tegrastats collector',
        'unit_conversion':'mW / 1000 = W', 'requested_sampling_interval_ms':100,
        'timestamp':'host time.monotonic_ns() on sample receipt',
        'integration':'endpoint-interpolated trapezoidal integration over active window; reject >0.5s gaps',
        'prior_provenance':'results/equal_service_map/POWER_SCOPE_AUDIT.md',
        'scope':'Thor module+carrier VIN input; Edge excluded; no rail summation',
        'limitation':'Frozen V2.2 trace ends near active end before all drain/cleanup; E_run_J cannot be asserted without separate scope validation. No extrapolation.'})
    bundle = out/'edge_bundle';bundle.mkdir(exist_ok=False)
    old_bundle = base/'edge_e48_confirmation01/edge_bundle'
    deps = {}
    for name in ('formal_protocol.py','formal_server.py','profile_edge_concurrency.py','pruning_edge_server.py'):
        copy(old_bundle/name,bundle/name);deps[name]=c.sha(bundle/name)
    server = c.HERE/'edge_server_grid02.py'
    copy(server,bundle/server.name);deps[server.name]=c.sha(server)
    source_names = [c.HERE/name for name in ('grid_config.py','block_b_summary.py','run_thor.py',
                                               'validate.py','analyze.py','prepare.py','edge_server_grid02.py',
                                               'test_cpu.py','replay_grid01.py')]
    source_names += [c.ROOT/'scripts/timely_capacity_campaign/common/dispatch_observation.py',
                     c.ROOT/'scripts/timely_capacity_campaign/common/campaign_config.py']
    source = {str(path.relative_to(c.ROOT)):c.sha(path) for path in source_names}
    write(out/'source_sha256.json',source)
    plan = dict(old)
    plan.update(campaign='BLOCK_B_GRID02', freeze_status='PREPARED_NOT_EXECUTED',
        frozen_utc=datetime.now(timezone.utc).isoformat(),
        order=c.order(),smoke=[],deadlines_ms=[100],source_phase_ns=[0]*8,
        idle_seconds=10,network_interface='wlP1p1s0',edge_host=endpoint['edge_ip'],
        placement=manifest,attempt_namespace='block_b_grid02',
        frozen_worker_sha256=hashlib.sha256(c.run_source().encode()).hexdigest(),
        source_sha256={**old['source_sha256'],**source},
        edge_dependency_sha256=deps,
        session_plan_sha256={'session_plan.json':c.sha(out/'session_plan.json')},
        edge_engine_SHA256=json.loads((base/'edge_e48_confirmation01/plan.json').read_text())['edge_engine_SHA256'],
        endpoint_manifest_sha256=c.sha(out/'EDGE_ENDPOINT_MANIFEST.json'),
        artifact_sha256={name:c.sha(out/name) for name in
            ('BLOCK_B_MASK_MANIFEST.json','BLOCK_B_SPLIT_MANIFEST.json','BLOCK_B_PRIOR_MASK_MATCH.json',
             'BLOCK_B_POLICY_HYPOTHESIS.json','mechanism_expectations.json',
             'BLOCK_B_ENERGY_SOURCE_MANIFEST.json','CPU_STATE_BEFORE.json',
             'GRID01_FAILURE_PROVENANCE.json')},
        no_TCP_preflight_probe=True,
        energy_status='Thor VIN active source verified; full-run energy coverage review required')
    # Old Block-A-specific fields would otherwise be misleading in a new plan.
    for key in ('D100_pairs','historical_208_use','summary_adapter_ref','summary_adapter_sha256',
                'prior_failure_status','prior_failure_reference','prior_failure_reference_sha256'):
        plan.pop(key,None)
    write(out/'plan.json',plan)
    with (out/'plan.sha256').open('x') as stream:stream.write(c.sha(out/'plan.json')+'\n')
    for name in ('plan.json','session_plan.json'):
        copy(out/name,bundle/name)
    with (bundle/'SHA256SUMS').open('x') as stream:
        for path in sorted(p for p in bundle.iterdir() if p.name != 'SHA256SUMS'):
            stream.write(c.sha(path)+'  '+path.name+'\n')
    after = {str(p):tree_hash(p) for p in prior_roots}
    write(out/'preservation.json',{'status':'PASS' if before==after else 'FAIL',
        'protected_tree_sha256_before':before,'protected_tree_sha256_after':after})
    if before!=after:raise RuntimeError('Protected results changed')
    print(json.dumps({'plan_sha256':c.sha(out/'plan.json'),'sessions':len(c.order()),
        'prior_masks':{k:v['status'] for k,v in prior.items()},
        'distributed_E_peaks':[manifest[f'L{r}S']['edge_peak'] for r in c.RATES],
        'energy_scope':'RUN_ENERGY_REVIEW_REQUIRED'},indent=2))


if __name__=='__main__':main()
