"""Synthetic CPU fixtures + preserved V2.2 OFF raw replay; no workloads."""
import hashlib
import inspect
import json
from pathlib import Path
import queue
import unittest
from accounting import accounting,classify,continuous_ols,rate_summary
from config import ROOT,OUT,frozen,run_source,order

NS=10**9


class ConservationTests(unittest.TestCase):
    def test_linear_growth(self):
        # SYNTHETIC: 200 admissions/s, 180 completions/s; drain all remainder.
        A=[i*NS//200 for i in range(12000)]
        C=[(i+1)*NS//180 for i in range(12000)]
        r=accounting(A,C,0,60*NS)
        self.assertAlmostEqual(r['rate_deficit_last30'],20,places=7)
        self.assertLess(abs(r['queue_conservation_error']),.001)
        self.assertEqual(r['endpoint_conservation_error_frames'],0)
        self.assertEqual(r['Delta_FPS'],r['B_active_end_div_60'])
        self.assertEqual(classify(True,r['g_B_H'],r['Delta_FPS']),'UNSUSTAINABLE')

    def test_early_buildup_plateau(self):
        # First 100 work items never finish until drain. Afterwards every arrival
        # is paired with a same-time completion: exact B=100 plateau in last30.
        A=[i*NS//200 for i in range(12000)]
        C=A[100:]+[60*NS+i*NS//200 for i in range(100)]
        r=accounting(A,C,0,60*NS)
        self.assertGreater(r['Delta_FPS'],0)
        self.assertAlmostEqual(r['g_B_H'],0,places=10)
        self.assertEqual(r['rate_deficit_last30'],0)
        self.assertAlmostEqual(r['queue_conservation_error'],0,places=10)
        self.assertFalse(r['hidden_drop_warning'])
        self.assertEqual(classify(True,r['g_B_H'],r['Delta_FPS']),'BOUNDARY')
        self.assertEqual(r['B_active_end'],100)

    def test_exact_boundaries_and_drain(self):
        A=[0,30*NS-1,30*NS,60*NS-1]
        C=[30*NS-1,30*NS,60*NS,61*NS]
        r=accounting(A,C,0,60*NS)
        self.assertEqual(r['admitted_count_last30'],2)
        self.assertEqual(r['completed_count_last30'],1)
        self.assertEqual(r['completed_count_active'],2)
        self.assertEqual(r['B_active_start'],0);self.assertEqual(r['B_active_end'],2)
        self.assertEqual(r['after_drain_backlog'],0)
        self.assertEqual(r['endpoint_conservation_error_frames'],0)

    def test_nonlinear_ols_is_not_endpoint_rate(self):
        # Late transient step has a different OLS slope despite exact conservation.
        r=accounting([55*NS]*100,[61*NS]*100,0,60*NS)
        self.assertGreater(abs(r['queue_conservation_error']),.1)
        self.assertEqual(r['endpoint_conservation_error_frames'],0)
        self.assertFalse(r['hidden_drop_warning'])

    def test_nonzero_initial_backlog(self):
        r=accounting([-NS,0],[61*NS,62*NS],0,60*NS)
        self.assertEqual(r['B_active_start'],1)
        self.assertEqual(r['delta_level_identity_error'],0)
        self.assertNotEqual(r['Delta_FPS'],r['B_active_end_div_60'])

    def test_time_translation(self):
        A=[0,30*NS,40*NS];C=[NS,45*NS,62*NS]
        a=accounting(A,C,0,60*NS);offset=27800000000000
        b=accounting([x+offset for x in A],[x+offset for x in C],offset,offset+60*NS)
        self.assertAlmostEqual(a['g_B_H'],b['g_B_H'],places=12)

    def test_rules_unchanged(self):
        for g,d,expected in ((.1,.5,'STABLE'),(.10001,.5,'BOUNDARY'),(.5,.6,'BOUNDARY'),(.50001,.50001,'UNSUSTAINABLE'),(-1,2,'BOUNDARY'),(1,.1,'BOUNDARY')):
            self.assertEqual(classify(True,g,d),expected)
            self.assertEqual(classify(False,g,d),'INVALID')

    def test_incomplete_window(self):
        with self.assertRaises(ValueError):accounting([],[],0,59*NS)

    def test_continuous_integral(self):
        self.assertAlmostEqual(continuous_ols([(0,30*NS,2),(30*NS,60*NS,2)],0,60*NS),0)
        self.assertAlmostEqual(continuous_ols([(0,30*NS,0),(30*NS,60*NS,10)],0,60*NS),.25)

    def test_invalid_not_capacity(self):
        rows=[dict(target_offered_FPS=200,repeat=i,classification='INVALID') for i in (1,2)]
        rates,b=rate_summary(rows)
        self.assertEqual(rates[0]['valid_repeat_count'],0)
        self.assertIsNone(b['lowest_2of2_UNSUSTAINABLE'])


class FrozenRuntimeTests(unittest.TestCase):
    def test_source_identical(self):
        self.assertEqual(run_source(),(frozen.OUT/'effective_runtime.txt').read_text())
        frozen.runtime_record()

    def test_off_accounting_fifo_and_lifecycle(self):
        from v22_accounting import make_accounting
        q=queue.Queue();a=make_accounting(False);jobs=[];tensor=object()
        for i in range(2500):
            j=dict(stream_id=i%8,frame_id=i,absolute_deadline_ns=1,tensor=tensor)
            a.enqueue(q,j,lambda:2);jobs.append(j)
        self.assertEqual(q.maxsize,0);self.assertEqual(q.qsize(),2500)
        for j in jobs:
            self.assertIs(q.get_nowait(),j);self.assertIs(j['tensor'],tensor)
            self.assertTrue(a.begin(j,lambda:3));self.assertEqual(j['s_ns'],3)
        self.assertEqual((a.n_enqueue,a.n_start,a.n_expired),(2500,2500,0))
        self.assertEqual(a.events,[])

    def test_rate_admission_and_order(self):
        import campaign_config as cfg
        rows=order();self.assertEqual(len(rows),12)
        self.assertEqual([c['target_service_FPS'] for c in rows],[200,208,216,224,232,240,240,232,224,216,208,200])
        for c in rows:
            counts=[0]*8
            for f in range(1800):
                for k in range(8):
                    r=dict(stream_id=k,frame_id=f,logical_arrival_ns=f*NS//30)
                    cfg.decorate(r,0,c);counts[k]+=r['admitted']
                    self.assertNotEqual(r['placement'],'EDGE')
                    if c['target_service_FPS']==200:
                        old=dict(stream_id=k,frame_id=f,logical_arrival_ns=f*NS//30)
                        cfg.decorate(old,0,frozen.order()[1]);self.assertEqual(r,old)
            self.assertEqual(counts,[60*c['local_r']]*8)
            self.assertFalse(c['pruning_enabled'])

    def test_preserved_off_replay(self):
        from analyze_scan import analyze_run
        c=frozen.order()[1];d=frozen.OUT/c['run_id'];row,_=analyze_run(d,c)
        self.assertEqual(row['raw_scan_integrity_status'],'VALID',row['validity_errors'])
        s=json.loads((d/'summary.json').read_text())
        self.assertAlmostEqual(row['g_B_H'],s['backlogs']['H']['g_B_E'],places=9)
        self.assertEqual(row['B_active_end'],4)
        self.assertAlmostEqual(row['Delta_FPS'],4/60)
        self.assertEqual(row['after_drain_backlog'],0)
        self.assertGreater(row['cohort_completed_FPS'],row['active_completed_FPS'])
        self.assertFalse(row['hidden_drop_warning'])

    def test_frozen_binding(self):
        from run_scan import Context
        new,_=Context().bindings()
        import run_validation
        old,_=run_validation.Context().bindings()
        # Same code object bytecode and constants: namespace/plan paths only differ.
        self.assertEqual(new.__code__.co_code,old.__code__.co_code)
        self.assertEqual(new.__code__.co_consts,old.__code__.co_consts)


if __name__=='__main__':unittest.main(verbosity=2)
