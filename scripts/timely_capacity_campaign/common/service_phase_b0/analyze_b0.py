"""Read-only raw inputs; new B0 analysis artifacts only. Never starts a workload."""
import csv
import gzip
import json
import math
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'results/timely_capacity_campaign/pruning_path_audit/service_phase_validation/b0_01'
RUN_ID='SPI_B0_S240_L176E64_ON_P01'
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'service_phase_v1'))
from analyze_phases import metrics,event_validation,startup_bins


def read(path):
    with (gzip.open(path,'rt') if path.name.endswith('.gz') else path.open()) as f:return list(csv.DictReader(f))
def quant(values):
    a=np.array([float(v) for v in values if v not in ('',None)],float);a=a[np.isfinite(a)]
    return dict(n=len(a),mean=float(a.mean()) if len(a) else None,**{f'p{k}':float(np.percentile(a,k)) if len(a) else None for k in (50,95,99)})
def dump(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,allow_nan=False)


def analyze():
    d=OUT/RUN_ID;dest=OUT/'analysis01';dest.mkdir(exist_ok=False)
    manifest=json.loads((d/'manifest.json').read_text());summary=json.loads((d/'summary.json').read_text())
    raw=read(d/'per_frame.csv.gz');ph=read(d/'per_frame_phase_timestamps.csv');wi=json.loads((d/'phase_instrumentation_manifest.json').read_text())
    records=[metrics(r) for r in ph];pd.DataFrame(records).to_csv(dest/'per_frame_phase_metrics.csv',index=False)
    active=[r for r in raw if r.get('phase')=='active'];local=[r for r in active if r['placement']=='LOCAL']
    completed=[r for r in local if r['completion_timestamp_ns']];ex=[r for r in ph if r['terminal_state']=='COMPLETED']
    ids=lambda rows:[(int(r['stream_id']),int(r['frame_id'])) for r in rows]
    lookup={key:r for key,r in zip(ids(local),local)}
    phase_duplicates=len(ph)-len(set(ids(ph)));source_duplicates=len(active)-len(set(ids(active)))
    missing_phase=len(set(ids(local))-set(ids(ph)));extra_phase=len(set(ids(ph))-set(ids(local)))
    mismatch=0;invalid_host_order=0
    for r in ph:
        match=lookup.get((int(r['stream_id']),int(r['frame_id'])))
        if match is None:mismatch+=1;continue
        mismatch+=r['terminal_state']!=match['terminal_state'] or r['worker_id']!=match['worker_id']
        if r['terminal_state']=='COMPLETED':
            mismatch+=r['service_start']!=match['inference_start_timestamp_ns'] or r['service_end']!=match['completion_timestamp_ns']
            keys=['t_worker_pop','t_lock_request','t_lock_acquired','service_start','t_expiry_check_done','t_pre_infer','t_infer_return','service_end','t_bookkeeping_begin','t_bookkeeping_end','t_gpu_elapsed_query_begin','t_gpu_elapsed_query_end']
        else:keys=['t_worker_pop','t_lock_request','t_lock_acquired','t_expiry_check_done','t_tensor_release_begin','t_tensor_release_end']
        invalid_host_order+=any(int(r[b])<int(r[a]) for a,b in zip(keys,keys[1:]))
    ev=event_validation(ph);gpu=[float(r['gpu_exec_duration_ms']) for r in ex if r['gpu_exec_duration_ms']!='']
    pairs=[]
    for worker in wi:
        w=str(worker['worker_id']);n=sum(r['worker_id']==w for r in ex);warm=sum(r['phase']=='warmup' and r['worker_id']==w for r in raw)
        pairs.append(dict(**worker,expected_record_calls=2*(n+warm),expected_elapsed_calls=n,
                          pair_count_mismatch=worker['record_calls']!=2*(n+warm) or worker['elapsed_calls']!=n))
    bounds=[r for r in records if r['terminal_state']=='COMPLETED' and r['gpu_exec_duration_ms'] is not None and math.isfinite(r['gpu_exec_duration_ms']) and r['gpu_exec_duration_ms']>r['infer_call_duration_ms']]
    validity=dict(**ev,sample_count=len(gpu),NaN_count=sum(math.isnan(x) for x in gpu),infinite_count=sum(math.isinf(x) for x in gpu),negative_count=sum(x<0 for x in gpu),zero_count=sum(x==0 for x in gpu),
                  gpu_span_exceeds_enclosing_host_call_count=len(bounds),implausibly_large_rule='GPU stream event span > enclosing host infer duration; raw excess preserved; no arbitrary ms cutoff',
                  event_pair_count_mismatch=sum(r['pair_count_mismatch'] for r in pairs),event_record_errors=sum(r['record_errors'] for r in pairs),
                  elapsed_query_error_count=sum(r['gpu_event_status']=='ELAPSED_FAILED' for r in ph),worker_records=pairs,
                  pairing_scope='Private reusable pair, synchronous owner-thread reuse plus call/count/row consistency; no separate per-event sequence ID logged')
    integrity=dict(integrity_status=summary['integrity_status'],frequency_restore_ok=manifest['frequency_restore_ok'],
                   source_missing=14400-len(set(ids(active))),source_duplicate=source_duplicates,
                   missing_frames=summary['missing_frames'],phase_missing=missing_phase,phase_extra=extra_phase,phase_duplicate=phase_duplicates,
                   row_or_legacy_timestamp_mismatch=mismatch,invalid_host_order=invalid_host_order,terminal_accounting=summary['terminal_accounting_status'],
                   true_unfinished_after_drain=summary['true_unfinished_after_drain'])
    stat=[]
    for name in ['existing_service_duration_ms','infer_call_duration_ms','gpu_exec_duration_ms','host_wakeup_delay_ms','lock_wait_duration_ms','bookkeeping_duration_ms','tensor_release_duration_ms','accounting_locked_duration_ms','gpu_elapsed_query_duration_ms']:
        stat.append(dict(metric=name,**quant([r.get(name) for r in records])))
    pd.DataFrame(stat).to_csv(dest/'service_phase_summary.csv',index=False)
    bins=startup_bins(ph,raw,manifest['active_start_ns']);pd.DataFrame(bins).to_csv(dest/'startup_100ms_timeseries.csv',index=False)
    duration=(manifest['active_end_ns']-manifest['active_start_ns'])/1e9
    primary=dict(run_id=RUN_ID,local_raw_completed_FPS=summary['local_active_completed_FPS'],Local_timely_ratio=summary['path_timely']['LOCAL']['timely_ratio'],Edge_timely_ratio=summary['path_timely']['EDGE']['timely_ratio'],
                 local_queue_p95_ms=summary['local_queue_ms']['p95'],local_queue_p99_ms=summary['local_queue_ms']['p99'],
                 active_concurrency_mean=summary['active_concurrency_mean'],OC3_delta=summary['OC3_delta'],temperature=summary['temperature'],actual_freq_mean_MHz=summary['actual_freq_mean_MHz'],
                 local_assigned_FPS=len(local)/duration,local_expired_FPS=sum(r['terminal_state']=='EXPIRED_DROP' for r in local)/duration)
    service_mean=next(r['mean'] for r in stat if r['metric']=='existing_service_duration_ms')
    delta=service_mean-9.16 if service_mean is not None else None
    invalid=(summary['integrity_status']!='VALID' or not manifest['frequency_restore_ok'] or ev['status']!='PASS' or validity['event_pair_count_mismatch'] or validity['event_record_errors'] or
             missing_phase or extra_phase or phase_duplicates or mismatch or invalid_host_order or source_duplicates or integrity['source_missing'] or summary['missing_frames'] or summary['terminal_accounting_status']!='PASS' or summary['true_unfinished_after_drain'])
    verdict='B0_INSTRUMENTATION_INVALID' if invalid else 'B0_INSTRUMENTATION_SUSPECT' if bounds or delta is None or abs(delta)>.2 else 'B0_INSTRUMENTATION_VALID'
    report=dict(verdict=verdict,integrity=integrity,CUDA_event_validity=validity,metrics=primary,phases=stat,
                historical_approx_reference_service_ms=9.16,service_mean_delta_vs_approx_reference_ms=delta,
                interpretation='0.2ms criterion is descriptive historical comparison, not isolated overhead causality. host_wakeup is a broad residual, not OS/GIL time.',final_state='B0_COMPLETE_WAITING_FOR_REVIEW')
    dump(dest/'B0_VALIDATION.json',report)
    pd.DataFrame([dict(**primary,verdict=verdict)]).to_csv(dest/'per_run_summary.csv',index=False)
    historical=[]
    for p in sorted((ROOT/'results/timely_capacity_campaign/block_b_split/v2_1/E_MAX_72').glob('TCCBV2_E72_R*_S240_L176E64_P01/summary.json')):
        h=json.loads(p.read_text());historical.append(dict(run_id=h['run_id'],service_mean_ms=h['local_service_ms']['mean'],local_queue_p95_ms=h['local_queue_ms']['p95'],local_timely_ratio=h['path_timely']['LOCAL']['timely_ratio'],Edge_timely_ratio=h['path_timely']['EDGE']['timely_ratio']))
    pd.DataFrame(historical).to_csv(dest/'historical_healthy_condition_references.csv',index=False)
    panels=[('gpu_exec_duration_ms_mean','GPU stream span (ms)'),('infer_call_duration_ms_mean','Infer call (ms)'),('host_wakeup_delay_ms_mean','Host residual (ms)'),('local_completed_count','Local completed /100ms'),('local_expired_count','Local expired /100ms'),('local_late_count','Local late /100ms'),('host_active_concurrency_mean','Host concurrency')]
    fig,axes=plt.subplots(len(panels),1,figsize=(10,14),sharex=True)
    for ax,(key,label) in zip(axes,panels):ax.plot(np.arange(30)*.1,[b[key] for b in bins]);ax.set_ylabel(label);ax.grid(alpha=.2)
    axes[-1].set_xlabel('Active time (s), 100ms bins');fig.suptitle('B0 startup — observed durations and event counts');fig.tight_layout();fig.savefig(dest/'startup_B0_100ms.png',dpi=150);plt.close(fig)
    text=['# '+verdict,'','B0 only. B1/B2/recovery/Block A were not executed.','','|Metric|n|mean|p50|p95|p99|','|---|---:|---:|---:|---:|---:|']
    for row in stat:text.append('|'+str(row['metric'])+'|'+'|'.join('N/A' if row[k] is None else str(round(row[k],6)) for k in ['n','mean','p50','p95','p99'])+'|')
    text+=['','```json',json.dumps(dict(metrics=primary,integrity=integrity,CUDA_event_validity=validity),indent=2),'```','',report['interpretation'],'','B0_COMPLETE_WAITING_FOR_REVIEW']
    with (dest/'VALIDATION_SUMMARY.md').open('x') as f:f.write('\n'.join(text)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':analyze()
