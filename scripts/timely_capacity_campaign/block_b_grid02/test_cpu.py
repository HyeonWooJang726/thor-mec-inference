"""Pure CPU regressions; never calls the worker, network, or clock controls."""
import copy
import unittest
import sys
from pathlib import Path

import grid_config as c
import block_b_summary
from analyze import prediction
from validate import validate_rows


class GridTests(unittest.TestCase):
    def test_masks_and_order(self):
        rows=c.order()
        self.assertEqual(len(rows),31)
        self.assertEqual(rows[0]['run_id'],'BLOCKB02_WARMUP_L200_E40_S')
        self.assertEqual([[r['target_service_FPS'],r['admission_pattern'][0]] for r in rows[1:]],
            [[rate,token] for round_ in c.ROUNDS for rate,token in round_])
        self.assertEqual({(r['target_service_FPS'],r['admission_pattern'],r['repeat']) for r in rows[1:]},
            {(rate,pattern,rep) for rate in c.RATES for pattern in ('ALIGNED','STAGGERED') for rep in range(1,6)})
        for rate,peak in ((216,1),(208,2),(200,2)):
            for pattern in ('ALIGNED','STAGGERED'):
                mask=c.masks(rate,pattern)
                self.assertEqual(mask['local_count_per_stream_per_30'],[rate//8]*8)
                self.assertEqual(mask['edge_count_per_stream_per_30'],[(240-rate)//8]*8)
                self.assertTrue(all(a+b==1 for aa,bb in zip(mask['local_masks'],mask['edge_masks'])
                                    for a,b in zip(aa,bb)))
                self.assertTrue(all(a+b==8 for a,b in zip(mask['m_L'],mask['m_E'])))
                if pattern=='STAGGERED':self.assertEqual(mask['edge_peak'],peak)
                ids=sorted(c.edge_id(rate,pattern,sid,frame)
                           for frame in range(30) for sid in range(8)
                           if not c.local_bit(rate,pattern,sid,frame))
                self.assertEqual(ids,list(range(240-rate)))

    def test_decorate_and_fidelity(self):
        condition=c.condition(200,'S',0,1,True)
        start=100_000_000_000
        rows=[]
        for frame in range(30*condition['seconds']):
            due=start+frame*10**9//30
            for sid in range(8):
                row={'phase':'active','stream_id':sid,'frame_id':frame,
                     'logical_arrival_ns':due,'admission_timestamp_ns':due,
                     'admission_observed_ns':due+sid+1}
                c.decorate(row,start,condition)
                row['terminal_state']='COMPLETED'
                row['completion_timestamp_ns']=due+10_000_000
                row['expired_drop_ns']=''
                rows.append(row)
        self.assertEqual(validate_rows(rows,condition,start)['status'],'PASS')
        wrong=copy.deepcopy(rows)
        wrong[0]['placement']='EDGE' if wrong[0]['placement']=='LOCAL' else 'LOCAL'
        self.assertEqual(validate_rows(wrong,condition,start)['status'],'FAIL')
        wrong=copy.deepcopy(rows)
        first=wrong[0]
        later=next(r for r in wrong[1:8] if r['placement']==first['placement'])
        later['admission_observed_ns']=first['admission_observed_ns']-1
        self.assertEqual(validate_rows(wrong,condition,start)['status'],'FAIL')
        wrong=copy.deepcopy(rows)
        wrong[0]['terminal_state']=''
        self.assertEqual(validate_rows(wrong,condition,start)['status'],'FAIL')

    def test_predictions_nonbinding(self):
        self.assertEqual(prediction('L216S',225)['MATCH_status'],'MATCH')
        self.assertEqual(prediction('L216S',234)['MATCH_status'],'MATCH')
        self.assertEqual(prediction('L216S',224.99)['MATCH_status'],'MISMATCH')
        self.assertEqual(prediction('L200A',238)['MATCH_status'],'MATCH')
        self.assertEqual(prediction('L200A',238.01)['MATCH_status'],'MISMATCH')
        self.assertEqual(prediction('L208S',235)['MATCH_status'],'MATCH')
        self.assertEqual(prediction('L208S',234.99)['MATCH_status'],'MISMATCH')
        self.assertEqual(prediction('L216S',220)['verdict_effect'],'NONE')

    def test_runtime_and_hello_preservation(self):
        self.assertEqual(c.run_source(),(c.frozen.OUT/'effective_runtime.txt').read_text())
        from run_thor import Context, supervisor_source
        self.assertIn("edge_r=c['edge_r']",supervisor_source())
        self.assertEqual(Context().block,'B')
        bundle=c.ROOT/'results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/edge_bundle'
        sys.path.insert(0,str(bundle))
        from edge_server_grid02 import expected_hello
        for condition in c.order():
            self.assertEqual(Context().hello(condition,condition['run_id'],'PLAN'),
                             expected_hello(condition,'PLAN',
                                 Context().hello(condition,condition['run_id'],'PLAN')['cache_sha256']))
        self.assertNotIn('socket.create_connection',Path(c.HERE/'run_thor.py').read_text())

    def test_private_summary_split_and_warmup_binding(self):
        import json
        source=block_b_summary.parameterized_source()
        compile(source, '<block-b-summary-regression>', 'exec')
        self.assertIn('duration!=expected_seconds',source)
        self.assertIn('len(rows)==expected_seconds*240',source)
        self.assertNotIn('if duration!=60:',source)
        self.assertNotIn('len(rows)==target*60',source)
        plan=json.loads(c.PLAN.read_text())
        for condition in (plan['order'][0],plan['order'][1]):
            seconds=condition['seconds']
            start=10**12
            manifest=dict(condition,plan_sha256=c.sha(c.PLAN),
                execution_manifest_sha256=c.sha(c.PLAN),batch_size=1,
                pruning_enabled=True,placement_schedule=plan['placement'],
                active_start_ns=start,active_end_ns=start+seconds*10**9)
            original=dict(manifest)
            result=block_b_summary.summarize(manifest,[],[])
            self.assertEqual(manifest,original)
            self.assertEqual(result['target_service_FPS'],condition['target_service_FPS'])
            self.assertEqual(result['total_offered_FPS'],240)
            self.assertEqual(result['configured_admission_FPS_per_stream'],30)
            self.assertEqual(result['integrity_status'],'INVALID')
            self.assertIn('source/admission count',result['errors'])
            self.assertFalse(any('active duration mismatch' in e for e in result['errors']))
            manifest['active_end_ns']+=10**9
            bad=block_b_summary.summarize(manifest,[],[])
            self.assertTrue(any('active duration mismatch' in e for e in bad['errors']))

    def test_all_six_cells_use_block_b_postdrain_decorator(self):
        import json
        plan=json.loads(c.PLAN.read_text())
        start=10**12
        for rate in c.RATES:
            for token in ('A','S'):
                with self.subTest(rate=rate,pattern=token):
                    condition=next(row for row in plan['order'] if
                        row['target_service_FPS']==rate and
                        row['admission_pattern'][0]==token and row['seconds']==60)
                    manifest=dict(condition,plan_sha256=c.sha(c.PLAN),
                        execution_manifest_sha256=c.sha(c.PLAN),batch_size=1,
                        pruning_enabled=True,placement_schedule=plan['placement'],
                        active_start_ns=start,active_end_ns=start+60*10**9)
                    rows=[]
                    for frame in range(30):
                        due=start+frame*10**9//30
                        for sid in range(8):
                            row={'phase':'active','stream_id':sid,'frame_id':frame,
                                 'logical_arrival_ns':due,'admission_timestamp_ns':due,
                                 'source_timestamp_ns':frame*10**9//30}
                            c.decorate(row,start,condition)
                            rows.append(row)
                    summary=block_b_summary.summarize(manifest,rows,[])
                    self.assertEqual(summary['integrity_status'],'INVALID')
                    self.assertTrue(any('source/admission count' in e for e in summary['errors']))
                    self.assertFalse(any('Unplanned pattern/rate' in e or
                        'placement/deadline identity' in e for e in summary['errors']))


if __name__=='__main__':unittest.main()
