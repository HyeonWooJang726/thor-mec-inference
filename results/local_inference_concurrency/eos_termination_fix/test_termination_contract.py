"""Explicit synthetic event fixtures, no frame-derived/fake EOS and no GPU."""
import unittest
from termination_contract_checks import BoundedTerminationEvidence


class ContractTests(unittest.TestCase):
    def source_events(self, c):
        for i in range(c.streams):
            c.source_complete(i,c.expected)
            c.observe_eos_event(i)
            c.worker_joined(i,False)

    def test_01_every_stream_exact_bound_required(self):
        c=BoundedTerminationEvidence(2,900)
        with self.assertRaises(ValueError):c.source_complete(0,899)
        with self.assertRaises(ValueError):c.source_complete(0,901)
        self.source_events(c);c.inference_drained(1800,0,0)
        self.assertTrue(c.ready_for_shutdown())

    def test_02_one_source_completes_late(self):
        c=BoundedTerminationEvidence(2,900)
        c.inference_drained(1800,0,0)
        for i in range(2):c.observe_eos_event(i);c.worker_joined(i,False)
        c.source_complete(0,900);self.assertFalse(c.ready_for_shutdown())
        c.source_complete(1,900);self.assertTrue(c.ready_for_shutdown())

    def test_03_last_job_and_source_completion_order(self):
        for source_first in (True,False):
            c=BoundedTerminationEvidence(2,900)
            if source_first:self.source_events(c)
            c.inference_drained(1800,0,0)
            if not source_first:self.source_events(c)
            self.assertTrue(c.ready_for_shutdown())

    def test_04_duplicate_source_completion_idempotent(self):
        c=BoundedTerminationEvidence(2,900)
        self.assertTrue(c.source_complete(0,900))
        self.assertFalse(c.source_complete(0,900))
        self.assertEqual(c.duplicate_source_events,1)
        self.assertEqual(c.eos_events,set())
        self.assertFalse(c.ready_for_shutdown())

    def test_05_delayed_actual_eos_event(self):
        c=BoundedTerminationEvidence(2,900)
        for i in range(2):c.source_complete(i,900);c.worker_joined(i,False)
        c.inference_drained(1800,0,0);c.observe_eos_event(0)
        self.assertFalse(c.ready_for_shutdown())
        c.observe_eos_event(1);self.assertTrue(c.ready_for_shutdown())

    def test_06_frame_drain_still_requires_join_and_null(self):
        c=BoundedTerminationEvidence(1,900)
        c.source_complete(0,900);c.observe_eos_event(0);c.inference_drained(900,0,0)
        self.assertFalse(c.ready_for_shutdown())
        with self.assertRaises(ValueError):c.worker_joined(0,True)
        c.worker_joined(0,False)
        with self.assertRaises(ValueError):c.pipeline_shutdown(0,'PLAYING')
        self.assertFalse(c.complete())
        c.pipeline_shutdown(0,'NULL');self.assertTrue(c.complete())

    def test_07_timeout_detects_missing_termination_without_faking_eos(self):
        c=BoundedTerminationEvidence(1,900)
        c.source_complete(0,900);c.worker_joined(0,False);c.inference_drained(900,0,0)
        c.check_deadline(9,10)
        with self.assertRaises(TimeoutError):c.check_deadline(10,10)
        self.assertEqual(c.eos_events,set())
        self.assertFalse(c.complete())


if __name__=='__main__':unittest.main()
