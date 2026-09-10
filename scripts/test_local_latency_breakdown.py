"""Synthetic correctness checks only; no GPU workload or performance measurements."""

import csv
from fractions import Fraction
import queue
import tempfile
from pathlib import Path
import threading
import unittest

from local_latency_breakdown_metrics import (
    QueueAccounting, queue_metrics, validate_timing, frame_rows_ns, run_summary,
    aggregate_runs, write_csv, PER_FRAME_FIELDS, PER_RUN_FIELDS, MOTIVATION_FIELDS,
    QUEUE_FIELDS,
)


def job(i):
    return {"stream_id": 0, "frame_id": i, "a_ns": 0, "b_ns": 1, "c_ns": 100}


class MeasurementTests(unittest.TestCase):
    def test_dequeued_handoff_and_service_exclusion(self):
        q, accounting, lock = queue.Queue(), QueueAccounting(), threading.Lock()
        records = [job(i) for i in range(3)]
        with lock:
            accounting.enqueue(q, records[0], lambda: 10)
        dequeued = q.get()
        with lock:
            accounting.enqueue(q, records[1], lambda: 20)
            accounting.start(dequeued, lambda: 30)
            accounting.enqueue(q, records[2], lambda: 40)
            accounting.start(q.get(), lambda: 50)
            accounting.start(q.get(), lambda: 60)
        self.assertEqual([r["inference_queue_depth_before_enqueue"] for r in records], [0, 1, 1])
        metrics = queue_metrics(accounting.events, records, 3, 3)
        self.assertEqual(metrics["inference_queue_peak"], 2)
        self.assertEqual(metrics["inference_queue_at_last_enqueue"], 2)
        self.assertEqual(metrics["integral_frame_ns"], 40)
        self.assertEqual(metrics["inference_queue_time_weighted"], Fraction(4, 3))
        self.assertEqual(metrics["waiting_after_drain"], 0)
        accounting.events[2]["seq"] = 99
        with self.assertRaises(ValueError):
            queue_metrics(accounting.events, records, 3, 3)

    def test_equal_timestamp_lock_sequence(self):
        q, a = queue.Queue(), QueueAccounting()
        records = [job(i) for i in range(3)]
        a.enqueue(q, records[0], lambda: 10)
        a.start(q.get(), lambda: 10)
        a.enqueue(q, records[1], lambda: 10)
        a.start(q.get(), lambda: 20)
        a.enqueue(q, records[2], lambda: 20)
        a.start(q.get(), lambda: 20)
        m = queue_metrics(a.events, records, 3, 3)
        self.assertEqual(m["inference_queue_peak"], 1)
        self.assertEqual(m["inference_queue_time_weighted"], 1)
        self.assertEqual(m["inference_queue_at_last_enqueue"], 1)

    def test_concurrent_accounting(self):
        q, a, lock = queue.Queue(), QueueAccounting(), threading.Lock()
        records = []
        tick = iter(range(10, 10000))

        def producer(stream):
            for i in range(50):
                r = dict(job(i), stream_id=stream, c_ns=10000)
                with lock:
                    a.enqueue(q, r, lambda: next(tick))

        def consumer():
            for _ in range(150):
                r = q.get(timeout=5)
                with lock:
                    a.start(r, lambda: next(tick))
                records.append(r)

        workers = [threading.Thread(target=producer, args=(i,)) for i in range(3)]
        workers.append(threading.Thread(target=consumer))
        for t in reversed(workers):
            t.start()
        for t in workers:
            t.join(timeout=10)
            self.assertFalse(t.is_alive())
        self.assertEqual(len(records), 150)
        self.assertEqual(queue_metrics(a.events, records, a.n_enqueue, a.n_start)["waiting_after_drain"], 0)

    def test_integer_timing_and_exact_deadline(self):
        records = [dict(job(i), r_ns=2, s_ns=3, c_ns=c,
                        inference_queue_depth_before_enqueue=0)
                   for i, c in enumerate((33_333_333, 33_333_334))]
        self.assertFalse(any(validate_timing(records).values()))
        self.assertEqual([r["deadline_miss"] for r in frame_rows_ns(records, 0)], [0, 1])
        records[0]["b_ns"] = -1
        self.assertEqual(validate_timing(records)["timestamp_ordering_violations"], 1)
        records[0]["b_ns"] = 0.0
        with self.assertRaises(ValueError):
            validate_timing(records)

    def test_exact_schemas_and_nonpooled_formal_aggregation(self):
        expected_frame = "stream_id frame_id scheduled_arrival_rel_ms frame_start_lag_ms front_end_ms inference_queue_wait_ms inference_ms e2e_ms inference_queue_depth_before_enqueue deadline_miss".split()
        expected_run = "K run_id frame_start_lag_mean_ms frame_start_lag_p95_ms front_end_mean_ms front_end_p95_ms inference_queue_wait_mean_ms inference_queue_wait_p95_ms inference_mean_ms inference_p95_ms e2e_mean_ms e2e_p95_ms e2e_p99_ms deadline_miss_pct".split()
        self.assertEqual(PER_FRAME_FIELDS, expected_frame)
        self.assertEqual(PER_RUN_FIELDS, expected_run)
        self.assertEqual(MOTIVATION_FIELDS, ["K", "offered_load_fps", "run_count"] + expected_run[2:])
        self.assertEqual(QUEUE_FIELDS, "K run_count inference_queue_peak_mean inference_queue_time_weighted_mean inference_queue_at_last_enqueue_mean".split())
        runs, queues = [], []
        for k in range(1, 8):
            for i in range(1, 6):
                raw = [dict(job(j), r_ns=2, s_ns=3, c_ns=i * 20_000_000,
                            inference_queue_depth_before_enqueue=0) for j in range(i)]
                rows = frame_rows_ns(raw, 0)
                runs.append(run_summary(rows, k, f"run{i:02d}"))
                queues.append({"K": k, "run_id": f"run{i:02d}",
                               "inference_queue_peak": i,
                               "inference_queue_time_weighted": Fraction(i, 2),
                               "inference_queue_at_last_enqueue": i - 1})
        motivations, qs = aggregate_runs(runs, queues, formal=True)
        for m, q in zip(motivations, qs):
            self.assertEqual(m["run_count"], 5)
            self.assertEqual(m["offered_load_fps"], m["K"] * 30)
            for metric in ("mean", "p95", "p99"):
                self.assertEqual(m[f"e2e_{metric}_ns"], 60_000_000)
            self.assertEqual(m["deadline_miss_pct"], 80)
            self.assertEqual(q["inference_queue_peak_mean"], 3)
            self.assertEqual(q["inference_queue_time_weighted_mean"], Fraction(3, 2))
            self.assertEqual(q["inference_queue_at_last_enqueue_mean"], 2)
        with self.assertRaises(ValueError):
            aggregate_runs(runs[:-1], queues[:-1], formal=True)
        with self.assertRaises(ValueError):
            aggregate_runs(runs + [runs[0]], queues + [queues[0]], formal=False)
        smoke, _ = aggregate_runs([runs[0]], [queues[0]], formal=False)
        self.assertEqual(smoke[0]["run_count"], 1)
        with tempfile.TemporaryDirectory(prefix="latency-schema-") as temp:
            for fields, data in ((PER_FRAME_FIELDS, rows), (PER_RUN_FIELDS, runs),
                                 (MOTIVATION_FIELDS, motivations), (QUEUE_FIELDS, qs)):
                path = Path(temp) / f"synthetic_{len(fields)}.csv"
                write_csv(path, fields, data)
                with path.open() as f:
                    self.assertEqual(next(csv.reader(f)), fields)
                before = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    write_csv(path, fields, data)
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
