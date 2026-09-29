"""No workload or network calls; deterministic order/fidelity regressions."""
import unittest
import sys
from pathlib import Path

import config as c
from analyze import mechanism, describe


def synthetic(condition):
    start = 10_000_000_000
    rows = []
    rid = 0
    for frame in range(condition['seconds']*30):
        due = start + frame*10**9//30
        order = c.submit_order(condition['dispatch_order_mode'],frame) if condition['stage']=='MEASURED' and c.q6()[frame%30] else list(range(8))
        for position,sid in enumerate(order):
            selected = c.bit(condition['pattern'],sid,frame)
            row = {'stream_id':sid,'frame_id':frame,'logical_arrival_ns':due,
                   'admission_timestamp_ns':due,'admission_observed_ns':due+position+1,
                   'admitted':selected,'placement':'EDGE' if selected else 'SKIP',
                   'dispatch_order_mode':condition['dispatch_order_mode'],
                   'dispatch_position':position if selected else None,
                   'active_slot_index':c.active_index(frame) if condition['stage']=='MEASURED' and selected else -1}
            if selected:
                row.update(edge_request_id=rid,edge_release_target_ns=due,
                           absolute_deadline_ns=due+100_000_000)
                rid += 1
            rows.append(row)
    return rows,start


class OrderTests(unittest.TestCase):
    def test_frozen_sequence(self):
        order=c.frozen_order()
        self.assertEqual(len(order),16)
        self.assertEqual(order[0]['run_id'],'EDGEORDER01_WARMUP_E48_S')
        self.assertEqual([(r['dispatch_order_mode'],r['repeat']) for r in order[1:]],list(c.SEQUENCE))

    def test_masks_and_exposure(self):
        self.assertEqual(sum(c.q6()),6)
        matrix=c.exposure()
        self.assertEqual(sum(map(sum,matrix)),1440)
        self.assertTrue(all(v in (22,23) for row in matrix for v in row))
        self.assertTrue(all(max(row)-min(row)<=1 for row in matrix))
        for mode in c.MODES:
            cond=next(row for row in c.frozen_order() if row['dispatch_order_mode']==mode)
            rows,start=synthetic(cond)
            self.assertEqual(c.validate_source_rows(rows,cond,start)['status'],'PASS')
            rows[0]['logical_arrival_ns'] += 1
            self.assertEqual(c.validate_source_rows(rows,cond,start)['status'],'FAIL')

    def test_G_id_rule(self):
        rows=[]
        for i in range(1,6):
            rows.extend([{'dispatch_order_mode':'BASE','repeat':i,'stream0_minus_stream7_TIR':.2},
                         {'dispatch_order_mode':'REVERSE','repeat':i,'stream0_minus_stream7_TIR':-.2}])
        self.assertEqual(mechanism(rows)['verdict'],'ORDER_EFFECT_SUPPORTED')
        rows[-1]['stream0_minus_stream7_TIR']=0
        self.assertEqual(mechanism(rows)['verdict'],'ORDER_EFFECT_NOT_FULLY_SUPPORTED')
        self.assertEqual(describe([1,-1,2,0,3])['positive_count'],3)

    def test_edge_hello_and_frozen_backend(self):
        bundle = c.ROOT/'results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/edge_bundle'
        sys.path.insert(0,str(bundle))
        from edge_server_order01 import expected_hello
        for condition in c.frozen_order():
            self.assertEqual(c.hello(condition,'PLAN','CACHE'), expected_hello(condition,'PLAN','CACHE'))
        self.assertNotIn('socket.create_connection',Path(c.HERE/'run_thor.py').read_text())


if __name__=='__main__':unittest.main()
