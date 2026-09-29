"""CPU-only Confirmation02 regression; never invokes a workload or network check."""
import copy
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

import block_b_summary
import confirmation_rules as rules
import grid_config as c
from validate import validate_rows,edge_terminal_valid,cpu_run_valid


class ConfirmationTests(unittest.TestCase):
    def test_candidate_from_raw(self):
        selected=json.loads((c.OUT/'GRID02_SELECTION_RECOMPUTE.json').read_text())
        self.assertEqual(selected['status'],'PASS')
        self.assertEqual(selected['eta'],.99)
        self.assertEqual(selected['candidate'],'L200S')
        self.assertEqual(selected['exploratory_feasible_set'],['L200S'])
        self.assertEqual(selected['raw_frame_rows_checked'],432000)
        self.assertFalse(selected['mu_backlog_lower_used'])

    def test_latin_order_and_counts(self):
        rows=c.order()
        self.assertEqual(len(rows),26)
        self.assertEqual(rows[0]['run_id'],'BCONF02_WARMUP_L200_S')
        self.assertEqual(rows[0]['seconds'],15)
        self.assertEqual([r['run_id'] for r in rows[1:6]],
            ['BCONF02_L216_A1','BCONF02_L200_A1','BCONF02_L200_S1',
             'BCONF02_L208_S1','BCONF02_L192_S1'])
        self.assertEqual(Counter((r['target_service_FPS'],r['admission_pattern']) for r in rows[1:]),
            Counter({(rate,'ALIGNED' if token=='A' else 'STAGGERED'):5 for rate,token in c.CONDITIONS}))
        for rate,token in c.CONDITIONS:
            positions=[]
            for round_ in c.ROUNDS:
                positions.append(round_.index((rate,token))+1)
            self.assertEqual(sorted(positions),[1,2,3,4,5])
        self.assertTrue(all(r['seconds']==60 for r in rows[1:]))

    def test_masks_prior_equality_and_new_p24(self):
        old=json.loads((c.OUT.parent/'block_b_grid02/BLOCK_B_MASK_MANIFEST.json').read_text())
        for label in ('L216A','L200A','L200S','L208S'):
            rate=int(label[1:4]);pattern='ALIGNED' if label.endswith('A') else 'STAGGERED'
            self.assertEqual(json.loads(json.dumps(c.masks(rate,pattern))),
                             {k:v for k,v in old[label].items() if not k.endswith('_sha256')})
        for rate,token in c.CONDITIONS:
            mask=c.masks(rate,'ALIGNED' if token=='A' else 'STAGGERED')
            self.assertEqual(mask['local_count_per_stream_per_30'],[rate//8]*8)
            self.assertEqual(mask['edge_count_per_stream_per_30'],[(240-rate)//8]*8)
            self.assertTrue(all(a+b==1 for aa,bb in zip(mask['local_masks'],mask['edge_masks'])
                                for a,b in zip(aa,bb)))
            self.assertEqual(sum(mask['m_L']),rate)
            self.assertEqual(sum(mask['m_E']),240-rate)
            ids=sorted(c.edge_id(rate,'ALIGNED' if token=='A' else 'STAGGERED',sid,frame)
                       for frame in range(30) for sid in range(8)
                       if not c.local_bit(rate,'ALIGNED' if token=='A' else 'STAGGERED',sid,frame))
            self.assertEqual(ids,list(range(240-rate)))
        self.assertEqual(c.p(192).count(1),24)
        self.assertEqual(c.masks(192,'STAGGERED')['phase_vector'],list(range(8)))

    def test_rules_exact_and_nonbinding_mechanism(self):
        self.assertEqual(rules.ETA,.99)
        records=[]
        for round_ in range(1,6):
            for rate,token in c.CONDITIONS:
                value={'L216A':210,'L200A':225,'L200S':239,'L208S':230,'L192S':238}[f'L{rate}{token}']
                worst={'L216A':.8,'L200A':.85,'L200S':.995,'L208S':.98,'L192S':.996}[f'L{rate}{token}']
                records.append({'round':round_,'rate_local':rate,
                    'pattern':'ALIGNED' if token=='A' else 'STAGGERED',
                    'total_timely_FPS':value,'worst_stream_TIR':worst})
        verdict,rounds,tables=rules.decide(records)
        self.assertEqual(verdict['C1'],'L200S_FEASIBILITY_CONFIRMED')
        self.assertEqual(verdict['C2'],'L200_TEMPORAL_EFFECT_CONFIRMED')
        self.assertEqual(verdict['C3'],'L200S_VS_L216A_CONFIRMED')
        self.assertEqual(verdict['C4'],'MAX_LOCAL_SELECTION_CONSISTENT')
        self.assertEqual(verdict['C5'],'BOTH_L200S_AND_L192S_FEASIBLE_DESCRIPTIVE')
        self.assertTrue(verdict['mu_backlog_lower_not_used'])
        self.assertEqual(len(rounds),5)
        changed=copy.deepcopy(records)
        next(r for r in changed if r['round']==3 and r['rate_local']==208)['worst_stream_TIR']=.99
        self.assertEqual(rules.decide(changed)[0]['C4'],'MAX_LOCAL_SELECTION_CONSISTENT')
        for r in changed:
            if r['rate_local']==208:r['worst_stream_TIR']=.99
        self.assertEqual(rules.decide(changed)[0]['C4'],'MAX_LOCAL_SELECTION_NOT_CONFIRMED')
        changed=copy.deepcopy(records)
        next(r for r in changed if r['round']==1 and r['rate_local']==200 and r['pattern']=='STAGGERED')['worst_stream_TIR']=.989999
        self.assertEqual(rules.decide(changed)[0]['C1'],'L200S_FEASIBILITY_NOT_CONFIRMED')
        changed=copy.deepcopy(records)
        next(r for r in changed if r['round']==1 and r['rate_local']==200 and r['pattern']=='STAGGERED')['total_timely_FPS']=225
        self.assertEqual(rules.decide(changed)[0]['C2'],'L200_TEMPORAL_EFFECT_NOT_CONFIRMED')
        changed=copy.deepcopy(records)
        next(r for r in changed if r['round']==1 and r['rate_local']==216)['total_timely_FPS']=239
        self.assertEqual(rules.decide(changed)[0]['C3'],'L200S_VS_L216A_NOT_CONFIRMED')

    def test_summary_all_five_and_instrumentation_preservation(self):
        source=block_b_summary.parameterized_source()
        compile(source,'<confirmation-summary-regression>','exec')
        plan=json.loads(c.PLAN.read_text())
        for condition in plan['order']:
            if condition['repeat']==0 or condition['repeat']!=1:continue
            with self.subTest(run=condition['run_id']):
                start=10**12
                manifest=dict(condition,plan_sha256=c.sha(c.PLAN),
                    execution_manifest_sha256=c.sha(c.PLAN),batch_size=1,
                    pruning_enabled=True,placement_schedule=plan['placement'],
                    active_start_ns=start,active_end_ns=start+60*10**9)
                original=dict(manifest)
                frame={'phase':'active','stream_id':0,'frame_id':0,
                    'logical_arrival_ns':start,'admission_timestamp_ns':start,
                    'source_timestamp_ns':0}
                c.decorate(frame,start,condition)
                summary=block_b_summary.summarize(manifest,[frame],[])
                self.assertEqual(manifest,original)
                self.assertEqual(summary['integrity_status'],'INVALID')
                self.assertFalse(any('Unplanned pattern/rate' in e for e in summary['errors']))
        self.assertEqual(c.run_source(),(c.frozen.OUT/'effective_runtime.txt').read_text())
        prior=json.loads((c.OUT.parent/'block_b_grid02/plan.json').read_text())
        self.assertEqual(json.loads(c.PLAN.read_text())['frozen_worker_sha256'],prior['frozen_worker_sha256'])

    def test_launcher_safety_without_execution(self):
        from run_thor import Context, supervisor_source
        text=Path(c.HERE/'run_thor.py').read_text()
        self.assertNotIn('socket.create_connection',text)
        self.assertIn('LISTENING 5000: 26 CONFIRMATION sessions',text)
        self.assertIn('EDGE_LISTENER_READY_CONFIRMATION',text)
        self.assertIn('edge_r=c[\'edge_r\']',supervisor_source())
        self.assertEqual(Context().block,'B')
        state=json.loads((c.OUT/'CPU_STATE_BEFORE.json').read_text())
        self.assertEqual(len(state['policies']),7)
        for policy in state['policies']:
            self.assertEqual(policy['fields']['scaling_governor'],'schedutil')
            self.assertEqual(policy['fields']['scaling_min_freq'],'972000')
            self.assertEqual(policy['fields']['scaling_max_freq'],'2601000')

    def test_edge_terminal_invalid_stops_campaign(self):
        sample=json.loads((c.OUT.parent/'block_b_grid02/BLOCKB02_L216_A1/edge_final.json').read_text())
        self.assertTrue(edge_terminal_valid(sample,1440))
        for patch in ({'integrity_status':'INVALID'},{'errors':['socket']},
                      {'drain_completed':False},{'duplicates':1},{'drops':1},
                      {'received':sample['received']-1},{'client_expired_before_submission':0}):
            altered=dict(sample,**patch)
            self.assertFalse(edge_terminal_valid(altered,1440),patch)

    def test_cpu_before_after_are_run_validity_gates(self):
        from tempfile import TemporaryDirectory
        sample=c.OUT.parent/'block_b_grid02/BLOCKB02_L200_S1'
        self.assertTrue(cpu_run_valid(sample))
        with TemporaryDirectory() as temp:
            directory=Path(temp)
            for name in ('CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json'):
                (directory/name).write_bytes((sample/name).read_bytes())
            self.assertTrue(cpu_run_valid(directory))
            after=directory/'CPU_AFTER_RUN.json'
            record=json.loads(after.read_text())
            record['status']='FAIL'
            after.write_text(json.dumps(record))
            self.assertFalse(cpu_run_valid(directory))
            after.unlink()
            self.assertFalse(cpu_run_valid(directory))


if __name__=='__main__':unittest.main()
