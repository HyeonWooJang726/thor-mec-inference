"""Worker-private tuple records; post-join output only, no runtime hardware imports."""
import csv
import json
from pathlib import Path

FIELDS = (
    'stream_id', 'frame_id', 'terminal_state',
    't_worker_pop', 't_lock_request', 't_lock_acquired', 't_expiry_check_done',
    't_pre_infer', 't_infer_return', 't_bookkeeping_begin', 't_bookkeeping_end',
    't_tensor_release_begin', 't_tensor_release_end',
    'service_start', 'service_end', 'gpu_exec_duration_ms', 'gpu_event_status',
    't_gpu_elapsed_query_begin', 't_gpu_elapsed_query_end',
)


def write_after_join(directory, workers):
    """Call only when every worker has stopped; fail rather than overwrite output."""
    directory = Path(directory)
    with (directory / 'per_frame_phase_timestamps.csv').open('x', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(('worker_id',) + FIELDS)
        for worker in workers:
            for row in worker.phase_records:
                writer.writerow((worker.worker_id,) + row)
    # All worker records are immutable scalar tuples; no tensors/job references retained.
    report = []
    for worker in workers:
        e = worker.phase_events
        report.append(dict(worker_id=worker.worker_id, records=len(worker.phase_records),
                           create_code=e.create_code, record_calls=e.record_calls,
                           record_errors=e.record_errors, elapsed_calls=e.elapsed_calls,
                           storage='worker-private list of scalar tuples',
                           GPU_hardware_validation='REQUIRED_IN_FIRST_APPROVED_RUN'))
    with (directory / 'phase_instrumentation_manifest.json').open('x') as f:
        json.dump(report, f, indent=2)
