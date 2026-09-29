"""Post-run B1/B0 log analysis only. Never imports a GPU runtime or starts workloads."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
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
from b1_common import ROOT, HERE, OUT, B0_ROOT, B0_RUN, PLAN, load_plan, sha
from analyze_phases import metrics, event_validation, startup_bins
sys.path.insert(0, str(HERE.parent))
import campaign_config as cfg

PHASES = ('existing_service_duration_ms','gpu_exec_duration_ms','host_wakeup_delay_ms',
          'infer_call_duration_ms','lock_wait_duration_ms','bookkeeping_duration_ms',
          'tensor_release_duration_ms','gpu_elapsed_query_duration_ms')


def read(path):
    with (gzip.open(path,'rt') if str(path).endswith('.gz') else Path(path).open()) as f:
        return list(csv.DictReader(f))


def number(r,k):
    v=r.get(k)
    return int(v) if v not in ('',None) else None


def quant(values):
    a=np.array([float(v) for v in values if v not in ('',None)],float)
    finite=a[np.isfinite(a)]
    return dict(n=len(a),finite_n=len(finite),nonfinite_n=len(a)-len(finite),
        **{k:(float(fn(finite)) if len(finite) else None) for k,fn in
           [('mean',np.mean),('p50',lambda x:np.percentile(x,50)),('p95',lambda x:np.percentile(x,95)),('p99',lambda x:np.percentile(x,99))]})


def ids(rows):return [(int(r['stream_id']),int(r['frame_id'])) for r in rows]


def validate_run(c,m,s,raw,ph,wi):
    errors=[]
    def require(ok,reason):
        if not ok:errors.append(reason)
    active=[r for r in raw if r.get('phase')=='active']
    local=[r for r in active if r.get('placement')=='LOCAL']
    expected={}
    for f in range(int(c['seconds']*30)):
        for k in range(8):
            row=dict(stream_id=k,frame_id=f,logical_arrival_ns=m['active_start_ns']+f*10**9//30)
            cfg.decorate(row,m['active_start_ns'],c);expected[k,f]=row
    require(set(ids(active))==set(expected),'source missing/extra IDs')
    require(len(ids(active))==len(set(ids(active))),'duplicate source IDs')
    for r in active:
        e=expected.get((int(r['stream_id']),int(r['frame_id'])))
        if e is None:continue
        require(r['placement']==e['placement'] and int(r['admitted'])==e['admitted'] and number(r,'logical_arrival_ns')==e['logical_arrival_ns'],'source arrival/admission/placement mismatch')
    require(set(ids(local))==set(ids(ph)),'phase/Local IDs mismatch')
    require(len(ids(ph))==len(set(ids(ph))),'duplicate phase IDs')
    lookup=dict(zip(ids(local),local));completed=expired=unfinished=0
    for r in local:
        end=number(r,'completion_timestamp_ns');drop=number(r,'expired_drop_ns')
        good_c=end is not None and drop is None and r['terminal_state']=='COMPLETED'
        good_x=end is None and drop is not None and r['terminal_state']=='EXPIRED_DROP'
        completed+=good_c;expired+=good_x;unfinished+=not(good_c or good_x)
        require(not (end is not None and drop is not None),'conflicting terminal states')
        if good_x:
            require(drop>=number(r,'absolute_deadline_ns') and number(r,'inference_start_timestamp_ns') is None,'early expiry or expired inference')
        if good_c and c.get('pruning_enabled',True):
            require(number(r,'expiry_check_ns') is not None and number(r,'expiry_check_ns')<number(r,'absolute_deadline_ns'),'ON executed expired waiting work')
    require(unfinished==0,'true unfinished Local work')
    if c.get('pruning_enabled') is False:require(expired==0,'OFF expired work')
    for r in ph:
        rawrow=lookup.get((int(r['stream_id']),int(r['frame_id'])))
        if rawrow is None:continue
        require(r['worker_id']==rawrow['worker_id'] and r['terminal_state']==rawrow['terminal_state'],'phase terminal/worker mismatch')
        if r['terminal_state']=='COMPLETED':
            require(number(r,'service_start')==number(rawrow,'inference_start_timestamp_ns') and number(r,'service_end')==number(rawrow,'completion_timestamp_ns'),'legacy timestamp mismatch')
            keys=['t_worker_pop','t_lock_request','t_lock_acquired','service_start','t_expiry_check_done','t_pre_infer','t_infer_return','service_end','t_bookkeeping_begin','t_bookkeeping_end','t_gpu_elapsed_query_begin','t_gpu_elapsed_query_end']
        else:keys=['t_worker_pop','t_lock_request','t_lock_acquired','t_expiry_check_done','t_tensor_release_begin','t_tensor_release_end']
        values=[number(r,k) for k in keys]
        require(all(x is not None for x in values) and all(a<=b for a,b in zip(values,values[1:])),'invalid host timestamp order')
    ev=event_validation(ph);require(ev['status']=='PASS','invalid CUDA event samples')
    require(len(wi)==2 and {int(w['worker_id']) for w in wi}=={0,1},'missing/duplicate worker instrumentation')
    for w in wi:
        worker=str(w['worker_id']);n=sum(r['worker_id']==worker and r['terminal_state']=='COMPLETED' for r in ph)
        warm=sum(r.get('phase')=='warmup' and r['worker_id']==worker for r in raw)
        require(w['create_code']==0 and w['record_errors']==0,'CUDA create/record error')
        require(w['record_calls']==2*(warm+n) and w['elapsed_calls']==n,'CUDA event pair/query count mismatch')
    rows=[metrics(r) for r in ph]
    excess=sum(r['gpu_exec_duration_ms'] is not None and r['infer_call_duration_ms'] is not None and r['gpu_exec_duration_ms']>r['infer_call_duration_ms'] for r in rows)
    require(excess==0,'GPU stream span exceeds host infer interval')
    require(s['integrity_status']=='VALID' and s['terminal_accounting_status']=='PASS','saved integrity/terminal failure')
    require(m['frequency_restore_ok'] is True and s.get('frequency_restore_ok') is True,'frequency restoration failed')
    require(s['missing_frames']==0 and s['true_unfinished_after_drain']==0,'saved missing/unfinished work')
    require(m.get('requested_freq_MHz')==1575,'requested frequency mismatch')
    pin=m.get('pin_readback_Hz',{})
    require(pin.get('min_freq')==1575000000 and pin.get('max_freq')==1575000000,'pin readback mismatch')
    require(not m.get('queue_cap_saturation') and not m.get('queue_overflow'),'queue saturation/overflow')
    require(m.get('pruning_enabled',c.get('pruning_enabled'))==c.get('pruning_enabled'),'pruning flag mismatch')
    if c['edge_r']==0:
        require(m.get('edge_usage')=='NOT_USED','Edge unexpectedly active')
        require(not any(r['placement']=='EDGE' for r in active),'unexpected Edge placement')
    gpu=[float(r['gpu_exec_duration_ms']) for r in ph if r['terminal_state']=='COMPLETED' and r.get('gpu_exec_duration_ms') not in ('',None)]
    return dict(status='PASS' if not errors else 'FAIL',errors=sorted(set(errors)),
        error_count=len(errors),expected_source=len(expected),actual_source=len(active),
        assigned_local=len(local),completed_local=completed,expired_local=expired,
        true_unfinished_local=unfinished,phase_rows=len(ph),event_validation=ev,
        gpu_span_exceeds_host_call_count=excess,CUDA_event_sample_count=len(gpu),
        CUDA_NaN_count=sum(math.isnan(x) for x in gpu),CUDA_infinite_count=sum(math.isinf(x) for x in gpu),
        CUDA_negative_count=sum(x<0 for x in gpu),CUDA_zero_count=sum(x==0 for x in gpu),
        CUDA_elapsed_query_errors=sum(r.get('gpu_event_status')=='ELAPSED_FAILED' for r in ph))


def interval_index(intervals):
    merged=[]
    for a,b in sorted(intervals):
        if b<=a:raise ValueError('Nonpositive host infer interval')
        if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
        else:merged.append([a,b])
    starts=[a for a,b in merged];ends=[b for a,b in merged]
    prefix=[0]
    for a,b in merged:prefix.append(prefix[-1]+b-a)
    return starts,ends,prefix


def overlap_ns(a,b,index):
    starts,ends,prefix=index
    left=bisect_right(ends,a);right=bisect_left(starts,b)
    if left>=right:return 0
    return prefix[right]-prefix[left]-max(0,a-starts[left])-max(0,ends[right-1]-b)


def overlap_rows(ph,run_id):
    executed=[metrics(r) for r in ph if r['terminal_state']=='COMPLETED']
    workers={str(r['worker_id']) for r in executed}
    indexes={w:interval_index([(int(r['t_pre_infer']),int(r['t_infer_return'])) for r in executed if str(r['worker_id'])!=w]) for w in workers}
    out=[]
    for r in executed:
        a,b=int(r['t_pre_infer']),int(r['t_infer_return']);ov=overlap_ns(a,b,indexes[str(r['worker_id'])])
        assert 0<=ov<=b-a
        group='non-overlap' if ov==0 else 'full-overlap' if ov==b-a else 'partial-overlap'
        out.append(dict(r,run_id=run_id,overlap_ns=ov,host_infer_ns=b-a,overlap_fraction=ov/(b-a),overlap_group=group))
    return out


def summarize_overlap(rows,run_id):
    out=[]
    for group in ('non-overlap','full-overlap','partial-overlap'):
        selected=[r for r in rows if r['overlap_group']==group]
        for key in PHASES[:3]:
            out.append(dict(run_id=run_id,group=group,metric=key,**quant([r[key] for r in selected])))
    return out


def load_run(directory,condition):
    m=json.loads((directory/'manifest.json').read_text());s=json.loads((directory/'summary.json').read_text())
    raw=read(directory/'per_frame.csv.gz');ph=read(directory/'per_frame_phase_timestamps.csv')
    wi=json.loads((directory/'phase_instrumentation_manifest.json').read_text())
    valid=validate_run(condition,m,s,raw,ph,wi)
    return m,s,raw,ph,valid


def summarize_run(c,m,s,raw,ph):
    active=[r for r in raw if r.get('phase')=='active' and r.get('placement')=='LOCAL']
    t0,t1=m['active_start_ns'],m['active_end_ns'];seconds=(t1-t0)/1e9
    completed=[r for r in active if number(r,'completion_timestamp_ns') is not None]
    timely=[r for r in completed if number(r,'completion_timestamp_ns')<=number(r,'absolute_deadline_ns')]
    expired=[r for r in active if r['terminal_state']=='EXPIRED_DROP']
    phases=[metrics(r) for r in ph]
    phase_stats=[dict(run_id=c['run_id'],mode='ON' if c.get('pruning_enabled',True) else 'OFF',repeat=c['repeat'],metric=k,**quant([r[k] for r in phases])) for k in PHASES]
    q=quant([(number(r,'inference_start_timestamp_ns')-number(r,'ready_timestamp_ns'))/1e6 for r in completed])
    pending_q=quant([((number(r,'inference_start_timestamp_ns') or number(r,'expired_drop_ns'))-number(r,'ready_timestamp_ns'))/1e6 for r in active if number(r,'ready_timestamp_ns') is not None and (number(r,'inference_start_timestamp_ns') or number(r,'expired_drop_ns')) is not None])
    concurrency=sum(max(0,min(t1,number(r,'completion_timestamp_ns'))-max(t0,number(r,'inference_start_timestamp_ns'))) for r in completed)/(t1-t0)
    result=dict(run_id=c['run_id'],mode='ON' if c.get('pruning_enabled',True) else 'OFF',repeat=c['repeat'],
        local_assigned_FPS=len(active)/seconds,raw_completed_FPS=sum(t0<=number(r,'completion_timestamp_ns')<t1 for r in completed)/seconds,
        completed_cohort_FPS=len(completed)/seconds,timely_FPS=len(timely)/seconds,timely_ratio=len(timely)/len(active) if active else None,
        expired_FPS=len(expired)/seconds,late_completed_FPS=(len(completed)-len(timely))/seconds,
        queue_p95_ms=q['p95'],queue_p99_ms=q['p99'],all_terminal_wait_p95_ms=pending_q['p95'],
        active_concurrency_mean=concurrency,OC3_delta=s['OC3_delta'],temperature_mean_C=s['temperature'],
        actual_GPU_frequency_MHz=s['actual_freq_mean_MHz'],actual_clock_non_target_fraction=s.get('actual_clock_non_target_fraction'),
        temperature_start=m.get('run_start_diagnostics',{}).get('GPU_temperature_C'),temperature_end=m.get('run_end_diagnostics',{}).get('GPU_temperature_C'),
        integrity_status=s['integrity_status'],terminal_accounting=s['terminal_accounting_status'],frequency_restore_ok=m['frequency_restore_ok'],
        true_unfinished_after_drain=s['true_unfinished_after_drain'])
    for rec in phase_stats:
        for k in ('n','mean','p50','p95','p99'):result[rec['metric']+'_'+k]=rec[k]
    bins=startup_bins(ph,raw,t0)
    for i,b in enumerate(bins):
        b.update(run_id=c['run_id'],mode=result['mode'],repeat=c['repeat'],start_seconds=i/10)
        vals=[r['existing_service_duration_ms'] for r in phases if r['terminal_state']=='COMPLETED' and b['start_ns']<=int(r['service_start'])<b['end_ns']]
        b['service_mean_ms']=quant(vals)['mean']
    return result,phase_stats,bins


def write_csv(path,rows):
    pd.DataFrame(rows).to_csv(path,index=False)


def write_json(path,obj):
    with path.open('x') as f:json.dump(obj,f,indent=2,allow_nan=False)


def paired_description(runs,overlap):
    lines=['# B1 interpretation','',
        'Descriptive observations only; no significance test, no causal classification.',
        'Raw completed FPS uses completions inside active time; timely/late/expired use active-admitted cohorts including drain.',
        'Local-only 200 uses aligned admission; historical hybrid L200+E40 uses different Local IDs/burst shape. B1/B0 difference does not establish hybrid coupling.','']
    by={(r['mode'],r['repeat']):r for r in runs}
    for rep in (1,2):
        a,b=by['OFF',rep],by['ON',rep]
        lines.append(f"R{rep} ON−OFF: completed={b['raw_completed_FPS']-a['raw_completed_FPS']:.6f} FPS; timely={b['timely_FPS']-a['timely_FPS']:.6f} FPS; queue p95={b['queue_p95_ms']-a['queue_p95_ms']:.6f} ms.")
    lines+=['','Axis A: report each OFF completion deficit from assigned 200, late/expired counts and service distributions. No new binary slowdown threshold.',
            'Axis B: compare full-overlap GPU span and host residual to B0, with n and partial/non-overlap groups retained. Positive differences alone are not statistical significance.','',
            '|Axis A / axis B|GPU stream span increase|Host residual increase with similar GPU span|',
            '|---|---|---|',
            '|OFF also degraded|Common runtime/overlap candidates; not pruning-specific evidence|Common host/runtime candidate; do not label actual GPU saturation|',
            '|Only ON degraded|Pruning-path candidate; no causal mechanism established|Pruning host-path candidate; no causal mechanism established|','',
            'Both components increasing or mixed/empty groups remain MIXED/UNRESOLVED. No arbitrary “similar” or “significant” cutoff is introduced.','']
    for r in runs:
        lines.append(f"{r['run_id']}: assigned−active completed={200-r['raw_completed_FPS']:.6f} FPS; cohort completions={r['completed_cohort_FPS']:.6f} FPS; expired={r['expired_FPS']:.6f} FPS. Active-end work can explain a small active completion deficit.")
    lookup={(x['run_id'],x['metric']):x for x in overlap if x['group']=='full-overlap'}
    b0id=B0_RUN.name
    lines+=['','Full-overlap conditioned mean differences relative to B0 (not GPU-kernel overlap):']
    for r in runs:
        pieces=[]
        for metric in PHASES[:3]:
            x,y=lookup[r['run_id'],metric],lookup[b0id,metric]
            delta=x['mean']-y['mean'] if x['mean'] is not None and y['mean'] is not None else None
            pieces.append(f"{metric}: n={x['n']}, delta_ms={delta if delta is not None else 'N/A'}")
        lines.append(r['run_id']+': '+'; '.join(pieces))
    lines+=['','Startup 100ms rows preserve all first-3s observations. They describe temporal sequence, not an onset cause.','B1_COMPLETE_WAITING_FOR_REVIEW; no B2/recovery/Block A execution.']
    return '\n'.join(lines)+'\n'


def plots(dest,runs,overlap,startup):
    labels=[r['mode']+'-R'+str(r['repeat']) for r in runs]
    fig,ax=plt.subplots(figsize=(8,4))
    for key in ('raw_completed_FPS','timely_FPS','expired_FPS','late_completed_FPS'):
        ax.plot(labels,[r[key] for r in runs],marker='o',label=key)
    ax.set_ylabel('Frames/s');ax.legend();fig.tight_layout();fig.savefig(dest/'OFF_vs_ON_throughput.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4))
    ax.bar(labels,[r['gpu_exec_duration_ms_mean'] for r in runs],label='GPU stream span')
    ax.bar(labels,[r['host_wakeup_delay_ms_mean'] for r in runs],bottom=[r['gpu_exec_duration_ms_mean'] for r in runs],label='Host residual')
    ax.set_ylabel('Mean ms');ax.legend();fig.tight_layout();fig.savefig(dest/'OFF_vs_ON_gpu_host_decomposition.png',dpi=150);plt.close(fig)
    frame=pd.DataFrame(overlap);fig,ax=plt.subplots(figsize=(10,4))
    for group in ('non-overlap','full-overlap','partial-overlap'):
        r=frame[(frame['group']==group)&(frame.metric=='gpu_exec_duration_ms')]
        ax.plot(r.run_id,[np.nan if v is None else v for v in r['mean']],marker='o',label=group)
    ax.tick_params(axis='x',rotation=20);ax.set_ylabel('GPU stream span mean (ms)');ax.legend();fig.tight_layout();fig.savefig(dest/'overlap_conditioned_gpu_span.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(8,1,figsize=(10,17),sharex=True)
    keys=['gpu_exec_duration_ms_mean','host_wakeup_delay_ms_mean','service_mean_ms','local_completed_count','local_expired_count','local_late_count','host_active_concurrency_mean','conceptual_local_waiting_queue_mean']
    for ax,key in zip(axes,keys):
        for r,label in zip(runs,labels):
            rows=[x for x in startup if x['run_id']==r['run_id']]
            ax.plot([x['start_seconds'] for x in rows],[np.nan if x[key] is None else x[key] for x in rows],label=label)
        ax.set_ylabel(key,fontsize=8);ax.grid(alpha=.2)
    axes[0].legend();axes[-1].set_xlabel('Active seconds (100ms windows)');fig.tight_layout();fig.savefig(dest/'startup_100ms_all_runs.png',dpi=150);plt.close(fig)


def analyze(destination):
    plan=load_plan()
    if destination.exists():raise RuntimeError('Refuse existing analysis output')
    for c in plan['order']:
        for name in ('manifest.json','summary.json','per_frame.csv.gz','per_frame_phase_timestamps.csv','phase_instrumentation_manifest.json'):
            if not (OUT/c['run_id']/name).is_file():raise RuntimeError('B1 run incomplete/missing: '+c['run_id']+'/'+name)
    destination.mkdir(parents=True)
    stats=[];phases=[];startup=[];ov_summary=[];checks={};provenance={}
    b0c=json.loads((B0_ROOT/'plan.json').read_text())['order'][0]
    allconds=[(B0_RUN,dict(b0c,pruning_enabled=True))]+[(OUT/c['run_id'],c) for c in plan['order']]
    for directory,c in allconds:
        for p in directory.iterdir():
            if p.is_file():provenance[str(p.relative_to(ROOT))]=sha(p)
        m,s,raw,ph,check=load_run(directory,c);checks[c['run_id']]=check
        ov=overlap_rows(ph,c['run_id']);ov_summary+=summarize_overlap(ov,c['run_id'])
        write_csv(destination/(c['run_id']+'_overlap_frames.csv'),ov)
        if directory!=B0_RUN:
            r,p,b=summarize_run(c,m,s,raw,ph);stats.append(r);phases+=p;startup+=b
            write_csv(destination/(c['run_id']+'_phase_metrics.csv'),[metrics(x) for x in ph])
    write_csv(destination/'per_run_summary.csv',stats);write_csv(destination/'phase_metrics_by_run.csv',phases)
    write_csv(destination/'overlap_conditioned_metrics.csv',ov_summary);write_csv(destination/'startup_100ms_timeseries.csv',startup)
    # Aggregate summaries are across two repeat values, never pooled frames.
    summary=[]
    for mode in ('OFF','ON'):
        selected=[r for r in stats if r['mode']==mode]
        for key in selected[0]:
            values=[r[key] for r in selected]
            if all(isinstance(v,(float,int)) and not isinstance(v,bool) for v in values):
                summary.append(dict(mode=mode,metric=key,repeat1=values[0],repeat2=values[1],mean=float(np.mean(values)),sample_SD=float(np.std(values,ddof=1)),min=min(values),max=max(values)))
    write_csv(destination/'mode_statistics.csv',summary)
    write_json(destination/'integrity_and_event_validation.json',checks)
    valid=all(x['status']=='PASS' for x in checks.values())
    interpretation=paired_description(stats,ov_summary) if valid else '# INCONCLUSIVE\nIntegrity/event checks failed; preserve all rows and inspect integrity_and_event_validation.json. No causal interpretation.\n'
    with (destination/'B1_INTERPRETATION.md').open('x') as f:f.write(interpretation)
    for name in ('cuda_event_scope.md','isolated_reference_check.md'):
        with (destination/name).open('x') as f:f.write((OUT/name).read_text())
    # Non-overlap GPU p50 is reported, but subtracting Gate-0 host mean is NOT_COMPARABLE.
    iso=pd.read_csv(ROOT/'results/gate0_model_ladder/model_capacity_predictions.csv')
    iso_value=float(iso[(iso.model=='M1')&(iso.frequency_MHz==1575)].iloc[0].T_iso_ms)
    isolated=[dict(run_id=r['run_id'],non_overlap_n=r['n'],non_overlap_gpu_stream_span_p50_ms=r['p50'],Gate0_T_iso_host_mean_ms=iso_value,status='NOT_COMPARABLE',absolute_difference=None,relative_difference=None) for r in ov_summary if r['group']=='non-overlap' and r['metric']=='gpu_exec_duration_ms']
    write_csv(destination/'isolated_reference_check.csv',isolated)
    plots(destination,stats,ov_summary,startup)
    changed=[p for p,h in provenance.items() if sha(ROOT/p)!=h]
    write_json(destination/'preservation.json',dict(status='PASS' if not changed else 'FAIL',input_count=len(provenance),changed=changed,source_sha256=provenance))
    import subprocess
    with (destination/'final_git_status.txt').open('x') as f:f.write(subprocess.check_output(['git','status','--short','--branch'],cwd=ROOT,text=True))
    print(json.dumps(dict(status='PASS' if valid else 'INCONCLUSIVE',runs=len(stats),output=str(destination))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=OUT/'analysis01');args=p.parse_args()
    analyze(args.output)
