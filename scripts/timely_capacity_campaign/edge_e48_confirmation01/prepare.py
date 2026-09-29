"""CPU-only, exclusive-create freeze for E48 confirmation; never launches workload."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import config

sys.path.insert(0, str(config.HERE.parent/'common'/'service_phase_b1f'))
import cpu_state
from make_cpu_commands import render


def write_json(path, obj):
    with path.open('x') as stream:
        json.dump(obj, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def copy_exact(source, target):
    with Path(source).open('rb') as inp, Path(target).open('xb') as out:
        out.write(inp.read())
    if config.sha(source) != config.sha(target):
        raise RuntimeError('Bundle copy SHA mismatch: '+str(source))


def tree_hash(root):
    if not root.is_dir(): return {'status':'UNAVAILABLE','reason':'directory absent'}
    files = {str(path.relative_to(root)):config.sha(path) for path in sorted(root.rglob('*')) if path.is_file()}
    canonical = json.dumps(files, sort_keys=True, separators=(',',':')).encode()
    return {'status':'PASS','file_count':len(files),'files_sha256':files,
            'manifest_sha256':hashlib.sha256(canonical).hexdigest()}


def main():
    out = config.OUT
    if (out/'plan.json').exists() or (out/'campaign_attempt.json').exists():
        raise RuntimeError('Already frozen/consumed; no overwrite')
    old = config.ROOT/'results/timely_capacity_campaign/v2_2/edge_preflight_final02'
    old_plan = json.loads((old/'plan.json').read_text())
    if old_plan['edge_ip'] != '192.168.0.6':
        raise RuntimeError('Last verified Edge endpoint changed; recheck before freezing')
    protected = {name:config.ROOT/'results/timely_capacity_campaign/v2_2'/name for name in
                 ('edge_preflight_final01','edge_preflight_final02','block_a_phase_pilot01','block_a_phase_pilot02')}
    before = {name:tree_hash(path) for name,path in protected.items()}
    cache = old_plan['cache']
    if config.sha(config.ROOT/cache['path']) != cache['sha256']:
        raise RuntimeError('Frozen RAW640 cache changed')
    q48,q64=config.q(48),config.q(64)
    e48a,e48s,e64s=(config.schedule(48,'ALIGNED'),config.schedule(48,'STAGGERED'),
                     config.schedule(64,'STAGGERED'))
    if e48s['max_m_n'] != 2:
        raise RuntimeError('EXPECTED_E48_SLOT_SHAPE_MISMATCH_REVIEW_REQUIRED')
    if any(v not in (0,8) for v in e48a['m_n']) or e48a['max_m_n'] != 8:
        raise RuntimeError('Unexpected canonical E48 aligned burst')
    endpoint={'hostname':'CY415AINET','edge_ip':'192.168.0.6','thor_ip':'192.168.0.189',
        'inference_port':5000,'subnet':'192.168.0.0/24',
        'provenance':'Operator-verified Final02 endpoint; Edge operator must compare live endpoint before pin',
        'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'readiness':'Route hard; neighbor/ICMP diagnostic; Edge LISTENING and Edge-local ss hard; no TCP probe'}
    write_json(out/'EDGE_ENDPOINT_MANIFEST.json',endpoint)
    def pattern(rate,bits,**schedules):
        text=''.join(map(str,bits))
        for schedule in schedules.values():
            schedule['per_stream_mask_sha256'] = [hashlib.sha256(''.join(map(str,mask)).encode('ascii')).hexdigest()
                                                  for mask in schedule['per_stream_masks']]
            schedule['schedule_sha256'] = hashlib.sha256(json.dumps(schedule['per_stream_masks'],
                separators=(',',':')).encode()).hexdigest()
        return {'rate_FPS':rate,'per_stream_FPS':rate//8,'q':list(bits),
            'q_bits':text,'q_SHA256_ASCII_bits':hashlib.sha256(text.encode()).hexdigest(),
            'generator':'campaign_config.schedule(rate, 0, ALIGNED) canonical floor rule',
            'schedules':schedules,'no_phase_search':True,'no_source_time_shift':True}
    write_json(out/'E48_RATE_PATTERN.json',pattern(48,q48,ALIGNED=e48a,STAGGERED=e48s))
    write_json(out/'E64_STAGGERED_PATTERN.json',pattern(64,q64,STAGGERED=e64s))
    write_json(out/'mechanism_expectations.json',{'binding_to_verdict':False,
        'payload_bytes_per_frame':config.PAYLOAD_BYTES,
        'approx_effective_wire_Mbit_per_frame':5.8,
        'approx_E48_Mbps':278,'approx_E64_Mbps':371,
        'approx_ALIGNED_burst_serialization_required_Mbps':'510-520',
        'ALIGNED_E48_TIR':'roughly 0.7-0.8, central near 0.75; diagnostic only',
        'STAGGERED_E48':'5/5 TIR >=0.99 possible; not robust gate',
        'STAGGERED_E64':'may have run below 0.90; descriptive only',
        'network_note':'337 Mbps Final02 E80-S2 was observed transmitted-data rate, not PHY',
        'mechanism_note':'Serialization estimate simplifies TCP pipeline and queue overlap; no absolute bound'})
    state=cpu_state.snapshot()
    if len(state['policies'])!=7 or any(row['fields']['scaling_max_freq']!='2601000' for row in state['policies']):
        raise RuntimeError('Seven CPU policies with max 2601000 required')
    for row in state['policies']:
        row['fields']['scaling_available_governors']=(Path(row['path'])/'scaling_available_governors').read_text().strip()
    write_json(out/'CPU_STATE_BEFORE.json',state)
    for name,restore in (('CPU_PIN_COMMANDS.sh',False),('CPU_RESTORE_COMMANDS.sh',True)):
        with (out/name).open('x') as stream: stream.write(render(state,restore=restore))
    session={'stage':'CONFIRMATION','order':config.frozen_order(),
        'warmup_index':0,'E48_measured_indices':list(range(1,11)),'E64_headroom_indices':list(range(11,14)),
        'E64_entry_rule':'All 10 E48 measured sessions VALID; no performance-based branch',
        'first_invalid':'Stop subsequent sessions; no retry/resume/overwrite'}
    write_json(out/'session_plan.json',session)
    bundle=out/'edge_bundle'
    bundle.mkdir(exist_ok=False)
    deps={}
    for name in ('formal_protocol.py','formal_server.py','profile_edge_concurrency.py','pruning_edge_server.py'):
        copy_exact(old/'edge_bundle'/name,bundle/name)
        deps[name]=config.sha(bundle/name)
    server=config.HERE/'edge_server_confirmation01.py'
    copy_exact(server,bundle/server.name)
    deps[server.name]=config.sha(server)
    new_sources=[config.HERE/name for name in ('config.py','run_thor.py','edge_server_confirmation01.py','analyze.py','prepare.py','test_cpu.py')]
    frozen_sources=[config.ROOT/name for name in (
        'scripts/timely_capacity_campaign/common/campaign_config.py',
        'scripts/timely_capacity_campaign/common/reuse.py',
        'scripts/timely_capacity_campaign/common/service_phase_b1f/cpu_state.py',
        'scripts/timely_capacity_campaign/common/service_phase_b1f/make_cpu_commands.py',
        'scripts/timely_capacity_campaign/block_b_split/v2/wifi_v2.py',
        'scripts/expired_work_pruning/pruning_common.py',
        'scripts/hybrid_capacity_extension/edge_link.py')]
    write_json(out/'source_sha256.json', {str(p.relative_to(config.ROOT)):config.sha(p) for p in new_sources+frozen_sources})
    plan={'campaign':'EDGE_E48_CONFIRMATION01','freeze_status':'PREPARED_NOT_EXECUTED',
        'purpose':'E48 Edge-only Block B coverage and E64 descriptive headroom; not hybrid capacity',
        'deadline_ms':100,'idle_seconds':config.IDLE_SECONDS,'K':8,'source_FPS_per_stream':30,
        'source_due':'t0+floor(frame_index*1e9/30), eight synchronized streams',
        'payload_bytes':config.PAYLOAD_BYTES,'cache':cache,
        'edge_host':endpoint['edge_ip'],'edge_ip':endpoint['edge_ip'],'edge_port':5000,
        'endpoint_manifest_sha256':config.sha(out/'EDGE_ENDPOINT_MANIFEST.json'),
        'source_sha256_manifest_sha256':config.sha(out/'source_sha256.json'),
        'edge_engine_SHA256':old_plan['edge_engine_SHA256'],
        'phase_vector_staggered':list(config.PHASES),
        'order':config.frozen_order(),
        'session_plan_sha256':{'session_plan.json':config.sha(out/'session_plan.json')},
        'edge_dependency_sha256':deps,
        'artifact_sha256':{name:config.sha(out/name) for name in
            ('E48_RATE_PATTERN.json','E64_STAGGERED_PATTERN.json','mechanism_expectations.json','CPU_STATE_BEFORE.json')},
        'classification':{'E48_robust_usable':'5/5 VALID TIR_admission >=0.90',
                          'E48_robust_fail':'5/5 VALID TIR_admission <0.80',
                          'E48_other':'ROBUST_EDGE_BOUNDARY',
                          'E64':'DESCRIPTIVE_HEADROOM_ONLY'},
        'pairing':[[f'EDGE48C01_E48_A{i}',f'EDGE48C01_E48_S{i}'] for i in range(1,6)],
        'delta':'TIR(S_i)-TIR(A_i); descriptive only',
        'warmup':'first session, 15s, integrity/drain/pending-zero gate; excluded from scoring',
        'pre_execution_guards':['fresh namespace','frozen artifacts/cache SHA','route hard',
            'neighbor/ICMP diagnostic','CPU pinned','Edge LISTENING 14 CONFIRMATION sessions + Edge-local ss',
            'no protocol-port probe'],
        'server_runtime':'pruning_edge_server.serve_session + formal_server.Backend unchanged'}
    write_json(out/'plan.json',plan)
    with (out/'plan.sha256').open('x') as stream: stream.write(config.sha(out/'plan.json')+'\n')
    for name in ('plan.json','session_plan.json'):
        copy_exact(out/name,bundle/name)
    with (bundle/'SHA256SUMS').open('x') as stream:
        for path in sorted(p for p in bundle.iterdir() if p.is_file()):
            stream.write(config.sha(path)+'  '+path.name+'\n')
    write_json(out/'BUNDLE_SHA256.json',{p.name:config.sha(p) for p in sorted(bundle.iterdir()) if p.is_file()})
    after={name:tree_hash(path) for name,path in protected.items()}
    write_json(out/'preservation.json',{'status':'PASS' if before==after else 'FAIL',
        'protected_roots':{name:{'before_manifest_sha256':before[name].get('manifest_sha256'),
                                 'after_manifest_sha256':after[name].get('manifest_sha256'),
                                 'file_count':after[name].get('file_count')} for name in protected},
        'artifact_sha256_before':before})
    if before!=after: raise RuntimeError('Protected result SHA changed')
    print(json.dumps({'plan_sha256':config.sha(out/'plan.json'),'session_count':len(session['order']),
        'E48_staggered_max_m_n':e48s['max_m_n'],'preservation':'PASS'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.parse_args()
    main()
