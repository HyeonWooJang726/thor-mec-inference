#!/usr/bin/env python3
"""Rate/DVFS Gate: explicit pre-primary capability microcheck."""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

from gpu_frequency import inspect, pinned, read_range, set_frequency

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/rate_dvfs_gate'
EXECUTION_PLAN = OUT / 'EXPERIMENT_PLAN_V2.md'
ENGINE = ROOT / 'models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine'
EVIDENCE = ROOT / 'results/local_concurrency_formal_full/replacements/c1/k2/replacement01/metadata.json'
sys.path.insert(0, str(ROOT / 'scripts/concurrency'))
sys.path.insert(0, str(ROOT / 'scripts/local'))
sys.path.insert(0, str(ROOT / 'scripts/common'))


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def provenance():
    expected = json.loads(EVIDENCE.read_text())['engine_sha256']
    actual = hashlib.sha256(ENGINE.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError('ENGINE_PROVENANCE_FAIL')
    return {'status': 'PASS', 'engine_path': str(ENGINE),
            'resolved_path': str(ENGINE.resolve()), 'sha256': actual,
            'expected_sha256': expected, 'evidence': str(EVIDENCE)}


def oc3():
    for hw in Path('/sys/class/hwmon').glob('*'):
        if (hw / 'name').read_text().strip() == 'soctherm_oc':
            return int((hw / 'oc3_event_cnt').read_text())
    raise RuntimeError('OC3 readback unavailable')


def microcheck():
    path = OUT / 'frequency_capability.json'
    previous = json.loads(path.read_text()) if path.exists() else None
    result = inspect()
    if previous:
        result['previous_observations'] = previous.get('previous_observations', []) + [
            {k: v for k, v in previous.items() if k != 'previous_observations'}]
    result['user_reported_manual_check'] = {
        'provenance': 'user report, prior to this execution',
        'MAXN': True, 'min_freq_write_315_to_1575_MHz': 'success',
        'restore_315_1575_MHz': 'success', 'idle_cur_freq_MHz': 0}
    result['set_method'] = 'ordered min_freq/max_freq sysfs writes; pin both to target; verify bounds'
    result['microcheck'] = {'classification': 'NON_PRIMARY_CAPABILITY_ONLY',
                            'input': 'synthetic zero FP32 tensor, 1x3x640x640; no throughput claim',
                            'sequence_MHz': [945,1260,1575,945],
                            'state_observation_seconds': 1.0,
                            'poll_interval_seconds': .01,
                            'minimum_matching_active_samples': 3,
                            'tegrastats_lines': [], 'errors': []}
    write_json(path, result)
    if result['status'] != 'FREQUENCY_SWITCHING_NOT_TESTED':
        return 2
    stop, ready, busy = threading.Event(), threading.Event(), threading.Event()
    progress = {'completions': 0, 'error': None}
    def workload():
        runtime = None
        try:
            import numpy as np
            from local_concurrency_tensorrt import ConcurrentTensorRT
            runtime = ConcurrentTensorRT(str(ENGINE), 1)
            worker = runtime.workers[0]
            worker.bind_thread()
            tensor = np.zeros((1,3,640,640), dtype=np.float32)
            while not stop.is_set():
                busy.set()
                worker.infer(tensor)
                busy.clear()
                progress['completions'] += 1
                ready.set()
        except BaseException:
            progress['error'] = traceback.format_exc()
            ready.set()
        finally:
            busy.clear()
            if runtime:
                runtime.close()
    thread = threading.Thread(target=workload, name='rdvg-microcheck-inference', daemon=True)
    telemetry = None
    reader = None
    try:
        result['engine_provenance'] = provenance()
        result['OC3_before'] = oc3()
        with pinned():
            # Confirm write permission using the current default values first.
            result['switching_attempted'] = True
            thread.start()
            if not ready.wait(30) or progress['error']:
                raise RuntimeError(progress['error'] or 'active GPU workload startup timeout')
            try:
                telemetry = subprocess.Popen(['/usr/bin/tegrastats', '--interval', '100'],
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                def collect():
                    for line in telemetry.stdout:
                        result['microcheck']['tegrastats_lines'].append(
                            {'timestamp_ns': time.monotonic_ns(), 'line': line.rstrip()})
                reader = threading.Thread(target=collect, daemon=True)
                reader.start()
            except OSError as error:
                result['microcheck']['tegrastats_unavailable'] = str(error)
            for mhz in (945,1260,1575,945):
                transition = {'command_timestamp_ns': time.monotonic_ns(),
                              'requested_MHz': mhz, 'samples': [],
                              'first_observed_target_timestamp_ns': None}
                result['switching_samples'].append(transition)
                transition['range_after_command_Hz'] = set_frequency(mhz)
                transition['command_return_timestamp_ns'] = time.monotonic_ns()
                deadline = time.monotonic() + 1.0
                count_before = progress['completions']
                while time.monotonic() < deadline:
                    if progress['error']:
                        raise RuntimeError(progress['error'])
                    before = busy.is_set()
                    observed = read_range()
                    stamp = time.monotonic_ns()
                    active = before and busy.is_set()
                    sample = {'timestamp_ns': stamp, 'inference_in_progress': active, **observed}
                    transition['samples'].append(sample)
                    if active and observed['cur_freq'] == mhz * 1000000:
                        if transition['first_observed_target_timestamp_ns'] is None:
                            transition['first_observed_target_timestamp_ns'] = stamp
                    time.sleep(.01)
                transition['completed_inferences'] = progress['completions'] - count_before
                matching = [s for s in transition['samples'] if s['inference_in_progress'] and s['cur_freq'] == mhz * 1000000]
                transition['active_target_sample_count'] = len(matching)
                first = transition['first_observed_target_timestamp_ns']
                transition['command_to_first_observed_ms'] = ((first-transition['command_timestamp_ns'])/1e6 if first else None)
                transition['status'] = 'PASS' if len(matching) >= 3 and transition['completed_inferences'] > 0 else 'READBACK_REVIEW_REQUIRED'
                # Retain the entire sequence for alternative telemetry review.
            result['status'] = ('FREQUENCY_CONTROL_PASS' if all(t['status']=='PASS' for t in result['switching_samples'])
                                else 'FREQUENCY_READBACK_REVIEW_REQUIRED')
            result['requested_to_actual_verified'] = result['status']=='FREQUENCY_CONTROL_PASS'
            stop.set()
            thread.join(10)
            if thread.is_alive():
                raise RuntimeError('microcheck worker failed to stop')
        result['restored_range_Hz'] = read_range()
        result['OC3_after'] = oc3()
        result['OC3_delta'] = result['OC3_after']-result['OC3_before']
        if result['OC3_delta']:
            result['status'] = 'MICROCHECK_OC3_INVALID'
    except BaseException:
        result['microcheck']['errors'].append(traceback.format_exc())
        result['status'] = 'MICROCHECK_FAILED'
    finally:
        stop.set()
        if thread.ident:
            thread.join(10)
        if telemetry:
            telemetry.terminate()
            try:
                telemetry.wait(3)
            except subprocess.TimeoutExpired:
                telemetry.kill()
                telemetry.wait()
        if reader:
            reader.join(3)
        result['range_at_exit_Hz'] = read_range()
        result['microcheck']['total_completed_inferences'] = progress['completions']
        result['microcheck']['worker_error'] = progress['error']
        write_json(path, result)
    print(json.dumps({k: result.get(k) for k in ('status','requested_to_actual_verified','OC3_delta','range_at_exit_Hz')}))
    return 0 if result['status'] == 'FREQUENCY_CONTROL_PASS' else 1


FRAME_FIELDS=['phase','stream_id','frame_id','source_timestamp_ns','logical_arrival_ns',
              'admitted','admission_timestamp_ns','admission_observed_ns','enqueue_timestamp_ns','b_ns','source_pulled_ns','ready_timestamp_ns',
              'inference_start_timestamp_ns','completion_timestamp_ns','worker_id',
              'submission_return_ns','stream_sync_return_ns','inference_queue_depth_before_enqueue']
POWER_FIELDS=['timestamp_ns','phase','requested_gpu_freq_MHz','actual_gpu_freq_MHz',
              'measured_power_W','temperature_C','OC3_count','min_freq_Hz','max_freq_Hz',
              'raw_tegrastats']


def load_plan():
    text=EXECUTION_PLAN.read_text()
    amendment=text.split('## Protocol Amendment — Unified Backlog B(t)\n',1)[1]
    plan=json.loads(amendment.split('```json\n',1)[1].split('\n```',1)[0])
    if plan['freeze_status']!='FROZEN_UNIFIED_BACKLOG':raise RuntimeError('backlog amendment not frozen')
    return plan


def logical_admit(frame_id, rate):
    """Equivalent to a zero-initialized 30-FPS phase accumulator."""
    return ((frame_id+1)*rate)//30 > (frame_id*rate)//30


def environment():
    paths=list(Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_*'))
    for device in Path('/sys/class/devfreq').glob('*'):
        paths.extend(device/name for name in ('governor','min_freq','max_freq','cur_freq'))
    clocks={}
    for p in paths:
        try: clocks[str(p)]=p.read_text().strip()
        except OSError as error: clocks[str(p)]={'unavailable':str(error)}
    return {'nvpmodel':subprocess.check_output(['nvpmodel','-q'],text=True),
            'uname':list(os.uname()),'clock_sysfs':clocks,
            'jetson_clocks':'not invoked; CPU/NVD/EMC unchanged',
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}


def run_one(condition,run_id):
    """Admission wrapper around the unchanged decode/preprocess/TRT/accounting components."""
    from profile_local_e2e import Gst,GstVideo,build_pipeline,preprocess_bgr,np,cv2
    from local_concurrency_tensorrt import ConcurrentTensorRT,ContextWorker
    from local_latency_breakdown_metrics import QueueAccounting
    from analyze_rate_dvfs_gate import summarize
    plan=load_plan()
    if json.loads((OUT/'frequency_capability.json').read_text())['status']!='FREQUENCY_CONTROL_PASS':
        raise RuntimeError('frequency microcheck must PASS')
    for source,digest in plan['source_sha256'].items():
        if hashlib.sha256((ROOT/source).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('frozen source hash mismatch: '+source)
    if condition['kind']!='smoke':
        for smoke in plan['smoke']:
            evidence=json.loads((OUT/smoke['run_id']/'summary.json').read_text())
            process_evidence=json.loads((OUT/smoke['run_id']/'manifest.json').read_text())
            if evidence['integrity_status']!='VALID' or evidence.get('PROCESS_LIFECYCLE')!='PASS' or process_evidence.get('child_returncode')!=0:
                raise RuntimeError('V2 smoke/pipeline prerequisite not PASS')
    directory=OUT/run_id
    # The supervisor reserves the fresh directory and seed manifest before launch.
    seed=json.loads((directory/'manifest.json').read_text())
    if seed.get('child_has_started'):
        raise RuntimeError('refusing to rerun an existing child directory')
    # Native TensorRT/GStreamer stdout and stderr are also retained in this log.
    log=(directory/'stderr.log').open('w')
    saved=[os.dup(1),os.dup(2)]
    os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
    frames=[];power=[];errors=[];pipelines=[];threads=[];runtime=None
    stop=threading.Event();telemetry_stop=threading.Event();lock=threading.Lock()
    ready_queue=queue.Queue();accounting=QueueAccounting()
    telemetry=None;telemetry_thread=None
    k,c=condition['K'],condition['C'];duration=condition['seconds'];rate=condition['r']
    freq={'LOW':945,'MID':1260,'HIGH':1575}[condition['frequency']]
    manifest={**seed,'child_has_started':True,'protocol_version':2,'run_id':run_id,'kind':condition['kind'],'repeat':condition.get('repeat'), 'K':k,'C':c,
              'freq_state':condition['frequency'],'requested_freq_MHz':freq,
              'admission_fps_per_stream':rate,'source_fps':30,'measurement_seconds':duration,
              'errors':errors,'queue_overflow':False,'forced_drop':False,'queue_cap_saturation':False,
              'queue_capacity':None,'warmup_inferences_per_worker':30,
              'warmup_input':'first actual decoded frame from stream 0, repeated',
              'active_start_ns':None,'active_end_ns':None,'batch_size':1,'CUDA_Graph':False,
              'plan_sha256':hashlib.sha256((OUT/'EXPERIMENT_PLAN_V2.md').read_bytes()).hexdigest(),
              'execution_manifest_sha256':hashlib.sha256(EXECUTION_PLAN.read_bytes()).hexdigest(),
              'source_sha256':plan['source_sha256'],
              'inputs':plan['inputs'][:k],'protocol_amendment':'UNIFIED_BACKLOG_B',
              'backlog_definition':'logical admitted count minus inference completion count'}
    manifest.update(summary_written=False,active_phase_completed=False,drain_completed=False,
                    cleanup_started=False,cleanup_completed=False,frequency_restore_ok=False,
                    lifecycle_events=[],child_pid=os.getpid(),status_finalized=False)
    def checkpoint(phase, **fields):
        manifest.update(fields)
        manifest['last_completed_lifecycle_phase']=phase
        manifest['last_frame_accounting_counts']={
            'source_scheduled':sum(r['phase']=='active' for r in frames),
            'source_decoded':sum(r['phase']=='active' and bool(r.get('source_pulled_ns')) for r in frames),
            'admitted':sum(r['phase']=='active' and bool(r.get('admitted')) for r in frames),
            'ready':accounting.n_enqueue,'started':accounting.n_start,
            'completed':sum(r['phase']=='active' and bool(r.get('c_ns')) for r in frames)}
        manifest['lifecycle_events'].append({'phase':phase,'monotonic_ns':time.monotonic_ns(),
                                           'utc':datetime.now(timezone.utc).isoformat()})
        write_json(directory/'manifest.json',manifest)
    if condition['kind']=='smoke':
        manifest['plan_snapshot_text']=(OUT/'EXPERIMENT_PLAN_V2.md').read_text()
    def fail(message):
        with lock: errors.append(str(message))
        stop.set()
    def sample_tensor(sample):
        info=GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        if (info.width,info.height,info.finfo.name)!=(1920,1080,'BGR'):
            raise RuntimeError('unexpected decoded caps')
        buffer=sample.get_buffer()
        ok,mapping=buffer.map(Gst.MapFlags.READ)
        if not ok: raise RuntimeError('GstBuffer map failed')
        try:
            frame=np.ndarray((1080,1920,3),dtype=np.uint8,buffer=mapping.data,strides=(info.stride[0],3,1))
            return preprocess_bgr(frame)
        finally: buffer.unmap(mapping)
    def save_records():
        for row in frames:
            for old,new in [('r_ns','ready_timestamp_ns'),('s_ns','inference_start_timestamp_ns'),('c_ns','completion_timestamp_ns')]:
                if old in row: row[new]=row[old]
            if 'r_ns' in row: row['enqueue_timestamp_ns']=row['r_ns']
        write_json(directory/'manifest.json',manifest)
        for name,fields,rows in [('per_frame.csv.gz',FRAME_FIELDS,frames),('power_trace.csv.gz',POWER_FIELDS,power)]:
            with gzip.open(directory/name,'wt',newline='') as target:
                writer=csv.DictWriter(target,fieldnames=fields,extrasaction='ignore')
                writer.writeheader();writer.writerows(rows)
    def save():
        save_records()
        try: summary=summarize(manifest,frames,power)
        except BaseException:
            summary={'protocol_version':2,'run_id':run_id,'kind':condition['kind'],
                     'integrity_status':'INVALID','validity':'INVALID',
                     'hardware_status':'PROTECTION_LIMITED' if manifest.get('OC3_after',0)>manifest.get('OC3_before',0) else 'CLEAN',
                     'errors':errors+[traceback.format_exc()]}
        summary['measurement_integrity_status']=summary['integrity_status']
        summary['integrity_status']='PENDING_PROCESS_EXIT'
        summary['validity']='PENDING_PROCESS_EXIT'
        summary['status_finalized']=False
        write_json(directory/'summary.json',summary)
        checkpoint('summary_written',summary_written=True)
        return summary
    try:
        # Reuse the already verified provenance; do not repeat the capability workload.
        manifest['engine_provenance']=json.loads((OUT/'frequency_capability.json').read_text())['engine_provenance']
        manifest['environment_before']=environment()
        manifest['OC3_before']=oc3()
        write_json(directory/'manifest.json',manifest)
        checkpoint('preflight_completed')
        Gst.init(None);cv2.setNumThreads(1)
        with pinned(freq):
            runtime=ConcurrentTensorRT(str(ENGINE),2)
            for worker_id in range(2,c): runtime.workers.append(ContextWorker(runtime.engine,worker_id))
            resources=[w.resources() for w in runtime.workers]
            for field in ('context_object_id','cuda_stream_pointer'):
                if len({r[field] for r in resources})!=c: raise RuntimeError('aliased contexts/streams')
            for field in ('device_buffers','pinned_host_buffers'):
                pointers=[p for r in resources for p in r[field].values()]
                if len(set(pointers))!=len(pointers):raise RuntimeError('aliased private buffers')
            manifest['resources']=resources
            manifest['TensorRT_version']=__import__('tensorrt').__version__
            checkpoint('resources_created')
            warm_pipeline,_,warm_sink=build_pipeline(plan['inputs'][0]['path'])
            try:
                if warm_pipeline.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:
                    raise RuntimeError('warm-up source start failed')
                sample=warm_sink.emit('try-pull-sample',5*Gst.SECOND)
                if sample is None: raise RuntimeError('warm-up source sample missing')
                warm_tensor=sample_tensor(sample)
            finally:
                warm_pipeline.set_state(Gst.State.NULL)
            arrival_queues=[queue.Queue() for _ in range(k)]
            warm_ready=[threading.Event() for _ in range(c)]
            front_done=[threading.Event() for _ in range(k)]
            sinks=[];eos=[False]*k
            for entry in plan['inputs'][:k]:
                pipeline,_,sink=build_pipeline(entry['path']);pipelines.append(pipeline);sinks.append(sink)
            def infer(worker_id):
                try:
                    worker=runtime.workers[worker_id];worker.bind_thread()
                    for number in range(30):
                        row={'phase':'warmup','stream_id':-1,'frame_id':worker_id*30+number,
                             'admitted':1,'worker_id':worker_id,'inference_start_timestamp_ns':time.monotonic_ns()}
                        worker.infer(warm_tensor)
                        row['completion_timestamp_ns']=time.monotonic_ns()
                        with lock: frames.append(row)
                    warm_ready[worker_id].set()
                    while not stop.is_set():
                        try: job=ready_queue.get(timeout=.05)
                        except queue.Empty:
                            if all(x.is_set() for x in front_done):break
                            continue
                        job['worker_id']=worker_id
                        with lock:accounting.start(job,time.monotonic_ns)
                        outputs=worker.infer(job['tensor'])
                        job['c_ns']=time.monotonic_ns()
                        job['submission_return_ns']=worker.submission_return_ns
                        job['stream_sync_return_ns']=worker.stream_sync_return_ns
                        if set(outputs)!={'pred_logits','pred_boxes'}:raise RuntimeError('unexpected outputs')
                        del job['tensor']
                except BaseException:fail('inference: '+traceback.format_exc())
            def front(stream_id):
                try:
                    for _ in range(int(duration*30)):
                        while not stop.is_set():
                            try:job=arrival_queues[stream_id].get(timeout=.05);break
                            except queue.Empty:continue
                        else:return
                        job['b_ns']=time.monotonic_ns()
                        # Waiting for decode is unfinished admitted work, not an abort.
                        while not stop.is_set():
                            sample=sinks[stream_id].emit('try-pull-sample',Gst.SECOND)
                            if sample is not None:break
                            if eos[stream_id]:raise RuntimeError(f'stream {stream_id}: unexpected EOS')
                        else:return
                        job['source_pulled_ns']=time.monotonic_ns()
                        job['source_timestamp_ns']=int(sample.get_buffer().pts)
                        if job['admitted']:
                            job['tensor']=sample_tensor(sample)
                            with lock:accounting.enqueue(ready_queue,job,time.monotonic_ns)
                except BaseException:fail('front end: '+traceback.format_exc())
                finally:front_done[stream_id].set()
            def arrivals():
                try:
                    for frame_id in range(int(duration*30)):
                        target=manifest['active_start_ns']+frame_id*10**9//30
                        wait=(target-time.monotonic_ns())/1e9
                        if wait>0 and stop.wait(wait):return
                        if stop.is_set():return
                        for stream_id in range(k):
                            now=time.monotonic_ns()
                            row={'phase':'active','stream_id':stream_id,'frame_id':frame_id,
                                 'logical_arrival_ns':target,'admitted':int(logical_admit(frame_id,rate)),
                                 'admission_timestamp_ns':target,'admission_observed_ns':now,
                                 'enqueue_timestamp_ns':''}
                            with lock:frames.append(row)
                            arrival_queues[stream_id].put(row)
                except BaseException:fail('source scheduler: '+traceback.format_exc())
            telemetry=subprocess.Popen(['/usr/bin/tegrastats','--interval','100'],stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT,text=True)
            def monitor():
                try:
                    for line in telemetry.stdout:
                        if telemetry_stop.is_set():break
                        watts=re.search(r'\bVDD_GPU (\d+)mW/',line)
                        temp=re.search(r'\bgpu@([\d.]+)C',line)
                        if not watts or not temp:continue
                        stamp=time.monotonic_ns();freqs=read_range();count=oc3()
                        phase='warmup' if manifest['active_start_ns'] is None or stamp<manifest['active_start_ns'] else 'active' if stamp<manifest['active_end_ns'] else 'drain'
                        power.append({'timestamp_ns':stamp,'phase':phase,'requested_gpu_freq_MHz':freq,
                                      'actual_gpu_freq_MHz':freqs['cur_freq']/1e6,
                                      'measured_power_W':int(watts[1])/1000,'temperature_C':float(temp[1]),
                                      'OC3_count':count,'min_freq_Hz':freqs['min_freq'],'max_freq_Hz':freqs['max_freq'],
                                      'raw_tegrastats':line.rstrip()})
                        # OC3 and actual clock limitations are observed hardware behavior,
                        # not integrity failures. Preserve them and finish the active interval.
                    if not telemetry_stop.is_set():fail('power telemetry ended unexpectedly')
                except BaseException:fail('telemetry: '+traceback.format_exc())
            telemetry_thread=threading.Thread(target=monitor,daemon=True);telemetry_thread.start()
            for worker_id in range(c):
                thread=threading.Thread(target=infer,args=(worker_id,),daemon=True)
                thread.start();threads.append(thread)
            limit=time.monotonic()+30
            while not all(x.is_set() for x in warm_ready) or len(power)<3:
                if stop.wait(.02):raise RuntimeError('warm-up failed')
                if time.monotonic()>limit:raise RuntimeError('warm-up/telemetry timeout')
            manifest['premeasurement_queue_empty']=(ready_queue.empty() and accounting.n_enqueue==0 and accounting.n_start==0)
            if not manifest['premeasurement_queue_empty']:raise RuntimeError('warm-up left queued work')
            checkpoint('warmup_completed')
            for pipeline in pipelines:
                if pipeline.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('source pipeline failed to start')
            manifest['active_start_ns']=time.monotonic_ns()+200000000
            manifest['active_end_ns']=manifest['active_start_ns']+int(duration*10**9)
            for stream_id in range(k):
                thread=threading.Thread(target=front,args=(stream_id,),daemon=True);thread.start();threads.append(thread)
            scheduler=threading.Thread(target=arrivals,daemon=True);scheduler.start();threads.append(scheduler)
            write_json(directory/'manifest.json',manifest)
            checkpoint('active_started')
            deadline=time.monotonic()+duration+180
            while not stop.is_set():
                if not manifest['active_phase_completed'] and time.monotonic_ns()>=manifest['active_end_ns']:
                    checkpoint('active_phase_completed',active_phase_completed=True)
                for i,pipeline in enumerate(pipelines):
                    message=pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR|Gst.MessageType.EOS)
                    if message and message.type==Gst.MessageType.ERROR:
                        error,debug=message.parse_error();fail(f'source {i}: {error}; {debug}')
                    elif message and message.type==Gst.MessageType.EOS:eos[i]=True
                all_done=all(not t.is_alive() for t in threads)
                fullsource=duration==60
                if all_done and (not fullsource or all(eos)) and time.monotonic_ns()>manifest['active_end_ns']+300000000:break
                if time.monotonic()>deadline:raise RuntimeError('drain/source EOS watchdog timeout')
                stop.wait(.02)
            manifest['source_EOS']=eos
            if errors:raise RuntimeError('run stopped after recorded failure')
            manifest['ready_queue_accounting']={'enqueue':accounting.n_enqueue,'start':accounting.n_start}
            if accounting.n_enqueue!=accounting.n_start:raise RuntimeError('ready queue accounting mismatch')
            checkpoint('drain_completed',drain_completed=True)
            checkpoint('cleanup_started',cleanup_started=True)
            # Stop telemetry before restoring so restore values cannot enter active traces.
            telemetry_stop.set();telemetry.terminate();telemetry.wait(3);telemetry_thread.join(3)
            save_records()
            checkpoint('raw_measurements_written')
            for pipeline in pipelines:
                if pipeline.set_state(Gst.State.NULL)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('pipeline NULL failure')
                if pipeline.get_state(3*Gst.SECOND)[1]!=Gst.State.NULL:raise RuntimeError('pipeline not NULL')
            manifest['clean_shutdown']=True
            checkpoint('pipelines_null')
        manifest['restored_range_Hz']=read_range()
        restored=manifest['restored_range_Hz']
        checkpoint('frequency_restored',frequency_restore_ok=(restored['min_freq'],restored['max_freq'])==(315000000,1575000000))
    except BaseException:
        errors.append(traceback.format_exc());stop.set()
    finally:
        if not manifest['cleanup_started']:checkpoint('cleanup_started',cleanup_started=True)
        stop.set();telemetry_stop.set()
        for pipeline in pipelines:
            try:pipeline.set_state(Gst.State.NULL)
            except BaseException:errors.append('pipeline cleanup: '+traceback.format_exc())
        for thread in threads:thread.join(6)
        alive=[t.name for t in threads if t.is_alive()]
        if alive:errors.append('workers still alive: '+str(alive))
        if telemetry and telemetry.poll() is None:
            telemetry.terminate()
            try:telemetry.wait(3)
            except subprocess.TimeoutExpired:telemetry.kill();telemetry.wait()
        if telemetry_thread:telemetry_thread.join(3)
        if runtime and not alive:
            checkpoint('tensorrt_cleanup_started')
            try:runtime.close()
            except BaseException:errors.append('TRT cleanup: '+traceback.format_exc())
        try:
            manifest['OC3_after']=oc3();manifest['range_at_exit_Hz']=read_range()
            manifest['environment_after']=environment()
            if (manifest['range_at_exit_Hz']['min_freq'],manifest['range_at_exit_Hz']['max_freq'])!=(315000000,1575000000):
                errors.append('default frequency range not restored')
            else:manifest['frequency_restore_ok']=True
        except BaseException:errors.append('postflight: '+traceback.format_exc())
        checkpoint('cleanup_completed' if not errors and not alive else 'cleanup_incomplete',cleanup_completed=not errors and not alive)
        summary=save()
        sys.stdout.flush();sys.stderr.flush()
        os.dup2(saved[0],1);os.dup2(saved[1],2)
        for fd in saved:os.close(fd)
        log.close()
    print(json.dumps({'run_id':run_id,'integrity_status':summary['integrity_status'],
                      'hardware_status':summary['hardware_status'],
                      'pipeline_audit_status':summary.get('pipeline_audit_status'),
                      'queue_classification':summary.get('queue_classification'),
                      'completed_fps':summary.get('aggregate_completed_fps'),'errors':summary['errors']}),flush=True)
    return 0 if summary['measurement_integrity_status']=='VALID' else 1


def kernel_evidence(start, end):
    """Optional read-only query. Never escalates or invokes sudo."""
    command=['journalctl','-k','--no-pager','-o','short-iso',
             '--since',start.strftime('%Y-%m-%d %H:%M:%S UTC'),
             '--until',end.strftime('%Y-%m-%d %H:%M:%S UTC')]
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=10)
        matches=[line for line in result.stdout.splitlines() if re.search(r'segfault|out of memory|oom|xid|nvrm|killed process|process.*kill|gpu.*error',line,re.I)]
        return {'command':command,'returncode':result.returncode,'stderr':result.stderr[-16000:],
                'matching_lines':matches[-100:],
                'availability':'query completed; no matching entries' if result.returncode==0 and not matches else 'query completed' if result.returncode==0 else 'unavailable'}
    except (OSError,subprocess.TimeoutExpired) as error:
        return {'command':command,'availability':'unavailable','reason':str(error)}


LIFECYCLE_FIELDS=['child_pid','child_returncode','child_exit_signal','child_start_time','child_exit_time',
                  'summary_written','active_phase_completed','drain_completed','cleanup_started',
                  'cleanup_completed','frequency_restore_ok','last_completed_lifecycle_phase',
                  'last_frame_accounting_counts','child_stdout_tail','child_stderr_tail']


def finalize_run(directory, process_info, stdout='', stderr=''):
    """Finish this newly executed run only after wait() has observed child exit."""
    from analyze_rate_dvfs_gate import summarize,read_csv
    with (directory/'stderr.log').open('a') as log:
        log.write('\nSUPERVISOR_STDOUT_TAIL\n'+stdout[-16000:]+'\nSUPERVISOR_STDERR_TAIL\n'+stderr[-16000:])
        log.write('\nSUPERVISOR_PROCESS_OUTCOME '+json.dumps(process_info)+'\n')
    manifest=json.loads((directory/'manifest.json').read_text())
    manifest.update(process_info)
    manifest['process_exit_code']=process_info['child_returncode']
    manifest['child_stdout_tail']=stdout[-16000:]
    logtail=(directory/'stderr.log').read_text(errors='replace')[-20000:]
    manifest['child_stderr_tail']=logtail
    current=read_range()
    manifest['supervisor_observed_frequency_range_Hz']=current
    manifest['frequency_restore_ok']=bool(manifest.get('frequency_restore_ok')) and (current['min_freq'],current['max_freq'])==(315000000,1575000000)
    frames=read_csv(directory/'per_frame.csv.gz');power=read_csv(directory/'power_trace.csv.gz')
    try:
        measured=summarize(manifest,frames,power)
    except BaseException:
        measured={'integrity_status':'INVALID','pipeline_audit_status':'INCONCLUSIVE',
                  'errors':['analysis failed: '+traceback.format_exc()],
                  'hardware_status':'PROTECTION_LIMITED' if manifest.get('OC3_after',0)>manifest.get('OC3_before',0) else 'CLEAN'}
    mandatory=('summary_written','active_phase_completed','drain_completed','cleanup_started','cleanup_completed','frequency_restore_ok')
    lifecycle_ok=process_info['child_returncode']==0 and all(manifest.get(field) is True for field in mandatory)
    process_errors=[]
    if process_info['child_returncode']!=0:
        process_errors.append(f"PROCESS_EXIT_FAILURE: returncode={process_info['child_returncode']}, signal={process_info['child_exit_signal']}")
    for field in mandatory:
        if manifest.get(field) is not True:process_errors.append('lifecycle incomplete: '+field)
    manifest['errors'].extend(process_errors)
    manifest['status_finalized']=True
    manifest['PIPELINE_SEMANTICS']=measured.get('pipeline_audit_status','INCONCLUSIVE')
    manifest['PROCESS_LIFECYCLE']='PASS' if lifecycle_ok else 'FAIL'
    manifest['PIPELINE_AUDIT']='PASS' if lifecycle_ok and manifest['PIPELINE_SEMANTICS']=='PASS' else 'FAIL'
    final=dict(measured)
    final.update({name:manifest.get(name) for name in LIFECYCLE_FIELDS})
    final.update(PIPELINE_SEMANTICS=manifest['PIPELINE_SEMANTICS'],PROCESS_LIFECYCLE=manifest['PROCESS_LIFECYCLE'],
                 PIPELINE_AUDIT=manifest['PIPELINE_AUDIT'],status_finalized=True,
                 measurement_integrity_status=measured['integrity_status'],
                 errors=measured['errors']+process_errors)
    final['integrity_status']='VALID' if measured['integrity_status']=='VALID' and lifecycle_ok else 'INVALID'
    final['validity']=final['integrity_status']
    if final['integrity_status']!='VALID':
        final.update(queue_stable=False,backlog_stable=False,queue_classification='INVALID',energy_per_frame_J=None)
    if process_info['child_returncode']!=0:
        begin=datetime.fromisoformat(process_info['child_start_time'])
        end=datetime.fromisoformat(process_info['child_exit_time'])
        manifest['kernel_evidence']=kernel_evidence(begin,end)
        final['kernel_evidence']=manifest['kernel_evidence']
    write_json(directory/'manifest.json',manifest)
    write_json(directory/'summary.json',final)
    return final


def recovery_report(plan):
    """Evaluate the two amendment smokes; do not rewrite historical reports."""
    summaries=[]
    for condition in plan['smoke']:
        path=OUT/condition['run_id']/'summary.json'
        if path.exists():summaries.append(json.loads(path.read_text()))
    good=len(summaries)==2 and all(s['integrity_status']=='VALID' and s['child_returncode']==0
                                  and s['PROCESS_LIFECYCLE']=='PASS' and s.get('backlog_after_drain')==0 for s in summaries)
    return good,'BACKLOG_SMOKE_PASS' if good else 'BACKLOG_SMOKE_FAIL'


def campaign(stage):
    plan=load_plan()
    if stage=='primary':
        good,_=recovery_report(plan)
        if not good:raise RuntimeError('both unified-backlog smokes must PASS before primary')
    conditions=plan['smoke'] if stage in ('smoke','recovery') else plan['order']
    for condition in conditions:
        directory=OUT/condition['run_id'];directory.mkdir(exist_ok=False)
        begin=datetime.now(timezone.utc);start_ns=time.monotonic_ns()
        seed={'protocol_version':2,'run_id':condition['run_id'],'kind':condition['kind'],
              'repeat':condition.get('repeat'),'K':condition['K'],'C':condition['C'],
              'freq_state':condition['frequency'],'requested_freq_MHz':{'LOW':945,'MID':1260,'HIGH':1575}[condition['frequency']],
              'admission_fps_per_stream':condition['r'],'errors':[],
              'child_start_time':begin.isoformat(),'child_start_monotonic_ns':start_ns,
              'child_returncode':None,'child_exit_signal':None,'child_pid':None,
              'summary_written':False,'active_phase_completed':False,'drain_completed':False,
              'cleanup_started':False,'cleanup_completed':False,'frequency_restore_ok':False,
              'status_finalized':False,'active_start_ns':None,'active_end_ns':None}
        write_json(directory/'manifest.json',seed)
        (directory/'stderr.log').touch()
        for filename,fields in [('per_frame.csv.gz',FRAME_FIELDS),('power_trace.csv.gz',POWER_FIELDS)]:
            with gzip.open(directory/filename,'wt',newline='') as stream:csv.DictWriter(stream,fieldnames=fields).writeheader()
        command=[sys.executable,'-X','faulthandler','-B',str(Path(__file__).resolve()),'one','--run-id',condition['run_id']]
        print('START '+condition['run_id'],flush=True)
        process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        timed_out=False
        try:stdout,stderr=process.communicate(timeout=condition['seconds']+300)
        except subprocess.TimeoutExpired:
            timed_out=True;process.terminate()
            try:stdout,stderr=process.communicate(timeout=15)
            except subprocess.TimeoutExpired:process.kill();stdout,stderr=process.communicate()
        end=datetime.now(timezone.utc)
        signo=-process.returncode if process.returncode<0 else None
        info={'child_pid':process.pid,'child_returncode':process.returncode,
              'child_exit_signal':signal.Signals(signo).name if signo else None,
              'child_start_time':begin.isoformat(),'child_exit_time':end.isoformat(),
              'child_start_monotonic_ns':start_ns,'child_exit_monotonic_ns':time.monotonic_ns(),
              'supervisor_timeout':timed_out}
        finalized=finalize_run(directory,info,stdout,stderr)
        print(json.dumps({key:finalized.get(key) for key in ('child_pid','child_returncode','child_exit_signal','integrity_status','hardware_status','supply_status','OC3_delta','frequency_restore_ok','PROCESS_LIFECYCLE','aggregate_completed_fps','g_B')}),flush=True)
        # Integrity-invalid conditions are retained without automatic retries.
        # Source/decode under-delivery and OC3 never terminate the campaign.
        current=read_range()
        if (current['min_freq'],current['max_freq'])!=(315000000,1575000000):
            print('RESTORE_BLOCKER',flush=True);return 3
    if stage in ('smoke','recovery'):
        good,outcome=recovery_report(plan)
        print(outcome,flush=True)
        return 0 if good else 2
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('microcheck','smoke','recovery','primary','one'))
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.action=='microcheck':result=microcheck()
    elif args.action in ('smoke','recovery','primary'):result=campaign(args.action)
    else:
        plan=load_plan()
        matches=[x for x in plan['smoke']+plan['order'] if x['run_id']==args.run_id]
        if len(matches)!=1:raise RuntimeError('run ID must occur exactly once in frozen plan')
        result=run_one(matches[0],args.run_id)
    raise SystemExit(result)
