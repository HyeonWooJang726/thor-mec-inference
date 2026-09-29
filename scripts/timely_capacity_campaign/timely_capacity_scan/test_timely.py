"""CPU-only parameter/analysis/regression fixtures; no GPU or control actions."""
import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from timely_config import order,decorate,canonical,frozen,run_source,GRIDS,OUT
from analyze_timely_scan import cohort_metrics,budget_metrics,run_class,rate_class,summaries,require_restore,validate
import analyze_b1 as b1
import timely_summary


class TimelyTests(unittest.TestCase):
    def test_order(self):
        cc=order();self.assertEqual(len(cc),20)
        self.assertEqual([(c['deadline_ms'],c['target_service_FPS']) for c in cc],[(100,r) for r in [200,208,212,216,224,240,240,224,216,212,208,200]]+[(67,r) for r in [192,200,208,216,216,208,200,192]])
        self.assertTrue(all(c['pruning_enabled'] and not c['edge_r'] for c in cc))

    def test_admission_exact(self):
        for c in order():
            counts=[0]*8;persecond={};slots={}
            for f in range(1800):
                for k in range(8):
                    row=dict(stream_id=k,frame_id=f,logical_arrival_ns=f*10**9//30)
                    old=dict(row);decorate(row,0,c);counts[k]+=row['admitted'];slots.setdefault(f,[]).append(row['admitted'])
                    if k==0:persecond[f//30]=persecond.get(f//30,0)+row['admitted']
                    if c['target_service_FPS']%8==0:
                        canonical.decorate(old,0,c)
                        if old['admitted']:old['absolute_deadline_ns']=old['logical_arrival_ns']+c['deadline_ms']*10**6
                        self.assertEqual(old,row)
            self.assertEqual(counts,[c['target_service_FPS']*60//8]*8)
            self.assertTrue(all(len(set(v))==1 for v in slots.values()))
            if c['target_service_FPS']==212:self.assertEqual(list(persecond.values()),[26,27]*30)

    def test_primary_denominator_and_drain(self):
        rows=[]
        for i in range(100):
            rows.append(dict(logical_arrival_ns=59_950_000_000,inference_start_timestamp_ns=59_980_000_000 if i<80 else '',
                completion_timestamp_ns=(60_000_000_000 if i<60 else 60_060_000_000) if i<80 else '',
                terminal_state='COMPLETED' if i<80 else 'EXPIRED_DROP'))
        r=cohort_metrics(rows,100,0,60*10**9)
        self.assertEqual(r['TIR_admission'],.6);self.assertEqual(r['timely_count'],60)
        self.assertEqual(r['late_completed_count'],20);self.assertEqual(r['expired_count'],20)
        self.assertEqual(r['active_completed_FPS'],0);self.assertTrue(r['terminal_identity_PASS'])

    def test_budget_and_inclusive_deadline(self):
        rows=[dict(logical_arrival_ns=0,inference_start_timestamp_ns=60_000_000,completion_timestamp_ns=67_000_000,terminal_state='COMPLETED'),dict(logical_arrival_ns=0,inference_start_timestamp_ns=65_000_000,completion_timestamp_ns=68_000_000,terminal_state='COMPLETED')]
        r=cohort_metrics(rows,67,0,60*10**9);self.assertEqual(r['timely_count'],1)
        b=budget_metrics(rows,67);self.assertEqual(b['budget_p50'],4.5)
        self.assertEqual(b['budget_less_than_measured_service_fraction'],.5)
        self.assertEqual(b['budget_le_zero_fraction'],0)

    def test_expiry_rule_unchanged(self):
        import queue
        from v22_accounting import make_accounting
        for D in (67,100):
            for delta,execute in ((-1,True),(0,False),(1,False)):
                a=make_accounting(True);q=queue.Queue();job=dict(stream_id=0,frame_id=0,absolute_deadline_ns=D*10**6)
                a.enqueue(q,job,lambda:1);self.assertIs(q.get(),job)
                self.assertEqual(a.begin(job,lambda:D*10**6+delta),execute)

    def test_classification(self):
        self.assertEqual(run_class(True,.99),'TIMELY_FEASIBLE')
        self.assertEqual(run_class(True,.95),'TIMELY_BOUNDARY')
        self.assertEqual(run_class(True,.949999),'TIMELY_CLEAR_FAIL')
        self.assertEqual(run_class(False,.1),'INVALID')
        def pair(a,b):return [dict(repeat=i,TIR_admission=v,classification=run_class(True,v)) for i,v in enumerate((a,b),1)]
        self.assertEqual(rate_class(pair(.99,1)),'TIMELY_FEASIBLE')
        self.assertEqual(rate_class(pair(.949,.1)),'TIMELY_CLEAR_FAIL')
        self.assertEqual(rate_class(pair(.99,.94)),'TIMELY_BOUNDARY')
        invalid=pair(.1,.2);invalid[0]['classification']='INVALID';self.assertEqual(rate_class(invalid),'INCONCLUSIVE_INVALID')

    def test_restore_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn=types.FunctionType(require_restore.__code__,dict(require_restore.__globals__,OUT=Path(tmp)))
            with self.assertRaisesRegex(RuntimeError,'restore PASS'):fn()
            (Path(tmp)/'CPU_RESTORE_READBACK.json').write_text('{"status":"FAIL"}')
            with self.assertRaises(RuntimeError):fn()

    def test_frozen_worker_bytecode(self):
        import run_validation
        from run_timely_scan import Context,binding_import
        self.assertEqual(run_source(),(frozen.OUT/'effective_runtime.txt').read_text())
        old,oldfinal=run_validation.Context().bindings();new,newfinal=Context().bindings()
        for x,y in ((old,new),(oldfinal,newfinal)):
            self.assertEqual(x.__code__.co_code,y.__code__.co_code);self.assertEqual(x.__code__.co_consts,y.__code__.co_consts)
        self.assertIs(new.__globals__['decorate'],decorate)
        self.assertIs(binding_import('b1_summary'),timely_summary)
        self.assertIs(binding_import('json'),json)

    def test_preserved_D100_ON_replay(self):
        c=dict(order()[0],run_id='V22_LOCAL200_ON_R1_P01');d=frozen.OUT/c['run_id']
        m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
        frames=b1.read(d/'per_frame.csv.gz');ph=b1.read(d/'per_frame_phase_timestamps.csv');power=b1.read(d/'power_trace.csv.gz');wi=json.loads((d/'phase_instrumentation_manifest.json').read_text())
        v=validate(c,m,s,frames,ph,wi);self.assertEqual(v['status'],'PASS',v['errors'])
        new=timely_summary.summarize(m,frames,power)
        self.assertEqual(new['integrity_status'],'VALID',new['errors'])
        for key in ('admitted_frames','timely_completed_frames','late_completed_frames','expired_dropped_frames','TIR_admission','raw_completed_FPS','g_B_H'):
            self.assertEqual(new[key],s[key],key)

    def test_actual_analyzer_replay_and_temperature(self):
        from analyze_timely_scan import analyze_run
        c=dict(order()[0],run_id='V22_LOCAL200_ON_R1_P01')
        r,trace=analyze_run(frozen.OUT/c['run_id'],c)
        self.assertEqual(r['integrity_status'],'VALID',r['validity_errors'])
        self.assertEqual(r['admitted_count'],12000)
        self.assertEqual(r['timely_count']+r['late_completed_count']+r['expired_count'],12000)
        self.assertEqual(r['U_after_drain'],0)
        self.assertEqual(len(trace),61)
        self.assertIsNotNone(r['temperature_mean'])
        self.assertEqual(r['TIR_admission'],r['timely_count']/12000)

    def test_D67_212_postrun_summary_synthetic(self):
        # Synthetic frame timestamps; saved power only supplies schema fixture.
        # This is NOT a measured D67/212 performance run.
        c=next(c for c in order() if c['target_service_FPS']==212)
        c=dict(c,deadline_ms=67)  # core decorator must refuse off-grid first.
        with self.assertRaises(ValueError):decorate(dict(stream_id=0,frame_id=0,logical_arrival_ns=0),0,c)
        for D,rate in ((67,208),(100,212)):
            c=next(c for c in order() if c['deadline_ms']==D and c['target_service_FPS']==rate)
            d=frozen.OUT/'V22_LOCAL200_ON_R1_P01';m=json.loads((d/'manifest.json').read_text());m.update(c)
            rows=b1.read(d/'per_frame.csv.gz');power=b1.read(d/'power_trace.csv.gz');n=0
            for r in rows:
                if r['phase']!='active':continue
                r['logical_arrival_ns']=int(r['logical_arrival_ns']);decorate(r,m['active_start_ns'],c);a=r['logical_arrival_ns']
                for key in ('ready_timestamp_ns','enqueue_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns','expired_drop_ns','expiry_check_ns','expired_stage','terminal_state','s_ns','c_ns'):r[key]=''
                r.update(b_ns=a+100,source_pulled_ns=a+200,resize_start_ns=a+300,resize_end_ns=a+400,payload_ready_ns=a+500)
                if r['admitted']:
                    n+=1;start=a+1000+(int(r['stream_id'])//2)*1_000_000
                    r.update(ready_timestamp_ns=a+600,enqueue_timestamp_ns=a+600,expiry_check_ns=start,inference_start_timestamp_ns=start,completion_timestamp_ns=start+1_000_000,terminal_state='COMPLETED')
            m['ready_queue_accounting']=dict(enqueue=n,start=n,expired=0)
            s=timely_summary.summarize(m,rows,power)
            self.assertEqual(s['integrity_status'],'VALID',s['errors'])
            self.assertEqual(s['admitted_frames'],rate*60);self.assertEqual(s['TIR_admission'],1)


if __name__=='__main__':unittest.main(verbosity=2)
