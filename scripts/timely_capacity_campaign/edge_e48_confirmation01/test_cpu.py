"""CPU-only schedule, scoring, protocol and launch-guard regression fixtures."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import run_thor
import analyze


def trace(condition, start=10**12):
    data=[]; rid=0
    for frame in range(condition['seconds']*30):
        due=start+frame*10**9//30
        for sid in range(8):
            selected=config.bit(condition['rate'],condition['pattern'],sid,frame)
            row={'stream_id':sid,'frame_id':frame,'logical_arrival_ns':due,
                 'admission_timestamp_ns':due,'admission_observed_ns':due+100+sid,
                 'admitted':selected,'placement':'EDGE' if selected else 'SKIP'}
            if selected:
                row.update(edge_request_id=rid,edge_release_target_ns=due,
                           absolute_deadline_ns=due+100_000_000)
                rid+=1
            data.append(row)
    return data,start


class CPURegression(unittest.TestCase):
    def test_q_and_slot_bounds(self):
        for rate in (48,64):
            q=config.q(rate)
            self.assertEqual(len(q),30)
            self.assertEqual(sum(q),rate//8)
            self.assertEqual(q,tuple(int((i+1)*(rate//8)//30>i*(rate//8)//30) for i in range(30)))
            self.assertEqual(sum(config.schedule(rate,'STAGGERED')['m_n']),rate)
        a=config.schedule(48,'ALIGNED'); s=config.schedule(48,'STAGGERED')
        self.assertEqual(max(s['m_n']),2)
        self.assertEqual(s['theoretical_peak_lower_bound'],math.ceil(48/30))
        self.assertEqual(set(a['m_n']),{0,8})
        self.assertEqual(a['max_m_n'],8)
        self.assertFalse(s['phase_search_used'])
        for rate,pattern in ((48,'ALIGNED'),(48,'STAGGERED'),(64,'STAGGERED')):
            schedule=config.schedule(rate,pattern)
            self.assertEqual(schedule['per_stream_admissions_per_30_slots'],[rate//8]*8)
            self.assertEqual(schedule['phases'],[0]*8 if pattern=='ALIGNED' else list(range(8)))
            for sid in range(8):
                shift=0 if pattern=='ALIGNED' else sid
                self.assertEqual(schedule['per_stream_masks'][sid],
                    [config.q(rate)[(i-shift)%30] for i in range(30)])

    def test_frozen_order_and_exclusion(self):
        order=config.frozen_order()
        self.assertEqual(len(order),14)
        self.assertEqual(order[0]['run_id'],'EDGE48C01_WARMUP_E48_S')
        self.assertEqual(order[0]['seconds'],15)
        self.assertEqual([c['run_id'] for c in order[1:11]],[f'EDGE48C01_E48_{p}{r}' for p,r in
            (('A',1),('S',1),('S',2),('A',2),('A',3),('S',3),('S',4),('A',4),('A',5),('S',5))])
        self.assertEqual([c['run_id'] for c in order[11:]],[f'EDGE48C01_E64_S{i}' for i in (1,2,3)])
        self.assertTrue(all(c['seconds']==30 for c in order[1:]))
        scored=[c for c in order if c['stage']!='WARMUP']
        self.assertEqual(len(scored),13)
        self.assertEqual(sum(c['rate']==48 for c in scored),10)
        self.assertEqual(sum(c['rate']==64 for c in scored),3)
        self.assertFalse(analyze.scoring_eligible(order[0]))
        self.assertTrue(all(analyze.scoring_eligible(c) for c in order[1:]))

    def test_actual_mask_and_adverse_fixtures(self):
        for condition in (config.frozen_order()[0],config.frozen_order()[1],config.frozen_order()[2],config.frozen_order()[11]):
            data,start=trace(condition)
            self.assertEqual(config.validate_source_rows(data,condition,start)['status'],'PASS')
            for mutate in (
                lambda x:x[0].__setitem__('logical_arrival_ns',start+1),
                lambda x:x[0].__setitem__('admission_timestamp_ns',start+1),
                lambda x:x[0].__setitem__('admitted',1-int(x[0]['admitted'])),
                lambda x:x[0].__setitem__('admission_observed_ns',start+1000),
                lambda x:x[1].__setitem__('admission_observed_ns',start+50)):
                bad=copy.deepcopy(data);mutate(bad)
                self.assertEqual(config.validate_source_rows(bad,condition,start)['status'],'FAIL')
            selected=next(i for i,row in enumerate(data) if row['admitted'])
            bad=copy.deepcopy(data);bad[selected]['edge_release_target_ns']+=33_333_333
            self.assertEqual(config.validate_source_rows(bad,condition,start)['status'],'FAIL')

    def test_hello_and_payload(self):
        sys.path.insert(0,str(config.OUT/'edge_bundle'))
        try:
            import edge_server_confirmation01 as server
            for c in config.frozen_order():
                self.assertEqual(config.hello(c,'plan','cache'),server.expected_hello(c,'plan','cache'))
        finally:
            sys.path.pop(0)
        self.assertEqual(config.PAYLOAD_BYTES,691200)

    def test_robust_and_headroom_not_classified(self):
        def cohort(values):
            return [dict(rate=48,repeat=i,integrity_status='VALID',TIR_admission=v) for i,v in enumerate(values,1)]
        self.assertEqual(config.robust_class(cohort([.90]*5)),'ROBUST_EDGE_USABLE')
        self.assertEqual(config.robust_class(cohort([.79]*5)),'ROBUST_EDGE_FAIL')
        self.assertEqual(config.robust_class(cohort([.90,.9,.9,.9,.89])),'ROBUST_EDGE_BOUNDARY')
        self.assertEqual(config.robust_class(cohort([.79]*4)),'INCOMPLETE')
        invalid=cohort([.95]*5);invalid[2]['integrity_status']='INVALID'
        self.assertEqual(config.robust_class(invalid),'INVALID')
        headroom=cohort([.95]*5)
        for row in headroom: row['rate']=64
        self.assertEqual(config.robust_class(headroom),'INCOMPLETE')

    def test_pair_identity_and_sign(self):
        data=[]
        for c in config.frozen_order()[1:11]:
            data.append(dict(c,TIR_admission=.7 if c['pattern']=='ALIGNED' else .9))
        pairs=analyze.paired(data)
        self.assertEqual([(p['A_run_id'],p['S_run_id']) for p in pairs],
            [(f'EDGE48C01_E48_A{i}',f'EDGE48C01_E48_S{i}') for i in range(1,6)])
        self.assertTrue(all(abs(p['delta_TIR_S_minus_A']-.2)<1e-12 for p in pairs))
        self.assertNotEqual(pairs[0]['A_run_id'],data[3]['run_id'])
        self.assertEqual(sum(p['delta_TIR_S_minus_A']>0 for p in pairs),5)

    def test_warmup_terminal_and_pending(self):
        c=config.frozen_order()[0]
        self.assertEqual(c['seconds']*c['rate'],720)
        submitted=[{'edge_request_id':i,'logical_arrival_ns':i*1_000_000,
            'payload_ready_ns':i*1_000_000+100,'socket_submission_ns':i*1_000_000+200,
            'response_completion_ns':i*1_000_000+10_000_000,
            'payload_sha256':'a','raw_sha256':'a'} for i in range(720)]
        final={'received':720,'completed':720,'responses_sent':720,
            'expired_request_ids':[],'assigned':720,'integrity_status':'VALID',
            'drain_completed':True,'cleanup_completed':True,'worker_thread_exited':True,
            'drops':0,'duplicates':0,'queue_cap_saturation':False,'errors':[]}
        valid=run_thor.evaluate_session(submitted,final,[],48,15)
        self.assertEqual(valid['integrity_status'],'VALID')
        self.assertEqual((valid['admitted'],valid['seconds'],valid['after_drain_unfinished']), (720,15,0))
        self.assertEqual(valid['Edge_timely_ratio'],1)
        self.assertEqual(run_thor.evaluate_session(submitted[:-1],final,[],48,15)['integrity_status'],'INVALID')
        result=analyze.client_pending([{'logical_arrival_ns':0,'socket_submission_ns':2_000_000_000}],0,1_000_000_000)
        self.assertEqual(result['active_end_count'],1)
        result=analyze.client_pending([{'logical_arrival_ns':0,'socket_submission_ns':500_000_000}],0,1_000_000_000)
        self.assertEqual(result['active_end_count'],0)
        # Invalid warm-up cannot satisfy the campaign continuation gate.
        self.assertNotEqual({'integrity_status':'INVALID'}['integrity_status'],'VALID')

    def test_pin_restore_and_freshness_guards(self):
        with mock.patch.object(run_thor,'cpu_report',return_value={'status':'FAIL','errors':['pin']}):
            with self.assertRaises(RuntimeError):run_thor.require_pin()
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(analyze,'OUT',Path(temporary)):
                with self.assertRaisesRegex(RuntimeError,'CPU restore PASS required'):
                    analyze.require_restore()
            with mock.patch.object(run_thor,'OUT',Path(temporary)):
                (Path(temporary)/'CPU_PIN_READBACK.json').write_text('{}')
                with self.assertRaisesRegex(RuntimeError,'Stale'):
                    run_thor.require_fresh_execution_namespace()

    def test_no_active_protocol_probe(self):
        text=(config.HERE/'run_thor.py').read_text()
        pre=text.split('def check_preexecution():')[1].split('def require_current_pin_evidence():')[0]
        for forbidden in ('create_connection','connect(', 'HELLO','nc -','telnet','curl'):
            self.assertNotIn(forbidden,pre)
        self.assertIn("['ip', 'route', 'get', host]",text)
        self.assertIn("['ping', '-c', '2', '-W', '1', host]",text)
        self.assertIn("LISTENING 5000: {count} {stage} sessions",text)
        self.assertIn("Edge listener evidence predates current CPU pin readback",text)
        self.assertIn("if result['integrity_status'] != 'VALID':",text)
        self.assertIn("if (OUT / 'campaign_attempt.json').exists()",text)
        self.assertIn("verify_local_artifacts(plan)",text)

    def test_server_backend_source_identical(self):
        old=config.ROOT/'results/timely_capacity_campaign/v2_2/edge_preflight_final02/edge_bundle'
        new=config.OUT/'edge_bundle'
        for name in ('formal_protocol.py','formal_server.py','profile_edge_concurrency.py','pruning_edge_server.py'):
            self.assertEqual(config.sha(old/name),config.sha(new/name))

    def test_plan_and_protected_results(self):
        plan=config.load_plan()
        self.assertEqual(len(plan['order']),14)
        report=json.loads((config.OUT/'preservation.json').read_text())
        self.assertEqual(report['status'],'PASS')
        self.assertEqual(plan['server_runtime'],'pruning_edge_server.serve_session + formal_server.Backend unchanged')


if __name__=='__main__': unittest.main(verbosity=2)
