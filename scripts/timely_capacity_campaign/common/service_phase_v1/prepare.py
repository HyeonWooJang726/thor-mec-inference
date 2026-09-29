"""Phase A CPU preparation only. No command here can start an experiment."""
import ast
import datetime
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from build_adapter import ROOT,BASE_RUN,BASE_TRT,run_source,runtime_source

HERE=Path(__file__).resolve().parent
OUT=ROOT/'results/timely_capacity_campaign/pruning_path_audit/service_phase_instrumentation'
VALIDATION=ROOT/'results/timely_capacity_campaign/pruning_path_audit/service_phase_validation'


def text(path,value):
    with path.open('x') as f:f.write(value)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='rate-dvfs-gate':
        raise RuntimeError('Wrong branch')
    result=subprocess.run([sys.executable,'-B',str(HERE/'verify_cpu.py')],cwd=ROOT,capture_output=True,text=True)
    text(OUT/'test_results.txt',result.stdout+result.stderr+'\nexit_code='+str(result.returncode)+'\n')
    if result.returncode:raise RuntimeError('CPU regression failed')
    record=json.loads(result.stdout)
    text(OUT/'behavior_preservation.json',json.dumps(record,indent=2)+'\n')
    rs,ts=run_source(),runtime_source()
    text(OUT/'instrumented_run_one.txt',rs)
    text(HERE/'instrumented_local_runtime.py',ts)
    diff=''.join(difflib.unified_diff(BASE_RUN.read_text().splitlines(True),rs.splitlines(True),fromfile=str(BASE_RUN.relative_to(ROOT)),tofile='NEW instrumented_run_one.txt'))
    diff+=''.join(difflib.unified_diff(BASE_TRT.read_text().splitlines(True),ts.splitlines(True),fromfile=str(BASE_TRT.relative_to(ROOT)),tofile=str((HERE/'instrumented_local_runtime.py').relative_to(ROOT))))
    text(OUT/'source_diff.txt',diff)
    # No experiment launcher is created in Phase A: the six-run plan is approval-gated.
    original=json.loads((ROOT/'results/timely_capacity_campaign/block_b_split/v2/E_MAX_72/plan.json').read_text())
    conditions=[]
    specs=[('B0','S240_L176E64_ON',240,176,64,True,1),('B1','LOCAL200_OFF_R1',200,200,0,False,1),
           ('B1','LOCAL200_ON_R1',200,200,0,True,1),('B1','LOCAL200_ON_R2',200,200,0,True,2),
           ('B1','LOCAL200_OFF_R2',200,200,0,False,2),('B2','S240_L200E40_ON',240,200,40,True,1)]
    for index,(block,name,admitted,local,edge,on,repeat) in enumerate(specs,1):
        c=dict(order_index=index,run_id='SPI_'+name+'_P01',block=block,admitted_FPS=admitted,local_FPS=local,edge_FPS=edge,pruning_enabled=on,repeat=repeat,active_seconds=60)
        if block in ('B0','B2'):
            previous=next(r for r in original['order'] if r['target_service_FPS']==admitted and r['local_r']*8==local and r['edge_r']*8==edge)
            c['frozen_original_condition']=previous
        conditions.append(c)
    plan=dict(status='WAITING_FOR_PHASE_A_APPROVAL_NOT_EXECUTABLE',order=conditions,
        fixed=dict(K=8,source_FPS_per_stream=30,decode_resize_FPS=240,deadline_ms=100,frequency_MHz=1575,C_L=2,C_E=1,B=1,
                   power_mode='MAXN (read/verify only)',DVFS='existing governor unchanged; pin 1575 during active, restore315–1575',
                   source_phase='same frozen canonical phase',instrumentation=True,network_for_E0=False),
        no_retry=True,no_overwrite=True,output=str(VALIDATION.relative_to(ROOT)),
        OFF_semantics='Future explicit control: original QueueAccounting.start FIFO; no expiry decision/drop. D100 remains offline metric.',
        ON_semantics='Original PruningAccounting.begin unchanged; stamp>=deadline expiry; no cancellation of running work.',
        approval='All six GPU/network/frequency runs require approval after Phase A. No launch command provided in Phase A.',
        first_GPU_run=dict(event_validation_required=True,no_extra_smoke=True,invalid_event_action='Preserve B0 and stop remaining run sequence for review',
            checks=['event record return codes','elapsed finite/nonnegative','not zero-only','same original CUDA sync count'],
            historical_service_reference_ms_approx=9.16,overhead_descriptive_difference_ms=0.2,
            exceeds_0_2='Preserve run; flag possible overhead/environment variation; never discard. All continued runs use identical instrumentation.'),
        startup=dict(seconds=3,bin_ms=100,phase_grouping='service-start bin',counts='completion/drop event bin',
                     gpu_p95_minimum_sample_count=20,rule_scope='descriptive quantile reporting only, not validity/performance threshold'),
        interpretations='Five user-provided descriptive branches; no automatic causal verdict or optimization',
        next_phases='C recovery and D Block A not executed or modified')
    text(OUT/'phase_b_validation_plan.json',json.dumps(plan,indent=2)+'\n')
    inventory=dict(executed_Local_frame=dict(additional_monotonic_reads=10,worker_private_tuple_appends=1,event_records=2,elapsed_queries=1,
                                           new_common_lock_acquisitions=0,inside_existing_lock='two scalar monotonic reads only'),
                   expired_Local_frame=dict(additional_monotonic_reads=6,worker_private_tuple_appends=1,event_records=0,elapsed_queries=0,new_common_lock_acquisitions=0),
                   warmup=dict(event_records_per_inference=2,phase_rows=0,elapsed_queries=0),
                   per_worker_initialization=dict(timing_enabled_events=2,reused_ctypes_float=1,private_list=1),
                   no_new=['CUDA stream','CUDA synchronize','device tensor buffer','pinned host buffer','explicit gc','hot-path I/O/JSON','shared metric list'],
                   event_resource_exception='Initial reusable CUDA event handles expressly contemplated by section1-b; not a per-frame tensor/host-buffer allocation',
                   overhead='UNMEASURED_PHASE_A; tuple/scalar/list growth and API/timestamp overhead are real, not asserted negligible',
                   event_elapsed_query='after legacy completion bookkeeping, excluded from recorded service/call durations but can delay next job',
                   record_append='outside measured durations and common lock; can delay next queue pop')
    text(OUT/'instrumentation_overhead_inventory.json',json.dumps(inventory,indent=2)+'\n')
    print('CPU validation PASS. New source and approval-only six-run plan written. No workload started.')

if __name__=='__main__':main()
