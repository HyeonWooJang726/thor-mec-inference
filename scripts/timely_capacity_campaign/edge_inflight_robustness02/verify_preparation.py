"""CPU-only frozen-plan verification; no runtime/network commands."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import config

_spec=importlib.util.spec_from_file_location('edge_inflight_prepare',config.HERE/'prepare.py')
prepare=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)


def run_test(path):
    proc=subprocess.run([sys.executable,str(path)],capture_output=True,text=True,
                        timeout=30,check=False)
    return {'status':'PASS' if proc.returncode==0 else 'FAIL',
            'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr}


def main():
    out=config.OUT
    plan=config.load_plan()
    report={}
    order=config.frozen_order()
    report['eight_unique_measured_runs']='PASS' if len(order)==len({r['run_id'] for r in order})==8 else 'FAIL'
    report['exact_order_and_stages']='PASS' if [(x['edge_C'],x['repeat'],x['pattern']) for x in order]==list(config.SEQUENCE) and \
        [(s['C_E'],s['start_index'],s['end_index']) for s in plan['stages']]==[(1,0,2),(2,2,6),(1,6,8)] else 'FAIL'
    report['same_E48_masks']='PASS' if all(config.schedule(p)['per_stream_masks']==
        config.previous.schedule(48,p)['per_stream_masks'] for p in ('ALIGNED','STAGGERED')) else 'FAIL'
    report['B1_and_30s']='PASS' if plan['B']==1 and all(r['edge_B']==1 and r['seconds']==30 for r in order) else 'FAIL'
    report['absolute_TIR_rule']='PASS' if plan['primary_delta']=='TIR(CE2,ALIGNED,j)-TIR(CE1,ALIGNED,j)' and \
        'both_ge_absolute_0.10' in plan['primary_rule'] else 'FAIL'
    old=json.loads((config.ROOT/'results/timely_capacity_campaign/v2_2/edge_inflight_robustness01/plan.json').read_text())
    same_keys=('K','source_FPS_per_stream','rate','deadline_ms','active_seconds','idle_seconds',
               'payload_bytes','B','phase_vector_staggered','ALIGNED_mask','STAGGERED_mask',
               'cache','edge_engine_SHA256','server_configuration_method','server_warmup_per_worker',
               'primary_delta','primary_rule','STAGGERED_role','no_TCP_probe','no_retry_resume_overwrite')
    report['scientific_condition_equality']='PASS' if all(plan[k]==old[k] for k in same_keys) and \
        [(r['edge_C'],r['repeat'],r['pattern']) for r in plan['order']]==\
        [(r['edge_C'],r['repeat'],r['pattern']) for r in old['order']] else 'FAIL'
    source=(config.HERE/'edge_server.py').read_text()
    initialize=source[source.index('def _initialize(self):'):source.index('def close(self):')]
    report['TensorRT_binding_before_ContextWorker']='PASS' if \
        initialize.index('import tensorrt as trt') < initialize.index('self.helpers.trt = trt') and \
        'self.helpers.ContextWorker(shared.engine,worker_id)' in source else 'FAIL'
    deps={name:config.sha(out/'edge_bundle'/name) for name in plan['edge_dependency_sha256']}
    canonical=json.dumps(deps,sort_keys=True,separators=(',',':')).encode()
    report['bundle_source_SHA']='PASS' if deps==plan['edge_dependency_sha256'] and \
        hashlib.sha256(canonical).hexdigest()==plan['bundle_sha256'] else 'FAIL'
    lines=(out/'edge_bundle/SHA256SUMS').read_text().splitlines()
    report['bundle_SHA256SUMS']='PASS' if all(config.sha(out/'edge_bundle'/name)==digest
        for digest,name in (line.split('  ',1) for line in lines)) else 'FAIL'
    report['historical_CE2_memory']='PASS' if json.loads((out/'C_E2_MEMORY_READINESS.json').read_text())['status']=='PASS' else 'FAIL'
    report['fresh_execution_namespace']='PASS' if not any((out/name).exists() for name in
        ('campaign_attempt.json','CPU_PIN_READBACK.json','CPU_RESTORE_READBACK.json',
         'NETWORK_REACHABILITY_CHECK.json','operator_evidence','sessions','analysis01')) else 'FAIL'
    evidence=out/'edge_preflight_evidence'
    report['waiting_for_real_Edge_preflight']='PASS' if evidence.is_dir() and \
        not any(evidence.iterdir()) and not (out/'EDGE_PREFLIGHT_READY.json').exists() else 'FAIL'
    preservation=json.loads((out/'preservation.json').read_text())
    report['prior_preservation']='PASS' if preservation['status']=='PASS' and \
        prepare.selected_protected_hashes()==preservation['before'] else 'FAIL'
    source=(config.HERE/'run_thor.py').read_text()
    check=source[source.index('def check_preexecution'):source.index('def require_current_pin_evidence')]
    report['check_no_TCP_probe']='PASS' if all(token not in check for token in
        ('socket.create_connection','nc ','telnet','curl','HELLO','5000')) else 'FAIL'
    report['measured_stage1_real_preflight_guard']='PASS' if \
        'require_edge_preflight_ready(plan)' in check and \
        'require_edge_preflight_ready(plan)' in source[source.index('def campaign_run'):source.index('def main():')] else 'FAIL'
    report['server_synthetic']=run_test(config.HERE/'regression_cpu.py')
    report['server_to_Thor_analysis_synthetic']=run_test(config.HERE/'test_analysis_synthetic.py')
    report['plan_sha256']=config.sha(config.PLAN)
    report['status']='PASS' if all(v=='PASS' if isinstance(v,str) else v['status']=='PASS'
                                  for key,v in report.items() if key!='plan_sha256') else 'FAIL'
    report_path=out/'regression_report.json'
    if report_path.exists():
        old=json.loads(report_path.read_text())
        if old.get('status')=='PASS' and old.get('plan_sha256')==report['plan_sha256']:
            raise RuntimeError('Passing frozen regression report already exists for this plan')
    with report_path.open('w') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({key:value if isinstance(value,str) else value['status']
                     for key,value in report.items()},indent=2))
    return 0 if report['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
