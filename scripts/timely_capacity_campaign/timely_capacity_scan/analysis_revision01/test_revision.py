"""CPU/log-only terminal identity and expectation isolation tests."""
import copy
import json
import unittest
import types
from pathlib import Path
import analyze_revision as a
from timely_config import frozen,order


def frames(t=90,l=6,x=4,n=100):
    rows=[];arrival=1_000_000_000;D=100_000_000
    for i in range(n):
        state='COMPLETED' if i<t+l else 'EXPIRED_DROP' if i<t+l+x else ''
        rows.append(dict(stream_id=i%8,frame_id=i//8,logical_arrival_ns=arrival,
            absolute_deadline_ns=arrival+D,terminal_state=state,
            completion_timestamp_ns=arrival+(90_000_000 if i<t else 110_000_000) if i<t+l else '',
            inference_start_timestamp_ns=arrival+50_000_000 if i<t+l else '',
            expired_drop_ns=arrival+D if state=='EXPIRED_DROP' else '',
            expiry_check_ns=arrival+D if state=='EXPIRED_DROP' else arrival+50_000_000 if i<t+l else ''))
    return rows


def guarded(p,rate=208,rep=1):
    return a.enforce_validity(dict(p,integrity_status='VALID',classification=a.prior.run_class(True,p['TIR_admission']),
        deadline_ms=100,offered_FPS=rate,repeat=rep,timely_FPS=p['N_timely']/60,expired_FPS=p['N_expired']/60,late_completed_FPS=p['N_late_completed']/60))


class RevisionTests(unittest.TestCase):
    def test_exact_partition_90_6_4(self):
        p=a.terminal_partition(frames(),100)
        self.assertEqual((p['N_admitted'],p['N_timely'],p['N_late_completed'],p['N_expired']),(100,90,6,4))
        self.assertEqual(p['terminal_accounting_error'],0);self.assertTrue(p['terminal_accounting_PASS']);self.assertTrue(p['terminal_partition_PASS'])
        self.assertNotEqual(guarded(p)['classification'],'INVALID')

    def test_missing_one(self):
        p=a.terminal_partition(frames(90,5,4),100);r=guarded(p)
        self.assertEqual(p['terminal_accounting_error'],1);self.assertFalse(p['terminal_accounting_PASS'])
        self.assertEqual(r['classification'],'INVALID');self.assertIsNone(r['TIR_admission'])

    def test_double_count_error_minus_one(self):
        rows=frames();rows[-1].update(completion_timestamp_ns=1_090_000_000,inference_start_timestamp_ns=1_050_000_000)
        p=a.terminal_partition(rows,100)
        self.assertEqual(p['terminal_accounting_error'],-1);self.assertEqual(p['terminal_overlapping_frames'],1)
        self.assertEqual(guarded(p)['classification'],'INVALID')

    def test_pruning_heavy_and_wrong_denominator(self):
        p=a.terminal_partition(frames(60,5,35),100)
        self.assertTrue(p['terminal_accounting_PASS']);self.assertTrue(p['terminal_partition_PASS'])
        self.assertEqual(p['TIR_admission'],.6)
        wrong=p['N_timely']/(p['N_timely']+p['N_late_completed'])
        self.assertGreater(wrong,p['TIR_admission']);self.assertAlmostEqual(wrong,60/65)
        self.assertEqual(guarded(p)['TIR_admission'],.6)

    def test_missing_and_double_cancel_not_valid(self):
        rows=frames(90,5,4)
        rows[-2].update(completion_timestamp_ns=1_090_000_000,inference_start_timestamp_ns=1_050_000_000)
        p=a.terminal_partition(rows,100)
        self.assertEqual(p['terminal_accounting_error'],0);self.assertTrue(p['terminal_accounting_PASS'])
        self.assertFalse(p['terminal_partition_PASS']);self.assertEqual(guarded(p)['classification'],'INVALID')

    def test_expired_started_or_early_rejected(self):
        for key,value in [('inference_start_timestamp_ns',1_099_000_000),('expired_drop_ns',1_099_000_000)]:
            rows=frames();rows[-1][key]=value
            p=a.terminal_partition(rows,100);self.assertFalse(p['terminal_partition_PASS']);self.assertEqual(guarded(p)['classification'],'INVALID')

    def test_duplicate_id_rejected(self):
        rows=frames();rows[-1]['frame_id']=rows[-9]['frame_id']
        p=a.terminal_partition(rows,100);self.assertFalse(p['terminal_partition_PASS'])

    def test_integer_only(self):
        for n in (100.0,True,-1):
            with self.assertRaises(ValueError):a.integer_accounting(n,90,6,4)
        p=a.integer_accounting(100,91,6,4);self.assertEqual(p['terminal_accounting_error'],-1)

    def test_invalid_repeat_excluded(self):
        bad=guarded(a.terminal_partition(frames(90,5,4),100));good=guarded(a.terminal_partition(frames(99,1,0),100),rep=2)
        rates,_=a.prior.summaries([bad,good]);r=next(x for x in rates if x['deadline']==100 and x['offered_FPS']==208)
        self.assertEqual(r['rate_classification'],'INCONCLUSIVE_INVALID');self.assertIsNone(r['R1_TIR']);self.assertEqual(r['TIR_admission_mean'],.99)

    def test_mechanism_never_changes_verdict(self):
        rows=[]
        for c in order():
            p=a.terminal_partition(frames(99,1,0),100)
            r=guarded(p,c['target_service_FPS'],c['repeat']);r.update(run_id=c['run_id'],deadline_ms=c['deadline_ms'])
            rows.append(r)
        before=copy.deepcopy(rows);summaries=a.prior.summaries(rows)
        checks=a.mechanism_checks(rows)
        self.assertEqual(before,rows);self.assertEqual(summaries,a.prior.summaries(rows))
        review={('M1_BUDGET',r['run_id']):dict(matched='NOT_MATCHED',notes='CPU fixture only: queue not near deadline') for r in rows}
        changed=a.mechanism_checks(rows,review)
        self.assertNotEqual(checks,changed);self.assertEqual(summaries,a.prior.summaries(rows))
        self.assertTrue(all(x['verdict_effect']=='NONE' for x in changed))
        self.assertTrue(any('prediction failed' in x['notes'] for x in changed))

    def test_actual_preserved_ON_replay(self):
        c=dict(order()[0],run_id='V22_LOCAL200_ON_R1_P01');d=frozen.OUT/c['run_id']
        old,_=a.prior.analyze_run(d,c);new,_=a.analyze_run(d,c)
        self.assertTrue(new['terminal_accounting_PASS']);self.assertTrue(new['terminal_partition_PASS'])
        self.assertEqual(new['terminal_accounting_error'],0);self.assertEqual(new['classification'],old['classification'])
        self.assertEqual(new['TIR_admission'],old['TIR_admission'])
        self.assertEqual(new['N_admitted'],12000)
        self.assertEqual(new['N_admitted'],new['N_timely']+new['N_late_completed']+new['N_expired'])


if __name__=='__main__':unittest.main(verbosity=2)
