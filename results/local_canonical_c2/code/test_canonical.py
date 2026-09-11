import unittest,copy
import run_fullsource as runner
from screening_validation import validate_concurrency
from termination_contract import validate_termination
from test_bounded_termination import fixture

def resources():
 r={k:2 for k in ('configured_workers','execution_context_count','cuda_stream_count','submission_stream_count','buffer_set_count','pinned_staging_set_count')};r['engine_instance_count']=1
 r['workers']=[{'worker_id':i,'context_object_id':i+1,'cuda_stream_pointer':i+10,
 'device_buffers':{n:1000+i*1000+j*100 for j,n in enumerate(('inputs','pred_logits','pred_boxes'))},
 'pinned_host_buffers':{n:10000+i*1000+j*100 for j,n in enumerate(('inputs','pred_logits','pred_boxes'))},
 'buffer_bytes':{n:10 for n in ('inputs','pred_logits','pred_boxes')}} for i in range(2)]
 return r

def record(w,s,c):
 return dict(worker_id=w,context_id=w,s_ns=s,c_ns=c,service_start_ns=s,service_completion_ns=c,submission_return_ns=s+1,stream_sync_return_ns=c-1)
class CanonicalTests(unittest.TestCase):
 def test_exact_plan(self):
  p=runner.plan();self.assertEqual(len(p['runs']),35);self.assertEqual(len({(r['K'],r['rep']) for r in p['runs']}),35)
  self.assertEqual(sum(r['K']*1800 for r in p['runs']),252000)
  for rep in range(1,6):self.assertEqual([r['K'] for r in p['runs'] if r['rep']==rep],list(range(rep,8))+list(range(1,rep)))
  self.assertTrue(all(r['C']==2 and '--formal' in r['argv'] and '1800' in r['argv'] for r in p['runs']))
 def test_other_C_rejected(self):
  with self.assertRaises(AssertionError):runner.command(4,5,1)
 def test_low_load_no_overlap_valid(self):
  r=validate_concurrency([record(0,0,10),record(0,30,40)],resources(),2)
  self.assertEqual(r['max_active_inferences'],1);self.assertEqual(r['workers_actually_used'],1);self.assertEqual(r['service_overlap_pair_count'],0)
 def test_same_worker_overlap_rejected(self):
  with self.assertRaises(ValueError):validate_concurrency([record(0,0,100),record(0,10,40)],resources(),2)
 def test_buffer_alias_rejected(self):
  r=resources();r['workers'][1]['device_buffers']['inputs']=1000
  with self.assertRaises(ValueError):validate_concurrency([record(0,0,10)],r,2)
 def test_full_EOS_required(self):
  e=fixture();e['mode']='full_source'
  for s in e['per_stream']:s['eos_observed']=True
  self.assertEqual(validate_termination(e)['validation'],'PASS')
  e['per_stream'][0]['eos_observed']=False
  self.assertEqual(validate_termination(e)['validation'],'FAIL')
 def test_NULL_required(self):
  e=fixture();e['mode']='full_source'
  for s in e['per_stream']:s['eos_observed']=True
  e['per_stream'][0]['pipeline_NULL_confirmed']=False
  self.assertEqual(validate_termination(e)['validation'],'FAIL')
if __name__=='__main__':unittest.main()
