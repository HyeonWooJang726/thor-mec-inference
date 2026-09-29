"""CPU-only, exclusive-create freeze; never starts an inference/network workload."""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import config

sys.path.insert(0,str(config.HERE.parent/'common'/'service_phase_b1f'))
import cpu_state
from make_cpu_commands import render

ROOT,OUT=config.ROOT,config.OUT


def put(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False)
        stream.write('\n')


def copy(source,target):
    with Path(source).open('rb') as inp,Path(target).open('xb') as out:
        shutil.copyfileobj(inp,out)
    if config.sha(source)!=config.sha(target):raise RuntimeError('Copy hash drift')


def selected_protected_hashes():
    base=ROOT/'results/timely_capacity_campaign/v2_2'
    names=('edge_inflight_robustness01','edge_e48_confirmation01','edge_order_robustness01',
           'block_b_grid02','block_b_confirmation01','block_b_confirmation02',
           'local_inflight_calibration01','local_inflight_calibration02',
           'local_inflight_calibration03','local_inflight_calibration04',
           'local_inflight_calibration05')
    result={}
    for name in names:
        root=base/name
        if not root.is_dir(): raise RuntimeError('Protected root absent: '+name)
        files=[p for p in (root/'plan.json',root/'plan.sha256',root/'analysis01/per_run.csv',
                            root/'campaign_attempt.json') if p.is_file()]
        result[name]={str(p.relative_to(root)):config.sha(p) for p in files}
    return result


def historical_c2_readiness(engine_sha):
    root=ROOT/'results/edge_raw_capacity_gate/edge_concurrency_run02'
    evidence=[]
    for name in ('C2_R1','C2_R2','C8_R1','C8_R2'):
        manifest=json.loads((root/name/'manifest.json').read_text())
        summary=json.loads((root/name/'summary.json').read_text())
        resources=manifest['resources']
        c=int(name.split('_')[0][1:])
        contexts=[r['context_object_id'] for r in resources]
        streams=[r['cuda_stream_pointer'] for r in resources]
        valid=(summary['integrity_status']=='VALID' and summary['clean_shutdown'] is True
               and manifest['engine_sha256']==engine_sha and len(resources)==c
               and len(set(contexts))==len(set(streams))==c)
        evidence.append({'run':name,'status':'PASS' if valid else 'FAIL',
            'summary_sha256':config.sha(root/name/'summary.json'),
            'manifest_sha256':config.sha(root/name/'manifest.json'),
            'contexts':len(contexts),'streams':len(streams),
            'same_frozen_engine':manifest['engine_sha256']==engine_sha})
    return {'status':'PASS' if all(r['status']=='PASS' for r in evidence) else 'FAIL',
            'scope':'Historical identical-engine C2/C8 TensorRT context/stream construction and cleanup. Current free VRAM is not observed; Edge operator must verify read-only immediately before launch.',
            'evidence':evidence}


def main():
    if (OUT/'plan.json').exists() or (OUT/'campaign_attempt.json').exists():
        raise RuntimeError('Already frozen or consumed')
    before=selected_protected_hashes()
    old=ROOT/'results/timely_capacity_campaign/v2_2/edge_e48_confirmation01'
    old_plan=json.loads((old/'plan.json').read_text())
    cache=old_plan['cache']
    if config.sha(ROOT/cache['path'])!=cache['sha256']:
        raise RuntimeError('RAW640 cache SHA drift')
    old_pattern=json.loads((old/'E48_RATE_PATTERN.json').read_text())['schedules']
    for pattern in ('ALIGNED','STAGGERED'):
        if config.schedule(pattern)['per_stream_masks']!=old_pattern[pattern]['per_stream_masks']:
            raise RuntimeError('E48 mask differs from prior')
    order=config.frozen_order()
    if len(order)!=8 or len({r['run_id'] for r in order})!=8:
        raise RuntimeError('Expected exact eight distinct runs')
    stages=[]
    for number,(start,end,c_e) in enumerate(((0,2,1),(2,6,2),(6,8,1)),1):
        stages.append({'stage':number,'start_index':start,'end_index':end,
                       'C_E':c_e,'run_ids':[r['run_id'] for r in order[start:end]],
                       'boundary_after':'STAGE_COMPLETE_WAITING_FOR_EDGE_RESTART' if number<3 else 'CAMPAIGN_COMPLETE'})
    session={'order':order,'stages':stages,'method':'METHOD_B_PROCESS_RESTART',
             'first_INVALID':'Stop remaining runs; no retry/resume/overwrite'}
    put(OUT/'session_plan.json',session)
    endpoint={'hostname':'CY415AINET','edge_ip':old_plan['edge_ip'],
              'thor_ip':'192.168.0.189','inference_port':5000,
              'provenance':'Last frozen E48 endpoint; operator must verify live Edge endpoint before pin',
              'frozen_utc':datetime.now(timezone.utc).isoformat(),
              'route':'Thor route hard; neighbor/ICMP diagnostic only; no TCP readiness probe'}
    put(OUT/'EDGE_ENDPOINT_MANIFEST.json',endpoint)
    state=cpu_state.snapshot()
    if len(state['policies'])!=7 or any(r['fields']['scaling_max_freq']!='2601000' for r in state['policies']):
        raise RuntimeError('Seven 2601000-kHz CPU policies required')
    for row in state['policies']:
        row['fields']['scaling_available_governors']=(Path(row['path'])/'scaling_available_governors').read_text().strip()
    put(OUT/'CPU_STATE_BEFORE.json',state)
    for name,restore in (('CPU_PIN_COMMANDS.sh',False),('CPU_RESTORE_COMMANDS.sh',True)):
        with (OUT/name).open('x') as stream:stream.write(render(state,restore=restore))
    memory=historical_c2_readiness(old_plan['edge_engine_SHA256'])
    put(OUT/'C_E2_MEMORY_READINESS.json',memory)
    if memory['status']!='PASS':raise RuntimeError('C_E2 historical resource readiness FAIL')
    bundle=OUT/'edge_bundle';bundle.mkdir(exist_ok=False)
    deps={}
    for name in ('formal_protocol.py','formal_server.py','profile_edge_concurrency.py',
                 'pruning_edge_server.py'):
        copy(old/'edge_bundle'/name,bundle/name)
        deps[name]=config.sha(bundle/name)
    copy(config.HERE/'edge_server.py',bundle/'edge_server.py')
    deps['edge_server.py']=config.sha(bundle/'edge_server.py')
    copy(config.HERE/'edge_local_preflight.py',bundle/'edge_local_preflight.py')
    deps['edge_local_preflight.py']=config.sha(bundle/'edge_local_preflight.py')
    canonical=json.dumps(deps,sort_keys=True,separators=(',',':')).encode()
    bundle_sha=hashlib.sha256(canonical).hexdigest()
    source_names=[str(p.relative_to(ROOT)) for p in (
        config.HERE/'config.py',config.HERE/'run_thor.py',config.HERE/'analyze.py',
        config.HERE/'edge_server.py',config.HERE/'edge_local_preflight.py',
        config.HERE/'verify_edge_preflight.py',config.HERE/'regression_cpu.py',
        config.HERE/'audit_existing.py',config.HERE/'prepare.py',
        config.HERE.parent/'edge_e48_confirmation01/config.py',
        ROOT/'scripts/hybrid_capacity_extension/edge_link.py',
        ROOT/'scripts/expired_work_pruning/pruning_common.py')]
    source={name:config.sha(ROOT/name) for name in source_names}
    put(OUT/'source_sha256.json',source)
    plan={'campaign':'EDGE_INFLIGHT_ROBUSTNESS02','freeze_status':'WAITING_FOR_REAL_EDGE_PREFLIGHT',
          'previous_failed_attempt':'edge_inflight_robustness01',
          'previous_plan_sha256':config.sha(ROOT/'results/timely_capacity_campaign/v2_2/edge_inflight_robustness01/plan.json'),
          'runtime_fix':'Bind helpers.trt to imported TensorRT module before ContextWorker construction',
          'real_edge_preflight_required_before_check_and_stage1':True,
          'question':'Is E48 ALIGNED timely loss materially sensitive to C_E=1 serialization?',
          'local_C_L_frozen_for_later_main_work':3,
          'K':8,'source_FPS_per_stream':30,'rate':48,'deadline_ms':100,
          'active_seconds':30,'idle_seconds':config.IDLE_SECONDS,
          'payload_bytes':config.PAYLOAD_BYTES,'B':1,
          'phase_vector_staggered':list(range(8)),
          'ALIGNED_mask':config.schedule('ALIGNED')['per_stream_masks'],
          'STAGGERED_mask':config.schedule('STAGGERED')['per_stream_masks'],
          'cache':cache,'edge_engine_SHA256':old_plan['edge_engine_SHA256'],
          'edge_host':endpoint['edge_ip'],'edge_ip':endpoint['edge_ip'],'edge_port':5000,
          'endpoint_manifest_sha256':config.sha(OUT/'EDGE_ENDPOINT_MANIFEST.json'),
          'order':order,'stages':stages,'session_plan_sha256':config.sha(OUT/'session_plan.json'),
          'server_configuration_method':'METHOD_B_PROCESS_RESTART',
          'server_warmup_per_worker':50,
          'edge_dependency_sha256':deps,
          'bundle_sha256':bundle_sha,
          'bundle_sha_definition':'SHA256 of canonical sorted JSON edge_dependency_sha256 map; excludes plan/session to avoid self-reference. SHA256SUMS verifies complete assembled bundle.',
          'preregistration_sha256':config.sha(OUT/'EDGE_INFLIGHT_PREREGISTRATION.md'),
          'source_sha256':source,
          'C_E2_historical_readiness_sha256':config.sha(OUT/'C_E2_MEMORY_READINESS.json'),
          'primary_delta':'TIR(CE2,ALIGNED,j)-TIR(CE1,ALIGNED,j)',
          'primary_rule':{'both_ge_absolute_0.10':'EDGE_BURST_CONCURRENCY_SENSITIVE; C_E_selected=2',
                          'both_lt_absolute_0.10':'EDGE_BURST_CONCURRENCY_ROBUST; C_E_selected=1',
                          'split':'EDGE_C_REPEAT_AMBIGUOUS; C_E_selected=null'},
          'STAGGERED_role':'supporting mechanism only; not C_E selection',
          'no_TCP_probe':True,'no_retry_resume_overwrite':True}
    put(OUT/'plan.json',plan)
    with (OUT/'plan.sha256').open('x') as stream:stream.write(config.sha(OUT/'plan.json')+'\n')
    for name in ('plan.json','session_plan.json'):
        copy(OUT/name,bundle/name)
    with (bundle/'SHA256SUMS').open('x') as stream:
        for path in sorted(p for p in bundle.iterdir() if p.is_file() and p.name!='SHA256SUMS'):
            stream.write(config.sha(path)+'  '+path.name+'\n')
    (OUT/'edge_preflight_evidence').mkdir(exist_ok=False)
    after=selected_protected_hashes()
    put(OUT/'preservation.json',{'status':'PASS' if before==after else 'FAIL',
                                 'scope':'SHA256 of protected plans, campaign markers and analysis per-run files; all prior trees are read-only by this preparation',
                                 'before':before,'after':after})
    if before!=after:raise RuntimeError('Protected prior artifact changed')
    print(json.dumps({'plan_sha256':config.sha(OUT/'plan.json'),
                      'preregistration_sha256':plan['preregistration_sha256'],
                      'bundle_sha256':bundle_sha,'preservation':'PASS'},indent=2))


if __name__=='__main__':main()
