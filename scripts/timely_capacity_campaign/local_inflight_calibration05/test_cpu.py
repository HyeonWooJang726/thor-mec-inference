"""CPU-only Calibration05 closure, runtime-binding and memory tests."""
import dis
import unittest

import config as cfg
from selection import decide,saturation_status
from run_scan import Context,parent_finalizer_source,memory_snapshot,supervisor_source


def rows(r1, r2, supply=None):
    supply=supply or {}
    return [dict(run_id=f'LINFLIGHT05_C{c}_R{rep}',C_L=c,repeat=rep,
                 active_completed_FPS=values[c],raw_scan_integrity_status='VALID',
                 saturation_status=supply.get((c,rep),'SATURATED_VALID'),OC3_delta=999)
            for rep,values in ((1,r1),(2,r2)) for c in (3,4,5,6)]


class FinalClosureTests(unittest.TestCase):
    def test_order_and_only_c_changes(self):
        order=cfg.order()
        self.assertEqual([x['run_id'] for x in order],[
            'LINFLIGHT05_C3_R1','LINFLIGHT05_C4_R1','LINFLIGHT05_C5_R1','LINFLIGHT05_C6_R1',
            'LINFLIGHT05_C6_R2','LINFLIGHT05_C5_R2','LINFLIGHT05_C4_R2','LINFLIGHT05_C3_R2'])
        ignored={'run_id','C','repeat','order_index','cell','original_cell','pass','pass_name'}
        base={k:v for k,v in order[0].items() if k not in ignored}
        self.assertTrue(all({k:v for k,v in row.items() if k not in ignored}==base for row in order))
        self.assertTrue(all(row['target_service_FPS']==240 and row['seconds']==60 and
                            row['frequency_MHz']==1575 and row['edge_r']==0 and
                            row['pruning_enabled'] is False for row in order))

    def test_derived_worker_and_parent_binding(self):
        source=cfg.run_source()
        self.assertIn('runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))',source)
        self.assertIn('for worker_id in range(2,c): runtime.workers.append(ContextWorker(runtime.engine,worker_id))',source)
        self.assertIn('from summary_adapter import summarize',source)
        self.assertEqual(source.replace('runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))',
            'runtime=ConcurrentTensorRT(str(ENGINE),2)').replace(
            'from summary_adapter import summarize','from b1_summary import summarize'),
            cfg.frozen_run_source())
        parent=parent_finalizer_source()
        self.assertIn('validate_parent_artifacts(directory,manifest,frames,measured)',parent)
        self.assertEqual([x.argval for x in dis.get_instructions(Context().bindings()[1])
                          if x.opname=='IMPORT_NAME'],['summary_adapter','parent_validation'])
        self.assertIn('pruning_enabled=False',supervisor_source())

    def test_supply_classes(self):
        self.assertEqual(saturation_status(True,'UNSUSTAINABLE',240,234),'SATURATED_VALID')
        self.assertEqual(saturation_status(True,'STABLE',240,239.5),'SOURCE_LIMITED')
        self.assertEqual(saturation_status(True,'BOUNDARY',240,238),'AMBIGUOUS')
        self.assertEqual(saturation_status(False,'UNSUSTAINABLE',240,234),'INVALID')

    def test_c6_two_of_two_full_load_selects_6(self):
        fixture=rows({3:232,4:234,5:235,6:239.6},{3:232,4:234,5:235,6:239.7},
                     {(6,1):'SOURCE_LIMITED',(6,2):'SOURCE_LIMITED'})
        result=decide(fixture)
        self.assertEqual(result['primary_verdict'],'FULL_LOAD_SUSTAINABLE_C_SELECTED')
        self.assertEqual(result['C_selected'],6)
        self.assertTrue(result['source_ceiling_reached'])

    def test_c5_and_c6_full_load_selects_5(self):
        supply={(c,rep):'SOURCE_LIMITED' for c in (5,6) for rep in (1,2)}
        result=decide(rows({3:232,4:234,5:239.6,6:239.8},
                           {3:232,4:234,5:239.7,6:239.9},supply))
        self.assertEqual(result['primary_verdict'],'FULL_LOAD_SUSTAINABLE_C_SELECTED')
        self.assertEqual(result['C_selected'],5)

    def test_c4_c5_c6_full_load_selects_4(self):
        supply={(c,rep):'SOURCE_LIMITED' for c in (4,5,6) for rep in (1,2)}
        result=decide(rows({3:232,4:239.6,5:239.7,6:239.8},
                           {3:232,4:239.6,5:239.8,6:239.9},supply))
        self.assertEqual(result['C_selected'],4)

    def test_saturated_plateau_selects_3(self):
        result=decide(rows({3:232,4:234,5:235,6:236},{3:232,4:234,5:235,6:236}))
        self.assertEqual(result['primary_verdict'],'FINAL_SATURATED_PLATEAU_C_SELECTED')
        self.assertEqual(result['C_selected'],3)
        self.assertTrue(result['plateau_supported'])
        self.assertTrue(result['OC3_diagnostic_only'])
        self.assertTrue(result['calibration05_is_selection_dataset'])
        self.assertFalse(result['previous_calibrations_used_for_selection'])

    def test_saturated_plateau_selects_4(self):
        result=decide(rows({3:230,4:234,5:235,6:236},{3:230,4:234,5:235,6:236}))
        self.assertEqual(result['primary_verdict'],'FINAL_SATURATED_PLATEAU_C_SELECTED')
        self.assertEqual(result['C_selected'],4)

    def test_not_reached_and_no_auto_c7(self):
        result=decide(rows({3:230,4:231,5:232,6:239},{3:230,4:231,5:232,6:239}))
        self.assertEqual(result['primary_verdict'],'FINAL_CLOSURE_NOT_REACHED')
        self.assertTrue(result['C7_extension_required'])
        self.assertIsNone(result['C_selected'])
        self.assertTrue(result['no_C7_or_third_repeat_automatic'])

    def test_mixed_repeat_supply_class_has_no_selection(self):
        result=decide(rows({3:232,4:234,5:235,6:239.6},
                           {3:232,4:234,5:235,6:239.7},
                           {(6,1):'SOURCE_LIMITED'}))
        self.assertEqual(result['primary_verdict'],'C_LEVEL_REPEAT_AMBIGUOUS')
        self.assertEqual(result['per_C_supply_class']['6'],'C_LEVEL_REPEAT_AMBIGUOUS')
        self.assertIsNone(result['C_selected'])

    def test_invalid_excluded(self):
        fixture=rows({3:230,4:232,5:234,6:235},{3:230,4:232,5:234,6:235})
        fixture[0]['raw_scan_integrity_status']='INVALID'
        result=decide(fixture)
        self.assertEqual(result['primary_verdict'],'NO_C_SELECTION_INVALID_DATA')
        self.assertIsNone(result['C_selected'])
        self.assertIsNone(result['r_3'])

    def test_repeat_branch_or_selected_c_ambiguity(self):
        result=decide(rows({3:230,4:231,5:232,6:233},
                           {3:230,4:231,5:232,6:240}))
        self.assertEqual(result['primary_verdict'],'REPEAT_AMBIGUOUS')
        result=decide(rows({3:232,4:234,5:235,6:236},
                           {3:229,4:234,5:235,6:236}))
        self.assertEqual(result['primary_verdict'],'REPEAT_AMBIGUOUS')

    def test_two_of_two_ambiguous_supply_has_no_selection(self):
        result=decide(rows({3:232,4:234,5:235,6:237},
                           {3:232,4:234,5:235,6:237},
                           {(6,1):'AMBIGUOUS',(6,2):'AMBIGUOUS'}))
        self.assertEqual(result['primary_verdict'],'REPEAT_AMBIGUOUS')
        self.assertEqual(result['repeat_ambiguity_kind'],'TWO_OF_TWO_AMBIGUOUS_SUPPLY')
        self.assertIsNone(result['C_selected'])

    def test_historical_selection_input_rejected(self):
        fixture=rows({3:232,4:234,5:235,6:236},{3:232,4:234,5:235,6:236})
        fixture[0]['run_id']='LINFLIGHT04_C3_R1'
        with self.assertRaisesRegex(ValueError,'Historical or wrong-namespace'):
            decide(fixture)

    def test_memory_readiness(self):
        snapshot=memory_snapshot()
        self.assertEqual(snapshot['planned_max_C'],6)
        self.assertEqual(snapshot['status'],'PASS')
        self.assertGreater(snapshot['headroom_after_reserve_bytes'],0)


if __name__=='__main__':unittest.main()
