"""Preallocated recording storage; no CUDA imports. Export only after worker join."""
import csv
import json
from pathlib import Path
import numpy as np

FIELDS=('stream_id','frame_id','terminal_state','t_worker_pop','t_lock_request','t_lock_acquired','t_expiry_check_done',
        't_pre_infer','t_infer_return','t_bookkeeping_begin','t_bookkeeping_end','t_tensor_release_begin','t_tensor_release_end',
        'service_start','service_end','gpu_exec_duration_ms','gpu_event_status','t_gpu_elapsed_query_begin','t_gpu_elapsed_query_end')
INT_FIELDS=tuple(k for k in FIELDS if k!='gpu_exec_duration_ms')
STATUS=('NOT_EXECUTED','OK','ZERO','CREATE_FAILED','RECORD_FAILED','ELAPSED_FAILED','INVALID_ELAPSED')


class PhaseBuffer:
    def __init__(self,capacity):
        self.capacity=capacity;self.count=0
        self.integers=np.empty((len(INT_FIELDS),capacity),dtype=np.int64);self.integers.fill(-1)
        self.gpu=np.empty(capacity,dtype=np.float64);self.gpu.fill(np.nan)
        # All column views are allocated once, not per record.
        for i,key in enumerate(INT_FIELDS):setattr(self,'c_'+key,self.integers[i])
    def __len__(self):return self.count
    def rows(self):
        # POST-JOIN ONLY: construct row containers here, not in the worker.
        for i in range(self.count):
            row=[]
            for key in FIELDS:
                if key=='gpu_exec_duration_ms':
                    value=float(self.gpu[i]) if self.c_terminal_state[i]==1 else None
                else:
                    value=int(getattr(self,'c_'+key)[i])
                    if key=='terminal_state':value='COMPLETED' if value==1 else 'EXPIRED_DROP'
                    elif key=='gpu_event_status':value=STATUS[value]
                    elif value==-1:value=None
                row.append(value)
            yield tuple(row)


class FrameLedger:
    """Fixed reference slots, same original record visibility under existing lock."""
    def __init__(self,capacity):self.items=[None]*capacity;self.count=0
    def record(self,row):
        if self.count==len(self.items):raise RuntimeError('Frame ledger overflow')
        self.items[self.count]=row;self.count+=1
    def __len__(self):return self.count
    def __iter__(self):
        for i in range(self.count):yield self.items[i]


def preallocate_source_rows(k,duration):
    # Preserve original row keys and values; no extra tensor references or changed tensor lifetime.
    return [[dict(phase='active',stream_id=s,frame_id=f,logical_arrival_ns=0,admitted=0,
                  admission_timestamp_ns=0,admission_observed_ns=0,enqueue_timestamp_ns='')
             for s in range(k)] for f in range(int(duration*30))]


def write_after_join(directory,workers):
    directory=Path(directory)
    with (directory/'per_frame_phase_timestamps.csv').open('x',newline='') as f:
        writer=csv.writer(f);writer.writerow(('worker_id',)+FIELDS)
        for worker in workers:
            for row in worker.phase_records.rows():writer.writerow((worker.worker_id,)+row)
    report=[]
    for worker in workers:
        e=worker.phase_events;b=worker.phase_records
        report.append(dict(worker_id=worker.worker_id,records=b.count,capacity=b.capacity,
            create_code=e.create_code,record_calls=e.record_calls,record_errors=e.record_errors,elapsed_calls=e.elapsed_calls,
            storage='worker-private preallocated int64/float64 arrays; no hot-path record containers',
            GPU_hardware_validation='REQUIRED_FIRST_APPROVED_V22_RUN'))
    with (directory/'phase_instrumentation_manifest.json').open('x') as f:json.dump(report,f,indent=2)
