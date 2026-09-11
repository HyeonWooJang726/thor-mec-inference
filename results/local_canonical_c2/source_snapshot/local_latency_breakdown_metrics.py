"""Measurement-only helpers; never launches a workload or creates formal directories."""

import csv
from fractions import Fraction

PER_FRAME_FIELDS = [
    "stream_id", "frame_id", "scheduled_arrival_rel_ms", "frame_start_lag_ms",
    "front_end_ms", "inference_queue_wait_ms", "inference_ms", "e2e_ms",
    "inference_queue_depth_before_enqueue", "deadline_miss",
]
PER_RUN_FIELDS = [
    "K", "run_id", "frame_start_lag_mean_ms", "frame_start_lag_p95_ms",
    "front_end_mean_ms", "front_end_p95_ms", "inference_queue_wait_mean_ms",
    "inference_queue_wait_p95_ms", "inference_mean_ms", "inference_p95_ms",
    "e2e_mean_ms", "e2e_p95_ms", "e2e_p99_ms", "deadline_miss_pct",
]
MOTIVATION_FIELDS = ["K", "offered_load_fps", "run_count"] + PER_RUN_FIELDS[2:]
QUEUE_FIELDS = [
    "K", "run_count", "inference_queue_peak_mean",
    "inference_queue_time_weighted_mean", "inference_queue_at_last_enqueue_mean",
]
SEGMENTS = {
    "frame_start_lag": ("a_ns", "b_ns"), "front_end": ("b_ns", "r_ns"),
    "inference_queue_wait": ("r_ns", "s_ns"), "inference": ("s_ns", "c_ns"),
    "e2e": ("a_ns", "c_ns"),
}


class QueueAccounting:
    """All methods that mutate state MUST run under the caller's state_lock.

    A dequeued frame remains conceptually waiting until start(). No physical
    queue length is consulted. Events are appended in lock order, never sorted.
    """

    def __init__(self):
        self.n_enqueue = 0
        self.n_start = 0
        self.events = []

    def enqueue(self, ready_queue, job, clock):
        depth = self.n_enqueue - self.n_start
        if depth < 0:
            raise RuntimeError("negative waiting depth")
        job["inference_queue_depth_before_enqueue"] = depth
        # Unbounded put completes before its timestamp. A concurrent get may
        # return, but cannot start service until this accounting lock is released.
        ready_queue.put(job)
        job["r_ns"] = clock()
        self.n_enqueue += 1
        self.events.append({"seq": len(self.events), "kind": "enqueue",
                            "ns": job["r_ns"], "stream_id": job["stream_id"],
                            "frame_id": job["frame_id"], "depth": depth + 1})

    def start(self, job, clock):
        if self.n_start >= self.n_enqueue:
            raise RuntimeError("inference start without enqueue")
        self.n_start += 1
        event = {"seq": len(self.events), "kind": "start", "ns": None,
                 "stream_id": job["stream_id"], "frame_id": job["frame_id"],
                 "depth": self.n_enqueue - self.n_start}
        self.events.append(event)
        # Sample at the end of bookkeeping, immediately before lock release and
        # infer(). The lock is never held across TensorRT service.
        job["s_ns"] = clock()
        event["ns"] = job["s_ns"]


def queue_metrics(events, records, n_enqueue, n_start):
    by_id = {(r["stream_id"], r["frame_id"]): r for r in records}
    enqueued, started = set(), set()
    depth = peak = area = 0
    first = previous = last = None
    last_area = at_last = 0
    for seq, event in enumerate(events):
        ns = event["ns"]
        if event["seq"] != seq or type(ns) is not int:
            raise ValueError("queue event sequence/type inconsistency")
        if previous is not None:
            if ns < previous:
                raise ValueError("queue clock/order inconsistency")
            area += depth * (ns - previous)
        key = (event["stream_id"], event["frame_id"])
        record = by_id[key]
        if event["kind"] == "enqueue":
            if key in enqueued or record["r_ns"] != ns:
                raise ValueError("duplicate or mismatched enqueue")
            if record["inference_queue_depth_before_enqueue"] != depth:
                raise ValueError("enqueue depth mismatch")
            enqueued.add(key)
            depth += 1
            if first is None:
                first = ns
            last, last_area, at_last = ns, area, depth
        elif event["kind"] == "start":
            if key not in enqueued or key in started or record["s_ns"] != ns:
                raise ValueError("unmatched or duplicate start")
            started.add(key)
            depth -= 1
        else:
            raise ValueError("unknown queue event")
        if depth < 0 or depth != event["depth"] or len(enqueued) < len(started):
            raise ValueError("negative/inconsistent queue state")
        peak = max(peak, depth)
        previous = ns
    if not (enqueued == started == set(by_id) and depth == 0
            and n_enqueue == n_start == len(records) == len(enqueued)):
        raise ValueError("queue counters or drain mismatch")
    if first is None or last == first:
        raise ValueError("undefined queue integration interval T=0")
    # Independent interval identity, clipped to the integration endpoints.
    clipped_area = sum(max(0, min(r["s_ns"], last) - max(r["r_ns"], first))
                       for r in records)
    if clipped_area != last_area:
        raise ValueError("queue integral differs from per-frame waiting intervals")
    return {
        "inference_queue_peak": peak,
        "inference_queue_time_weighted": Fraction(last_area, last - first),
        "inference_queue_at_last_enqueue": at_last,
        "integration_start_ns": first, "integration_end_ns": last,
        "integration_duration_ns": last - first, "integral_frame_ns": last_area,
        "waiting_after_drain": depth, "N_enqueue": n_enqueue,
        "N_inference_start": n_start, "event_count": len(events),
    }


def frame_rows_ns(records, t0_ns):
    rows = []
    for r in sorted(records, key=lambda r: (r["stream_id"], r["frame_id"])):
        row = {k: r[k] for k in ("stream_id", "frame_id",
                               "inference_queue_depth_before_enqueue")}
        row["scheduled_arrival_rel_ns"] = r["a_ns"] - t0_ns
        row.update({name + "_ns": r[end] - r[start]
                    for name, (start, end) in SEGMENTS.items()})
        row["deadline_miss"] = int(row["e2e_ns"] * 30 > 1_000_000_000)
        rows.append(row)
    return rows


def validate_timing(records):
    ordering = decomposition = max_error = 0
    for r in records:
        times = [r[k] for k in ("a_ns", "b_ns", "r_ns", "s_ns", "c_ns")]
        if any(type(t) is not int for t in times):
            raise ValueError("timestamps must be integer nanoseconds")
        ordering += int(any(a > b for a, b in zip(times, times[1:])))
        a, b, ready, s, c = times
        error = abs((c - a) - ((b - a) + (ready - b) + (s - ready) + (c - s)))
        decomposition += int(error != 0)
        max_error = max(max_error, error)
    return {"timestamp_ordering_violations": ordering,
            "decomposition_violations": decomposition,
            "max_absolute_decomposition_error_ns": max_error}


def mean(values):
    return sum(values, Fraction()) / len(values)


def percentile_ns(values, p):
    """Exact linear interpolation in ns (same percentile convention as NumPy)."""
    values = sorted(values)
    index = (len(values) - 1) * p
    lo, remainder = divmod(index, 100)
    hi = min(lo + 1, len(values) - 1)
    return Fraction(values[lo] * (100 - remainder) + values[hi] * remainder, 100)


def run_summary(rows, k, run_id):
    result = {"K": k, "run_id": run_id}
    for name in SEGMENTS:
        values = [r[name + "_ns"] for r in rows]
        result[name + "_mean_ns"] = mean(values)
        result[name + "_p95_ns"] = percentile_ns(values, 95)
        if name == "e2e":
            result[name + "_p99_ns"] = percentile_ns(values, 99)
    result["deadline_miss_pct"] = Fraction(100 * sum(r["deadline_miss"] for r in rows), len(rows))
    return result


def aggregate_runs(runs, queues, *, formal):
    """Arithmetic mean of run statistics; no pooled frames or event timelines.

    Each queue entry has K/run_id and its already computed run queue metrics.
    Formal callers must supply exactly K=1..7, run01..run05, once each.
    """
    keys = [(r["K"], r["run_id"]) for r in runs]
    qkeys = [(r["K"], r["run_id"]) for r in queues]
    if len(set(keys)) != len(keys) or len(set(qkeys)) != len(qkeys) or set(keys) != set(qkeys):
        raise ValueError("duplicate/mismatched run identities")
    if formal and set(keys) != {(k, f"run{r:02d}") for k in range(1, 8) for r in range(1, 6)}:
        raise ValueError("formal aggregation requires exactly K=1..7 x five runs")
    motivations, queue_rows = [], []
    for k in sorted({r["K"] for r in runs}):
        group = [r for r in runs if r["K"] == k]
        qgroup = [q for q in queues if q["K"] == k]
        row = {"K": k, "offered_load_fps": k * 30, "run_count": len(group)}
        for field in PER_RUN_FIELDS[2:]:
            key = field[:-3] + "_ns" if field.endswith("_ms") else field
            row[key] = mean([r[key] for r in group])
        motivations.append(row)
        queue_rows.append({"K": k, "run_count": len(group), **{
            field: mean([q[field.removesuffix("_mean")] for q in qgroup])
            for field in QUEUE_FIELDS[2:]}})
    return motivations, queue_rows


def write_csv(path, fields, rows):
    """Only here are ns durations/statistics converted to displayed milliseconds."""
    with path.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            output = {}
            for field in fields:
                if field.endswith("_ms"):
                    output[field] = float(Fraction(row[field[:-3] + "_ns"], 1_000_000))
                else:
                    value = row[field]
                    output[field] = float(value) if isinstance(value, Fraction) else value
            writer.writerow(output)
