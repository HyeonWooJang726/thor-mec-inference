import copy
import unittest
from termination_contract import validate_termination

def fixture():
    return {'mode':'bounded','frames_per_stream':2,'streams':2,
      'per_stream':[{'source_samples_pulled':2,'frame_ids':[0,1],
        'source_loop_normal_return':True,'source_joined':True,'pipeline_shutdown_requested':True,
        'pipeline_NULL_confirmed':True,'worker_exception':None,'gstreamer_errors':[],
        'eos_observed':False} for _ in range(2)],
      'counts':dict(arrivals=4,samples=4,preprocessed=4,completed=4,per_frame_rows=4),
      'timing':{'ordering_violations':0,'decomposition_violations':0},
      'waiting_after_drain':0,'active_after_drain':0,'negative_waiting_depth_events':0,
      'all_workers_joined':True,'watchdog_triggered':False,'runtime_errors':[]}

class BoundedTests(unittest.TestCase):
    def check_failure(self, change):
        e=fixture();change(e);self.assertEqual(validate_termination(e)['validation'],'FAIL')
    def test_exact_budget_without_EOS(self):
        e=fixture();before=copy.deepcopy(e);result=validate_termination(e)
        self.assertEqual(result['validation'],'PASS');self.assertEqual(e,before)
        self.assertEqual(result['bounded_complete'],[True,True])
    def test_incomplete_budget(self):
        self.check_failure(lambda e:e['per_stream'][1].update(source_samples_pulled=1))
    def test_incomplete_frame_completion(self):
        self.check_failure(lambda e:e['counts'].update(completed=3))
    def test_waiting_not_drained(self):
        self.check_failure(lambda e:e.update(waiting_after_drain=1))
    def test_active_not_drained(self):
        self.check_failure(lambda e:e.update(active_after_drain=1))
    def test_source_join_failure(self):
        self.check_failure(lambda e:e['per_stream'][1].update(source_joined=False))
    def test_gstreamer_error(self):
        self.check_failure(lambda e:e['per_stream'][1].update(gstreamer_errors=['decoder error']))
    def test_watchdog(self):
        self.check_failure(lambda e:e.update(watchdog_triggered=True))
    def test_actual_bus_EOS_metadata_true(self):
        e=fixture();e['per_stream'][0]['eos_observed']=True
        self.assertEqual(validate_termination(e)['eos_observed'],[True,False])
    def test_missing_EOS_metadata_false_not_faked(self):
        e=fixture();result=validate_termination(e)
        self.assertEqual(result['eos_observed'],[False,False]);self.assertEqual(result['missing_bus_EOS_stream_ids'],[0,1])
        self.assertFalse(any(s['eos_observed'] for s in e['per_stream']))
    def test_full_source_requires_natural_EOS(self):
        e=fixture();e['mode']='full_source'
        self.assertEqual(validate_termination(e)['validation'],'FAIL')
        for s in e['per_stream']:s['eos_observed']=True
        self.assertEqual(validate_termination(e)['validation'],'PASS')
    def test_shutdown_failure(self):
        self.check_failure(lambda e:e['per_stream'][0].update(pipeline_NULL_confirmed=False))
    def test_worker_exception(self):
        self.check_failure(lambda e:e['per_stream'][0].update(worker_exception='failed'))
    def test_source_loop_early_return(self):
        self.check_failure(lambda e:e['per_stream'][0].update(source_loop_normal_return=False))
    def test_duplicate_missing_IDs(self):
        self.check_failure(lambda e:e['per_stream'][0].update(frame_ids=[0,0]))
    def test_delayed_source_completion_and_join(self):
        e=fixture();e['per_stream'][1]['source_loop_normal_return']=False
        self.assertEqual(validate_termination(e)['validation'],'FAIL')
        e['per_stream'][1]['source_loop_normal_return']=True;e['per_stream'][1]['source_joined']=False
        self.assertEqual(validate_termination(e)['validation'],'FAIL')
        e['per_stream'][1]['source_joined']=True
        self.assertEqual(validate_termination(e)['validation'],'PASS')
    def test_source_before_last_frame_then_duplicate_validation(self):
        e=fixture();e['counts']['completed']=3
        self.assertEqual(validate_termination(e)['validation'],'FAIL')
        e['counts']['completed']=4
        self.assertEqual(validate_termination(e),validate_termination(e))
        self.assertEqual(validate_termination(e)['validation'],'PASS')

if __name__=='__main__':unittest.main()
