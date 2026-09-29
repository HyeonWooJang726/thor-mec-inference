#!/usr/bin/env python3
"""Minimal live-placement adapter over frozen Rate-DVFS/K8 run_one.

No copied decode, TensorRT worker, source scheduler or tegrastats implementation.
Guarded in-memory source substitutions expose only hybrid hooks; originals stay frozen.
"""
import argparse
import ast
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import types

from hybrid_common import ROOT,OUT,PLAN,load_plan,sha,decorate,remaining,EXTRA_FIELDS
from edge_link import EdgeLink
sys.path.insert(0,str(ROOT/'scripts/rate_dvfs_gate'))
import run_rate_dvfs_gate as base
import gpu_frequency as frequency

CAPABILITY=ROOT/'results/rate_dvfs_gate/frequency_capability.json'


def write_json(path,data):
    path=Path(path)
    if path.parent.parent!=OUT:raise RuntimeError('hybrid run writer outside dedicated run directories')
    base.write_json(path,data)


def replace_once(text,old,new,count=1):
    if text.count(old)!=count:raise RuntimeError('frozen hook shape mismatch: '+old[:100])
    return text.replace(old,new)


def adapted_source():
    s=inspect.getsource(base.run_one)
    s=replace_once(s,'from analyze_rate_dvfs_gate import summarize','from analyze_hybrid import summarize')
    s=replace_once(s,"OUT/'frequency_capability.json'",'CAPABILITY',2)
    s=replace_once(s,"OUT/'EXPERIMENT_PLAN_V2.md'",'EXECUTION_PLAN',2)
    s=replace_once(s,'telemetry=None;telemetry_thread=None','telemetry=None;telemetry_thread=None;edge=None')
    s=replace_once(s,'manifest.update(summary_written=False',
        "manifest.update(experiment='K8_HYBRID_CAPACITY_EXTENSION', placement_schedule=plan['placement'], "
        "local_assigned_fps=200, edge_assigned_fps=40, edge_threads_exited=False)\n    manifest.update(summary_written=False")
    s=replace_once(s,'return preprocess_bgr(frame)',
                  'return cv2.resize(frame,(640,360),interpolation=cv2.INTER_LINEAR)')
    s=replace_once(s,'warm_tensor=sample_tensor(sample)',
                  'warm_tensor=remaining(sample_tensor(sample).tobytes(order="C"))')
    s=replace_once(s,"Gst.init(None);cv2.setNumThreads(1)",
        "if 'NV Power Mode: MAXN' not in manifest['environment_before']['nvpmodel']:\n"
        "            raise RuntimeError('MAXN required; no nvpmodel change attempted')\n"
        "        edge=EdgeLink(condition,run_id,manifest,directory,fail,sha(EXECUTION_PLAN),plan['edge_host'])\n"
        "        Gst.init(None);cv2.setNumThreads(1)")
    s=replace_once(s,"job['tensor']=sample_tensor(sample)\n                            with lock:accounting.enqueue(ready_queue,job,time.monotonic_ns)",
        "job['resize_start_ns']=time.monotonic_ns()\n"
        "                            image=sample_tensor(sample)\n"
        "                            job['resize_end_ns']=time.monotonic_ns()\n"
        "                            if job['placement']=='LOCAL':\n"
        "                                job['payload_ready_ns']=time.monotonic_ns()\n"
        "                                job['tensor']=remaining(memoryview(image).cast('B'))\n"
        "                                with lock:accounting.enqueue(ready_queue,job,time.monotonic_ns)\n"
        "                            else:edge.put(job,image.tobytes(order='C'))")
    s=replace_once(s,"with lock:frames.append(row)\n                            arrival_queues[stream_id].put(row)",
        "decorate(row,manifest['active_start_ns'])\n"
        "                            with lock:frames.append(row)\n                            arrival_queues[stream_id].put(row)")
    s=replace_once(s,'all_done=all(not t.is_alive() for t in threads)',
        'if all(x.is_set() for x in front_done):edge.finish()\n'
        '                all_done=all(not t.is_alive() for t in threads) and edge.done.is_set()')
    s=replace_once(s,"if not manifest['cleanup_started']:checkpoint('cleanup_started',cleanup_started=True)",
        "if not manifest['cleanup_started']:checkpoint('cleanup_started',cleanup_started=True)\n"
        "        if edge is not None:\n"
        "            try:edge.close()\n"
        "            except BaseException:errors.append('Edge cleanup: '+traceback.format_exc())")
    ast.parse(s)
    return s


def bindings():
    ns=dict(base.__dict__)
    ns.update(OUT=OUT,EXECUTION_PLAN=PLAN,CAPABILITY=CAPABILITY,load_plan=load_plan,
              write_json=write_json,sha=sha,EdgeLink=EdgeLink,decorate=decorate,remaining=remaining,
              FRAME_FIELDS=base.FRAME_FIELDS+EXTRA_FIELDS,__file__=__file__)
    exec(compile(adapted_source(),str(Path(__file__).resolve())+':frozen-run-adapter','exec'),ns)
    final_source=replace_once(inspect.getsource(base.finalize_run),
                 'from analyze_rate_dvfs_gate import summarize,read_csv',
                 'from analyze_hybrid import summarize,read_csv')
    exec(compile(final_source,str(Path(__file__).resolve())+':finalize-adapter','exec'),ns)
    return ns['run_one'],ns['finalize_run']


def check_inputs():
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='rate-dvfs-gate':
        raise RuntimeError('wrong branch; no checkout')
    plan=load_plan()
    for path,digest in plan['source_sha256'].items():
        if sha(ROOT/path)!=digest:raise RuntimeError('source SHA mismatch: '+path)
    for source in plan['inputs']:
        if sha(Path(source['path']))!=source['sha256']:raise RuntimeError('video SHA mismatch: '+source['path'])
    if sha(base.ENGINE)!=plan['engine_provenance']['sha256']:raise RuntimeError('ENGINE_PROVENANCE_FAIL')
    adapted_source()
    return plan


def smoke_pass(plan):
    d=OUT/plan['smoke'][0]['run_id']
    if not (d/'summary.json').exists():return False
    s=json.loads((d/'summary.json').read_text());m=json.loads((d/'manifest.json').read_text())
    return (s.get('integrity_status')=='VALID' and s.get('PROCESS_LIFECYCLE')=='PASS'
            and s.get('child_returncode')==0 and s.get('backlog_after_drain')==0
            and m.get('execution_manifest_sha256')==sha(PLAN) and s.get('frequency_restore_ok') is True
            and s.get('placement_accounting_correct') is True)


def campaign(mode):
    plan=check_inputs()
    if mode=='primary' and not smoke_pass(plan):raise RuntimeError('hybrid smoke integrity PASS required')
    _,finalize=bindings()
    for c in plan['smoke'] if mode=='smoke' else plan['order']:
        d=OUT/c['run_id'];d.mkdir(exist_ok=False)
        start=datetime.now(timezone.utc);start_ns=time.monotonic_ns()
        seed=dict(protocol_version=2,run_id=c['run_id'],kind=c['kind'],repeat=c.get('repeat'),
                  K=8,C=2,freq_state='HIGH',requested_freq_MHz=1575,admission_fps_per_stream=30,
                  errors=[],active_start_ns=None,active_end_ns=None,child_returncode=None,
                  summary_written=False,active_phase_completed=False,drain_completed=False,
                  cleanup_started=False,cleanup_completed=False,frequency_restore_ok=False,status_finalized=False)
        write_json(d/'manifest.json',seed)
        # Preserve valid empty traces even if import/preflight crashes before the child writes them.
        import gzip,csv
        for name,fields in [('per_frame.csv.gz',base.FRAME_FIELDS+EXTRA_FIELDS),('power_trace.csv.gz',base.POWER_FIELDS)]:
            with gzip.open(d/name,'wt',newline='') as f:csv.DictWriter(f,fieldnames=fields).writeheader()
        process=None;stdout='';stderr='';interrupted=False;recovery_error=None
        try:
            process=subprocess.Popen([sys.executable,'-X','faulthandler','-B',str(Path(__file__).resolve()),
                      'one','--run-id',c['run_id']],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:stdout,stderr=process.communicate(timeout=c['seconds']+300)
            except (subprocess.TimeoutExpired,KeyboardInterrupt):
                interrupted=True;process.terminate()
                try:stdout,stderr=process.communicate(timeout=15)
                except subprocess.TimeoutExpired:process.kill();stdout,stderr=process.communicate()
        finally:
            # Main child pin context normally restores; parent also recovers after abnormal exit.
            current=frequency.read_range()
            if (current['min_freq'],current['max_freq'])!=(315000000,1575000000):
                try:frequency.restore()
                except BaseException:recovery_error='parent frequency restore failed'
        if process is None:raise RuntimeError('child launch failed; seed/traces preserved')
        code=process.returncode
        info=dict(child_pid=process.pid,child_returncode=code,
                  child_exit_signal=signal.Signals(-code).name if code<0 else None,
                  child_start_time=start.isoformat(),child_exit_time=datetime.now(timezone.utc).isoformat(),
                  child_start_monotonic_ns=start_ns,child_exit_monotonic_ns=time.monotonic_ns(),
                  supervisor_interrupted_or_timeout=interrupted,parent_restore_error=recovery_error)
        s=finalize(d,info,stdout,stderr)
        print(json.dumps({k:s.get(k) for k in ('run_id','integrity_status','g_B_H','aggregate_completed_fps','OC3_delta','frequency_restore_ok')}),flush=True)
        if interrupted or recovery_error or not s.get('frequency_restore_ok'):return 2
        if not json.loads((d/'manifest.json').read_text()).get('edge_ready'):
            # No synchronized session index exists after a failed handshake.
            # Preserve this run; do not consume later planned conditions blindly.
            return 2
    return 0 if mode=='primary' or smoke_pass(plan) else 1


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['check','smoke','primary','one'])
    ap.add_argument('--run-id')
    args=ap.parse_args()
    if args.action=='check':
        check_inputs();print('CPU/input/adapter check PASS; no GPU or frequency access');result=0
    elif args.action=='one':
        plan=check_inputs();matches=[c for c in plan['smoke']+plan['order'] if c['run_id']==args.run_id]
        if len(matches)!=1:raise RuntimeError('run outside frozen plan')
        result=bindings()[0](matches[0],args.run_id)
    else:result=campaign(args.action)
    raise SystemExit(result)
