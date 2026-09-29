#!/usr/bin/env python3
"""Small isolated C1 profile; unchanged canonical worker, no multi-stream rerun."""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'results/capacity_model_validity'
FREQS=[630,792,945,1107,1260,1413,1575]
for sub in ['common','local','concurrency','local_capacity_characterization']:
    sys.path.insert(0,str(ROOT/'scripts'/sub))
import gpu_frequency as frequency

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write(p,obj):
    p.write_text(json.dumps(obj,indent=2)+'\n')

def now():return datetime.now(timezone.utc).isoformat()

def oc3():
    for p in Path('/sys/class/hwmon').glob('*'):
        if (p/'name').read_text().strip()=='soctherm_oc':return int((p/'oc3_event_cnt').read_text())
    raise RuntimeError('OC3 unavailable')

def rows_csv(p,rows):
    with gzip.open(p,'wt',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['phase']);w.writeheader();w.writerows(rows)

def plan():return json.loads((OUT/'input_manifest.json').read_text())

def check_inputs(p):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='rate-dvfs-gate'
    assert 'NV Power Mode: MAXN' in subprocess.check_output(['nvpmodel','-q'],text=True)
    for k,v in p['execution_hashes'].items():
        if sha(ROOT/k)!=v:raise RuntimeError('source hash mismatch '+k)
    for x in [p['engine'],p['input']]:
        if sha(x['path'])!=x['sha256']:raise RuntimeError('input provenance mismatch '+x['path'])
    assert frequency.supported()==p['supported_frequencies_Hz']
    assert all(f*1000000 in frequency.supported() for f in FREQS)
    r=frequency.read_range()
    assert (r['min_freq'],r['max_freq'])==(315000000,1575000000)

def child(run_id):
    from profile_local_e2e import Gst,GstVideo,build_pipeline,preprocess_bgr,np,cv2
    from local_concurrency_tensorrt import ConcurrentTensorRT
    p=plan();d=OUT/run_id;m=json.loads((d/'manifest.json').read_text())
    if m.get('child_started'):raise RuntimeError('refuse rerun')
    m.update(child_started=True,child_pid=os.getpid(),errors=[],lifecycle=[],C=1,batch_size=1,precision='FP16',CUDA_Graph=False)
    rows=[];power=[];rt=None;pipe=None;tele=None;thread=None;stop=threading.Event()
    def checkpoint(phase):
        m['last_completed_lifecycle_phase']=phase;m['lifecycle'].append({'phase':phase,'timestamp_ns':time.monotonic_ns()});write(d/'manifest.json',m)
    def monitor():
        try:
            for line in tele.stdout:
                if stop.is_set():break
                w=re.search(r'\bVDD_GPU (\d+)mW/',line);t=re.search(r'\bgpu@([\d.]+)C',line)
                if not w or not t:continue
                rg=frequency.read_range()
                power.append({'timestamp_ns':time.monotonic_ns(),'requested_freq_MHz':m['frequency_MHz'],
                              'actual_freq_MHz':rg['cur_freq']/1e6,'min_freq_Hz':rg['min_freq'],'max_freq_Hz':rg['max_freq'],
                              'VDD_GPU_W':int(w[1])/1000,'temperature_C':float(t[1]),'OC3_count':oc3(),'raw_tegrastats':line.strip()})
        except BaseException:m['errors'].append('telemetry: '+traceback.format_exc())
    try:
        check_inputs(p);m['environment_before']={'nvpmodel':subprocess.check_output(['nvpmodel','-q'],text=True),'frequency':frequency.read_range()}
        Gst.init(None);cv2.setNumThreads(1)
        pipe,_,sink=build_pipeline(p['input']['path'])
        if pipe.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('source open failed')
        sample=sink.emit('try-pull-sample',5*Gst.SECOND)
        if sample is None:raise RuntimeError('first real source frame unavailable')
        info=GstVideo.VideoInfo.new_from_caps(sample.get_caps());buffer=sample.get_buffer()
        assert (info.width,info.height,info.finfo.name)==(1920,1080,'BGR')
        ok,mapping=buffer.map(Gst.MapFlags.READ)
        if not ok:raise RuntimeError('buffer mapping')
        try:tensor=preprocess_bgr(np.ndarray((1080,1920,3),dtype=np.uint8,buffer=mapping.data,strides=(info.stride[0],3,1)))
        finally:buffer.unmap(mapping)
        pipe.set_state(Gst.State.NULL);pipe=None;sample=None;buffer=None
        m['input_tensor_sha256']=hashlib.sha256(tensor.tobytes()).hexdigest()
        m['input_tensor_shape']=list(tensor.shape);checkpoint('input_prepared_decode_stopped')
        with frequency.pinned(m['frequency_MHz']):
            rt=ConcurrentTensorRT(p['engine']['path'],1);worker=rt.workers[0];worker.bind_thread()
            m['resources']=rt.resources;m['OC3_before']=oc3()
            tele=subprocess.Popen(['/usr/bin/tegrastats','--interval','100'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            thread=threading.Thread(target=monitor,daemon=True);thread.start()
            checkpoint('warmup_started')
            for phase,seconds in [('warmup',5),('measurement',10)]:
                start=time.monotonic_ns();i=0
                if phase=='measurement':m['measurement_start_ns']=start;checkpoint('measurement_started')
                while time.monotonic_ns()-start<seconds*10**9 or (phase=='warmup' and i<100):
                    a=time.monotonic_ns();worker.infer(tensor);b=time.monotonic_ns()
                    rows.append({'phase':phase,'request_id':i,'input_frame_id':0,'start_ns':a,'completion_ns':b,'service_ms':(b-a)/1e6})
                    i+=1
                if phase=='measurement':m['measurement_end_ns']=rows[-1]['completion_ns'];m['measurement_completed']=True
                checkpoint(phase+'_completed')
            m['OC3_after']=oc3();stop.set();tele.terminate();tele.wait(3);thread.join(3)
            checkpoint('cleanup_started');rt.close();rt=None;worker=None;checkpoint('cleanup_completed')
        m['frequency_restore_ok']=True;checkpoint('restored')
    except BaseException:
        m['errors'].append(traceback.format_exc())
    finally:
        stop.set()
        if pipe is not None:pipe.set_state(Gst.State.NULL)
        if tele and tele.poll() is None:
            tele.terminate()
            try:tele.wait(3)
            except subprocess.TimeoutExpired:tele.kill();tele.wait()
        if thread:thread.join(3)
        if rt is not None:
            try:rt.close()
            except BaseException:m['errors'].append('cleanup: '+traceback.format_exc())
        try:
            frequency.restore();rg=frequency.read_range();m['restored_range_Hz']=rg
            m['frequency_restore_ok']=(rg['min_freq'],rg['max_freq'])==(315000000,1575000000)
        except BaseException:m['frequency_restore_ok']=False;m['errors'].append('restore: '+traceback.format_exc())
        active=[x for x in rows if x['phase']=='measurement']
        pp=[x for x in power if m.get('measurement_start_ns',0)<=x['timestamp_ns']<=m.get('measurement_end_ns',0)]
        if not active or not pp or not m.get('measurement_completed'):m['errors'].append('missing measurement/telemetry')
        if pp and not any(x['actual_freq_MHz']>0 for x in pp):m['errors'].append('active actual frequency unavailable')
        if pp and any(x['min_freq_Hz']!=m['frequency_MHz']*1000000 or x['max_freq_Hz']!=m['frequency_MHz']*1000000 for x in pp):m['errors'].append('frequency pin mismatch')
        vals=[x['service_ms'] for x in active]
        sm={'run_id':run_id,'frequency_MHz':m['frequency_MHz'],'repeat':m['repeat'],'C':1,'integrity_status':'PENDING_PROCESS_EXIT',
            'measurement_count':len(active),'warmup_count':len(rows)-len(active),'errors':m['errors'],
            'service_ms':{k:float(v) for k,v in zip(['mean','p50','p95','p99'],[np.mean(vals),*np.percentile(vals,[50,95,99])])} if vals else {},
            'elapsed_seconds':(m['measurement_end_ns']-m['measurement_start_ns'])/1e9 if active else None,
            'frequency_restore_ok':m['frequency_restore_ok'],'OC3_delta':m.get('OC3_after',0)-m.get('OC3_before',0),
            'actual_freq_mean_MHz':statistics.mean(x['actual_freq_MHz'] for x in pp) if pp else None,
            'avg_VDD_GPU_W':statistics.mean(x['VDD_GPU_W'] for x in pp) if pp else None,
            'temperature_C':statistics.mean(x['temperature_C'] for x in pp) if pp else None}
        sm['hardware_status']='PROTECTION_LIMITED' if sm['OC3_delta']>0 else 'CLEAN'
        sm['measured_C1_inference_only_throughput']=len(active)/sm['elapsed_seconds'] if active else None
        rows_csv(d/'latency_samples.csv.gz',rows);rows_csv(d/'power_trace.csv.gz',power)
        write(d/'summary.json',sm);checkpoint('summary_written')
    return 1 if m['errors'] else 0

def campaign():
    p=plan();check_inputs(p);frequency.require_control()
    if any(OUT.glob('ISO_*')):raise RuntimeError('existing profile run; no automatic rerun/resume')
    for x in p['profiling_order']:
        check_inputs(p);d=OUT/x['run_id'];d.mkdir()
        m={**x,'input':p['input'],'engine':p['engine'],'execution_hashes':p['execution_hashes'],
           'input_inventory_sha256':sha(OUT/'INPUT_INVENTORY.md'),'child_start_time':now(),'parent_pid':os.getpid()}
        write(d/'manifest.json',m)
        print('START '+json.dumps(x),flush=True)
        with (d/'stderr.log').open('x') as log:
            proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'one','--run-id',x['run_id']],stdout=log,stderr=subprocess.STDOUT)
            m['child_pid']=proc.pid;write(d/'manifest.json',m)
            try:code=proc.wait(timeout=120)
            except BaseException:
                proc.terminate()
                try:proc.wait(10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                frequency.restore();raise
        m=json.loads((d/'manifest.json').read_text())
        m.update(child_returncode=code,child_exit_signal=signal.Signals(-code).name if code<0 else None,child_exit_time=now())
        try:
            rg=frequency.read_range()
            if (rg['min_freq'],rg['max_freq'])!=(315000000,1575000000):frequency.restore()
        except BaseException:m['frequency_restore_ok']=False;write(d/'manifest.json',m);raise
        s=json.loads((d/'summary.json').read_text()) if (d/'summary.json').exists() else {'errors':['child summary missing']}
        s.update(child_returncode=code,child_exit_signal=m['child_exit_signal'],status_finalized=True)
        s['integrity_status']='VALID' if code==0 and not s['errors'] and m.get('frequency_restore_ok') and m.get('measurement_completed') else 'INVALID'
        m['integrity_status']=s['integrity_status'];m['status_finalized']=True;write(d/'manifest.json',m);write(d/'summary.json',s)
        print('DONE '+json.dumps({k:s.get(k) for k in ['run_id','frequency_MHz','integrity_status','service_ms','OC3_delta','child_returncode']}),flush=True)
        if s['integrity_status']!='VALID':raise RuntimeError('invalid isolated profile; retained, no retry')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','one','check']);parser.add_argument('--run-id');a=parser.parse_args()
    if a.action=='run':campaign()
    elif a.action=='one':raise SystemExit(child(a.run_id))
    else:check_inputs(plan());print('read-only preflight PASS')
