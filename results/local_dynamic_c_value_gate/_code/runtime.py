"""New bounded dynamic-trace adapter; immutable Formal GPU/preprocess reused."""
import argparse,sys,threading,time,traceback,json
from core import *
sys.path.insert(0,str(FORMAL/'_campaign'))
from profile_fullsource import ConcurrentTensorRT, original_build_pipeline, Gst, GstVideo, GLib, cv2, np, preprocess_bgr

def main():
 p=argparse.ArgumentParser();p.add_argument('--acquisition-id',required=True);args=p.parse_args()
 plans=json.loads((ROOT/'frozen_plan.json').read_text());row=next(r for r in plans['acquisitions'] if r['acquisition_id']==args.acquisition_id)
 out=ROOT/row['acquisition_id'];assert out.is_dir() and not (out/'runtime_metadata.json').exists()
 manifest=json.loads((ROOT/'input_manifest.json').read_text());plan=Trace(row['trace'],row['duration_s']);state=State(plan,row['policy'])
 save(out/'runtime_metadata.json',dict(row=row,P=4,B=1,warmup_inferences=0,CUDA_Graph=False,deadline='exact 1/30s; (c-a)*30>1e9',timestamp_definitions=plans['timestamp_definitions'],termination='planned sample-budget completion, not full-source EOS',input_manifest_sha256=plans['input_manifest_sha256']))
 Gst.init(None);cv2.setNumThreads(1)
 inference=None;pipelines=[];sinks=[];threads=[];joined={};eos=[False]*7;null=[False]*7;samples=[0]*7;front_done=[False]*7;worker_errors=[];watchdog=[False];started=threading.Event();loop=GLib.MainLoop()
 try:
  inference=ConcurrentTensorRT(manifest['engine']['path'],4);save(out/'resources.json',inference.resources)
  assert inference.resources['num_aux_streams_per_context']==manifest['num_aux_streams_per_context']
  for v in manifest['videos']:
   pipe,_,sink=original_build_pipeline(v['path']);pipelines.append(pipe);sinks.append(sink)
  def fail(where):
   detail=where+': '+traceback.format_exc();worker_errors.append(detail);state.fail(detail);GLib.idle_add(loop.quit)
  def front(sid):
   try:
    for _ in range(plan.samples[sid]):
     while not state.stop:
      try:j=state.arrival[sid].get(timeout=.1);break
      except queue.Empty:continue
     else:return
     j['b_ns']=time.perf_counter_ns()
     sample=sinks[sid].emit('pull-sample')
     if sample is None:raise RuntimeError(f'stream {sid} no sample before planned budget completion')
     info=GstVideo.VideoInfo.new_from_caps(sample.get_caps())
     if (info.width,info.height,info.finfo.name)!=(1920,1080,'BGR'):raise RuntimeError('unexpected source caps')
     buf=sample.get_buffer();ok,mapping=buf.map(Gst.MapFlags.READ)
     if not ok:raise RuntimeError('buffer map failed')
     assert j['source_sample_index']==samples[sid];samples[sid]+=1
     try:
      frame=np.ndarray((1080,1920,3),dtype=np.uint8,buffer=mapping.data,strides=(info.stride[0],3,1))
      tensor=preprocess_bgr(frame)
     finally:buf.unmap(mapping)
     j['tensor']=tensor;state.enqueue(j)
    front_done[sid]=True
   except Exception:fail(f'front {sid}')
  def worker(wid):
   try:
    w=inference.workers[wid];w.bind_thread();started.wait()
    while not state.stop:
     with state.cv:
      if state.completed==len(plan.jobs):break
     j=state.admit(wid)
     if j is None:
      with state.cv:
       if state.completed==len(plan.jobs):break
       if state.active>=state.cap or state.ready.empty():state.cv.wait(timeout=.1)
      continue
     outputs=w.infer(j['tensor']);j['c_ns']=time.perf_counter_ns()
     if set(outputs)!={'pred_logits','pred_boxes'}:raise RuntimeError('unexpected TensorRT outputs')
     j['submission_return_ns']=w.submission_return_ns;j['stream_sync_return_ns']=w.stream_sync_return_ns
     del j['tensor'];state.publish_completion(j)
   except Exception:fail(f'inference {wid}')
  def producer():
   try:
    for template in plan.jobs:
     target=state.t0+template['offset_ns'];remaining=target-time.perf_counter_ns()
     if remaining>0:
      with state.cv:state.cv.wait_for(lambda:state.stop,timeout=remaining/1e9)
     if state.stop:return
     state.generate(template)
   except Exception:fail('producer')
  def boundary_worker():
   try:
    for offset,_,_ in plan.boundaries:
     remaining=state.t0+offset-time.perf_counter_ns()
     if remaining>0:
      with state.cv:state.cv.wait_for(lambda:state.stop,timeout=remaining/1e9)
     if state.stop:return
     with state.cv:state.apply_due()
   except Exception:fail('workload boundary')
  def bus_message(bus,msg,sid):
   if msg.type==Gst.MessageType.ERROR:
    error,debug=msg.parse_error();state.fail(f'GStreamer {sid}: {error}; {debug}');loop.quit()
   elif msg.type==Gst.MessageType.EOS:
    eos[sid]=True
    with state.cv:state.event('natural_bus_EOS',stream_id=sid)
  for sid,pipe in enumerate(pipelines):
   bus=pipe.get_bus();bus.add_signal_watch();bus.connect('message',bus_message,sid)
   if pipe.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('PLAYING failed')
  for sid in range(7):
   t=threading.Thread(target=front,args=(sid,),name=f'front-{sid}');t.start();threads.append(t)
  for wid in range(4):
   t=threading.Thread(target=worker,args=(wid,),name=f'inference-{wid}');t.start();threads.append(t)
  state.initialize(time.perf_counter_ns()+100000000);started.set()
  for fn,name in [(producer,'producer'),(boundary_worker,'boundary')]:
   t=threading.Thread(target=fn,name=name);t.start();threads.append(t)
  def finish():
   if state.stop or (state.completed==len(plan.jobs) and all(front_done)):loop.quit();return False
   return True
  def timeout():
   watchdog[0]=True;state.fail('300s runtime watchdog');loop.quit();return False
  GLib.timeout_add(100,finish);GLib.timeout_add_seconds(300,timeout);loop.run()
 except Exception:
  state.fail('runtime/setup: '+traceback.format_exc())
 finally:
  state.stop=True;started.set()
  with state.cv:state.cv.notify_all()
  if state.completed==len(plan.jobs):
   for t in threads:t.join(timeout=5);joined[t.name]=not t.is_alive()
  for sid,pipe in enumerate(pipelines):
   try:
    bus=pipe.get_bus()
    while True:
     msg=bus.pop_filtered(Gst.MessageType.ERROR|Gst.MessageType.EOS)
     if msg is None:break
     if msg.type==Gst.MessageType.EOS:eos[sid]=True
     else:state.errors.append('bus error at teardown: '+str(msg.parse_error()))
    result=pipe.set_state(Gst.State.NULL);ret,current,pending=pipe.get_state(5*Gst.SECOND)
    null[sid]=result!=Gst.StateChangeReturn.FAILURE and ret!=Gst.StateChangeReturn.FAILURE and current==Gst.State.NULL
   except Exception:state.errors.append('teardown: '+traceback.format_exc())
  for t in threads:
   if t.is_alive():t.join(timeout=5)
   joined[t.name]=not t.is_alive()
  if any(not v for v in joined.values()):state.errors.append('worker join failure')
  if inference is not None and all(joined.values()):
   try:inference.close()
   except Exception:state.errors.append('inference cleanup: '+traceback.format_exc())
  clean=[]
  for j in state.records:
   clean.append(dict(acquisition_id=row['acquisition_id'],round=row['round'],trace=row['trace'],policy=row['policy'],**{k:v for k,v in j.items() if k!='tensor'}))
  csvout(out/'per_frame.csv',clean,fields=None if clean else ['request_id','a_ns','b_ns','r_ns','s_ns','c_ns'])
  csvout(out/'events.csv',state.events,fields=None if state.events else ['seq','kind','ns'])
  save(out/'termination.json',dict(t0_ns=state.t0,expected=len(plan.jobs),generated=state.generated,enqueued=state.enqueued,started=state.started,completed=state.completed,
       samples=samples,front_done=front_done,natural_EOS_observed=eos,trace_budget_termination=True,EOS_not_required=True,
       waiting_after_drain=state.enqueued-state.started,active_counter_after_drain=state.active,backlog_published_after_drain=state.generated-state.completed,
       due_not_generated_after_drain=len(plan.jobs)-state.generated,joined=joined,pipeline_NULL=null,watchdog_triggered=watchdog[0],runtime_errors=state.errors,worker_errors=worker_errors))
 return 0 if not state.errors and state.completed==len(plan.jobs) and all(null) and all(joined.values()) else 1
if __name__=='__main__':sys.exit(main())
