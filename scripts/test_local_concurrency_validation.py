"""CPU-only adversarial interval checks; synthetic fixtures, no performance claims."""
import unittest
import queue
from local_latency_breakdown_metrics import QueueAccounting, queue_metrics
from local_concurrency_validation import interval_metrics, validate_concurrency


def record(worker, start, end):
    return {'worker_id': worker, 's_ns': start, 'c_ns': end,
            'service_start_ns': start, 'service_completion_ns': end,
            'submission_return_ns': start+1, 'stream_sync_return_ns': end-1}


class ValidationTests(unittest.TestCase):
    resources = {'execution_context_count': 2, 'cuda_stream_count': 2}

    def test_concurrent_and_out_of_order_completions(self):
        result = validate_concurrency([record(1, 20, 50), record(0, 0, 100)], self.resources)
        self.assertEqual(result['max_active_inferences'], 2)
        self.assertEqual(result['service_interval_overlap_count'], 1)
        self.assertEqual(result['service_interval_overlap_time_ns'], 30)
        self.assertEqual(result['active_after_drain'], 0)

    def test_touching_intervals_are_not_overlap(self):
        rows = [record(0, 0, 10), record(1, 10, 20)]
        self.assertEqual(interval_metrics(rows)['max_active_inferences'], 1)
        with self.assertRaisesRegex(ValueError, 'no concurrent service'):
            validate_concurrency(rows, self.resources)

    def test_same_context_concurrent_use_rejected(self):
        with self.assertRaisesRegex(ValueError, 'same worker'):
            interval_metrics([record(0, 0, 100), record(0, 20, 50)])

    def test_capacity_three_rejected(self):
        with self.assertRaisesRegex(ValueError, 'C=2'):
            interval_metrics([record(i, i, 100) for i in range(3)])

    def test_host_service_overlap_without_submitted_overlap_rejected(self):
        rows = [record(0, 0, 100), record(1, 50, 150)]
        rows[0]['stream_sync_return_ns'] = 60
        rows[1]['submission_return_ns'] = 70
        with self.assertRaisesRegex(ValueError, 'no overlapping submitted'):
            validate_concurrency(rows, self.resources)

    def test_bad_submission_order_rejected(self):
        rows = [record(0, 0, 100), record(1, 20, 50)]
        rows[0]['submission_return_ns'] = -1
        with self.assertRaisesRegex(ValueError, 'submission ordering'):
            validate_concurrency(rows, self.resources)

    def test_c1_valid_without_overlap(self):
        result = validate_concurrency([record(0, 0, 10), record(0, 10, 20)],
                                      {'execution_context_count': 1, 'cuda_stream_count': 1}, 1)
        self.assertEqual(result['max_active_inferences'], 1)
        self.assertEqual(result['service_overlap_pair_count'], 0)

    def test_c1_rejects_two_configured_resources(self):
        with self.assertRaisesRegex(ValueError, 'count differs'):
            validate_concurrency([record(0, 0, 10)], self.resources, 1)

    def test_waiting_queue_excludes_two_active_requests(self):
        accounting, ready = QueueAccounting(), queue.Queue()
        a = {'stream_id': 0, 'frame_id': 0, 'c_ns': 100}
        b = {'stream_id': 1, 'frame_id': 0, 'c_ns': 80}
        accounting.enqueue(ready, a, lambda: 10)
        accounting.enqueue(ready, b, lambda: 20)
        accounting.start(ready.get(), lambda: 30)
        accounting.start(ready.get(), lambda: 40)
        self.assertEqual(accounting.n_enqueue-accounting.n_start, 0)
        result = queue_metrics(accounting.events, [b, a], 2, 2)
        self.assertEqual(result['waiting_after_drain'], 0)
        self.assertEqual(result['inference_queue_peak'], 2)
        self.assertEqual(result['integral_frame_ns'], 10)


if __name__ == '__main__':
    unittest.main()
