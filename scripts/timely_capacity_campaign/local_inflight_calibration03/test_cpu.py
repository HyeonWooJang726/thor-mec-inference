"""CPU-only calibration regression; never starts inference or changes controls."""
import json
import unittest
from pathlib import Path

import config as c
from selection import decide, saturation_status
from analyze_scan import _old, _new, _source, _validate_dynamic_workers, active_concurrency_p95
from run_scan import supervisor_source, memory_snapshot, parent_finalizer_source, Context


def rows(values1, values2):
    return [dict(run_id=f'LINFLIGHT03_C{cc}_R{rep}', C_L=cc, repeat=rep,
                 active_completed_FPS=values[cc], raw_scan_integrity_status='VALID',
                 saturation_status='SATURATED_VALID',supply_saturation_evidence='PASS')
            for rep,values in ((1,values1),(2,values2)) for cc in (1,2,3,4)]


class CalibrationTests(unittest.TestCase):
    def test_order_and_only_c_changes(self):
        order=c.order()
        self.assertEqual([x['run_id'] for x in order],
            ['LINFLIGHT03_C1_R1','LINFLIGHT03_C2_R1','LINFLIGHT03_C3_R1',
             'LINFLIGHT03_C4_R1','LINFLIGHT03_C4_R2','LINFLIGHT03_C3_R2',
             'LINFLIGHT03_C2_R2','LINFLIGHT03_C1_R2'])
        self.assertEqual(sorted((x['C'],x['repeat']) for x in order),
            sorted((cc,rep) for cc in (1,2,3,4) for rep in (1,2)))
        ignored={'run_id','C','repeat','order_index','cell','original_cell','pass','pass_name'}
        baseline={k:v for k,v in order[0].items() if k not in ignored}
        self.assertTrue(all({k:v for k,v in x.items() if k not in ignored}==baseline for x in order))
        self.assertTrue(all(x['admission_r']==30 and x['admitted_FPS']==240 and
                            x['edge_r']==0 and x['pruning_enabled'] is False and
                            x['seconds']==60 and x['frequency_MHz']==1575 for x in order))
        self.assertEqual(c.frozen_run_source(),(c.frozen.OUT/'effective_runtime.txt').read_text())

    def test_runtime_dynamic_workers_without_hot_path_change(self):
        source=c.run_source()
        self.assertIn('runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))',source)
        self.assertIn('from summary_adapter import summarize',source)
        self.assertIn('for worker_id in range(2,c): runtime.workers.append(ContextWorker(runtime.engine,worker_id))',source)
        self.assertIn('for worker_id in range(c):',source)
        self.assertEqual(source.replace('runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))',
            'runtime=ConcurrentTensorRT(str(ENGINE),2)').replace(
            'from summary_adapter import summarize','from b1_summary import summarize'),
            c.frozen_run_source())
        self.assertIn('if len({r[field] for r in resources})!=c:',source)
        self.assertEqual(_source.count(_old),1)
        self.assertIn('C',_validate_dynamic_workers.__code__.co_consts)

    def test_plateau_and_c2(self):
        out=decide(rows({1:100,2:198,3:200,4:201},{1:101,2:199,3:201,4:200}))
        self.assertEqual(out['status'],'C_L2_DEPLOYMENT_JUSTIFIED')
        self.assertEqual(out['C_selected'],2)
        self.assertEqual(out['auxiliary_plateau_eligible'],[2,3,4])
        self.assertEqual(out['T_2'],out['r_2']/.98)

    def test_c1_and_c3_outcomes(self):
        one=decide(rows({1:200,2:201,3:200,4:200},{1:200,2:200,3:200,4:201}))
        self.assertEqual(one['status'],'C_L2_NOT_MINIMAL')
        three=decide(rows({1:100,2:150,3:200,4:201},{1:100,2:151,3:201,4:200}))
        self.assertEqual(three['status'],'C_L2_REJECTED_HIGHER_C_REQUIRED')
        self.assertIsNone(three['C_selected'])
        self.assertFalse(three['higher_C_final_winner_selected'])

    def test_repeat_ambiguity(self):
        ambiguous=decide(rows({1:100,2:200,3:203,4:200},{1:100,2:200,3:209,4:200}))
        self.assertEqual(ambiguous['status'],'CALIBRATION_REPEAT_AMBIGUOUS')
        self.assertIsNone(ambiguous['C_selected'])
        self.assertEqual(ambiguous['third_repeat_proposal_only'],[2,3])

    def test_higher_source_limited_can_reject_but_never_justify(self):
        high=rows({1:100,2:200,3:240,4:201},{1:100,2:200,3:240,4:201})
        for row in high:
            if row['C_L']==3:row['saturation_status']='SOURCE_LIMITED'
        out=decide(high)
        self.assertEqual(out['status'],'C_L2_REJECTED_HIGHER_C_REQUIRED')
        self.assertIsNone(out['auxiliary_plateau_eligible'])
        low=rows({1:100,2:236,3:240,4:238},{1:100,2:236,3:240,4:238})
        for row in low:
            if row['C_L']==3:row['saturation_status']='SOURCE_LIMITED'
        out=decide(low)
        self.assertEqual(out['status'],'C_L2_INCONCLUSIVE_SOURCE_CEILING')
        self.assertIsNone(out['C_selected'])

    def test_strict_threshold_and_c1_precedence(self):
        threshold=200/.98
        at=rows({1:100,2:200,3:threshold,4:199},
                {1:100,2:200,3:threshold,4:199})
        self.assertEqual(decide(at)['status'],'C_L2_DEPLOYMENT_JUSTIFIED')
        above=rows({1:200,2:200,3:240,4:200},
                   {1:200,2:200,3:240,4:200})
        self.assertEqual(decide(above)['status'],'C_L2_NOT_MINIMAL')

    def test_saturation_source_ceiling_and_ambiguity(self):
        self.assertEqual(saturation_status(True,'UNSUSTAINABLE',240,214),'SATURATED_VALID')
        self.assertEqual(saturation_status(True,'STABLE',240,239.7),'SOURCE_LIMITED')
        self.assertEqual(saturation_status(True,'BOUNDARY',240,239.3),'AMBIGUOUS')
        self.assertEqual(saturation_status(False,'UNSUSTAINABLE',240,214),'INVALID')
        fixture=rows({1:100,2:198,3:200,4:201},{1:101,2:199,3:201,4:200})
        fixture[3]['saturation_status']='AMBIGUOUS'
        self.assertEqual(decide(fixture)['status'],'CALIBRATION_REPEAT_AMBIGUOUS')

    def test_incomplete_run_cannot_receive_primary_verdict(self):
        fixture=rows({1:100,2:198,3:200,4:201},{1:101,2:199,3:201,4:200})
        fixture[2]['saturation_status']='SOURCE_LIMITED'
        for row in fixture[3:]:row['raw_scan_integrity_status']='INVALID'
        out=decide(fixture)
        self.assertEqual(out['status'],'CALIBRATION_INVALID_OR_INCOMPLETE')
        self.assertIsNone(out['primary_verdict'])

    def test_time_weighted_concurrency(self):
        intervals=[dict(inference_start_timestamp_ns='0',completion_timestamp_ns='1000000000'),
                   dict(inference_start_timestamp_ns='0',completion_timestamp_ns='1000000000')]
        self.assertEqual(active_concurrency_p95(intervals,0,1000000000),2)
        self.assertEqual(active_concurrency_p95([],0,1000000000),0)

    def test_supervisor_and_memory_are_existing_path(self):
        source=supervisor_source()
        self.assertIn("admission_fps_per_stream=c['admission_r']",source)
        self.assertIn('pruning_enabled=False',source)
        self.assertIn("time.sleep(plan['idle_seconds'])",source)
        self.assertEqual(memory_snapshot()['status'],'PASS')
        launcher=(c.HERE/'run_scan.py').read_text()
        self.assertIn('gpu_control_readiness()\n        mem=memory_snapshot()',launcher)

    def test_parent_finalizer_uses_c_aware_summary_and_cardinality(self):
        import dis
        source=parent_finalizer_source()
        self.assertIn('from summary_adapter import summarize,read_csv',source)
        self.assertIn('validate_parent_artifacts(directory,manifest,frames,measured)',source)
        self.assertNotIn('from b1_summary import summarize,read_csv',source)
        bound=Context().bindings()[1]
        imports=[item.argval for item in dis.get_instructions(bound)
                 if item.opname=='IMPORT_NAME']
        self.assertEqual(imports,['summary_adapter','parent_validation'])


if __name__=='__main__':
    unittest.main()
