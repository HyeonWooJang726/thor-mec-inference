"""Frozen pruning accounting plus additional log-only diagnostics and block gates."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics as st
import traceback
import types
import numpy as np
import campaign_config as cfg
from reuse import previous_analysis as old

read_csv,write_csv=old.read_csv,old.write_csv
val=old.prior_analysis.val
quantiles=old.prior_analysis.quantiles


def flatten(value,prefix=''):
    result={}
    for key,v in value.items():
        name=prefix+str(key)
        if isinstance(v,dict):result.update(flatten(v,name+'_'))
        elif isinstance(v,(list,tuple)):result[name]=json.dumps(v)
        else:result[name]=v
    return result


def summarize(m,frames,power):
    def decorated(row,start,target,mode,D): return cfg.decorate(row,start,m)
    fn=old._summarize
    raw=types.FunctionType(fn.__code__,dict(fn.__globals__,decorate=decorated))
    fn=old.summarize
    adapted=types.FunctionType(fn.__code__,dict(fn.__globals__,_summarize=raw))
    s=adapted(m,frames,power)
    s['experiment']='TIMELY_CAPACITY_CAMPAIGN'
    try:
        source=[r for r in frames if r.get('phase')=='active']
        rows=[r for r in source if int(r.get('admitted') or 0)]
        if len({(int(r['stream_id']),int(r['frame_id'])) for r in source})!=len(source):raise ValueError('Duplicate source IDs')
        s.update(diagnostics(m,source,rows,power))
    except Exception:
        s['errors'].append(traceback.format_exc());s.update(integrity_status='INVALID',validity='INVALID',pipeline_audit_status='FAIL')
    return s


def diagnostics(m,source,rows,power):
    t0,t1=m['active_start_ns'],m['active_end_ns'];duration=(t1-t0)/1e9
    out={};by_slot=defaultdict(list)
    for r in source:by_slot[int(r['frame_id'])].append(r)
    out['slot_counts']={}
    for label,predicate in [('source',lambda r:True),('admitted',lambda r:int(r.get('admitted') or 0)),('local',lambda r:r.get('placement')=='LOCAL'),('edge',lambda r:r.get('placement')=='EDGE')]:
        values=[sum(bool(predicate(r)) for r in rr) for rr in by_slot.values()]
        out['slot_counts'][label]=dict(mean=st.mean(values),min=min(values),max=max(values),histogram=dict(Counter(values)))
    out['path_timely']={};out['latency_decomposition']=[];out['remaining_budget']={}
    for path in ('LOCAL','EDGE'):
        rr=[r for r in rows if r['placement']==path]
        def state(r):return 'EXPIRED' if r.get('terminal_state')=='EXPIRED_DROP' else 'TIMELY' if val(r,'completion_timestamp_ns')-val(r,'logical_arrival_ns')<=100_000_000 else 'LATE'
        count=Counter(state(r) for r in rr)
        out['path_timely'][path]=dict(assigned_FPS=len(rr)/duration,timely_FPS=count['TIMELY']/duration,
            late_completed_FPS=count['LATE']/duration,expired_drop_FPS=count['EXPIRED']/duration,
            timely_ratio=count['TIMELY']/len(rr) if rr else None,**dict(count))
        for disposition in ('ALL_EXECUTED','TIMELY','LATE','EXPIRED'):
            group=[r for r in rr if (val(r,'completion_timestamp_ns') is not None if disposition=='ALL_EXECUTED' else state(r)==disposition)]
            segments=[('source_ready','logical_arrival_ns','ready_timestamp_ns')]
            segments += [('ready_start','ready_timestamp_ns','inference_start_timestamp_ns'),('start_end','inference_start_timestamp_ns','completion_timestamp_ns')] if path=='LOCAL' else [('ready_submit','ready_timestamp_ns','socket_submission_ns'),('submit_result','socket_submission_ns','response_completion_ns')]
            for name,a,b in segments:
                values=[(val(r,b)-val(r,a))/1e6 for r in group if val(r,a) is not None and val(r,b) is not None]
                out['latency_decomposition'].append(dict(path=path,state=disposition,segment=name,n=len(values),**quantiles(values)))
            if path=='LOCAL':
                executed=[r for r in group if val(r,'inference_start_timestamp_ns') is not None]
                budgets=[100-(val(r,'inference_start_timestamp_ns')-val(r,'logical_arrival_ns'))/1e6 for r in executed]
                out['remaining_budget'][disposition]=dict(n=len(budgets),**quantiles(budgets),
                    negative_fraction=sum(v<0 for v in budgets)/len(budgets) if budgets else None,
                    nonpositive_fraction=sum(v<=0 for v in budgets)/len(budgets) if budgets else None,
                    observed_service_exceeds_budget_fraction=sum((val(r,'completion_timestamp_ns')-val(r,'inference_start_timestamp_ns'))/1e6>b for r,b in zip(executed,budgets))/len(budgets) if budgets else None)
    out['slot_rank_outcomes']=[]
    for scope in ('ALL_ADMITTED_ENTRY_ORDER','LOCAL_QUEUE_ENTRY_ORDER'):
        counts=defaultdict(Counter)
        for rr in by_slot.values():
            rr=[r for r in rr if int(r.get('admitted') or 0) and (scope=='ALL_ADMITTED_ENTRY_ORDER' or r['placement']=='LOCAL')]
            stamps=[val(r,'enqueue_timestamp_ns') for r in rr]
            if None in stamps or len(set(stamps))!=len(stamps):
                for r in rr:counts['N/A'][state(r)]+=1
            else:
                for rank,r in enumerate(sorted(rr,key=lambda r:val(r,'enqueue_timestamp_ns')),1):counts[rank][state(r)]+=1
        for rank in list(range(1,9))+(['N/A'] if 'N/A' in counts else []):
            c=counts[rank];n=sum(c.values())
            out['slot_rank_outcomes'].append(dict(scope=scope,rank=rank,n=n,timely=c['TIMELY'],late=c['LATE'],expired=c['EXPIRED'],timely_ratio=c['TIMELY']/n if n else None))
    out['run_start_diagnostics']=m.get('run_start_diagnostics',{})
    samples=[(val(r,'timestamp_ns'),val(r,'network_tx_bytes')) for r in power if val(r,'network_tx_bytes') is not None]
    if m.get('edge_r') and len(samples)>=2 and samples[0][0]<=t0 and samples[-1][0]>=t1 and all(b[1]>=a[1] for a,b in zip(samples,samples[1:])):
        # Counter observation interpolation only; this is not an inferred event timestamp.
        tx=float(np.interp(t1-t0,[x[0]-t0 for x in samples],[x[1] for x in samples])-np.interp(0,[x[0]-t0 for x in samples],[x[1] for x in samples]))
        out['network_interface_TX_bytes_per_s']=tx/duration
    else:out['network_interface_TX_bytes_per_s']=None
    sent=[r for r in rows if r['placement']=='EDGE' and val(r,'socket_send_complete_ns') is not None and t0<=val(r,'socket_send_complete_ns')<t1]
    out['network_RAW640_completed_send_bytes_per_s']=len(sent)*691200/duration
    out['network_TX_scope']='Interface counter includes other traffic/link overhead; interpolated active endpoints. RAW640 counter includes image payload only.'
    return out


def verdict_a(rows):
    if len(rows)!=6 or any(r.get('integrity_status')!='VALID' for r in rows):return 'INCONCLUSIVE'
    pairs=[({r['admission_pattern']:r for r in rows if r['repeat']==rep}) for rep in (1,2,3)]
    if any(set(p)!=set(('ALIGNED','STAGGERED')) for p in pairs):return 'INCONCLUSIVE'
    gains=[p['STAGGERED']['timely_FPS']-p['ALIGNED']['timely_FPS'] for p in pairs]
    queues=[p['STAGGERED']['local_queue_ms']['p95']-p['ALIGNED']['local_queue_ms']['p95'] for p in pairs]
    if all(g>0 for g in gains) and all(q<0 for q in queues):return 'STAGGER_SUPPORTED'
    if all(g<0 for g in gains):return 'ALIGNED_BETTER'
    ranges=[]
    for pattern in ('ALIGNED','STAGGERED'):
        v=[r['timely_FPS'] for r in rows if r['admission_pattern']==pattern];q=[r['local_queue_ms']['p95'] for r in rows if r['admission_pattern']==pattern]
        ranges.append((max(v)-min(v),max(q)-min(q)))
    if all(abs(g)<=min(x[0] for x in ranges) for g in gains) and all(abs(q)<=min(x[1] for x in ranges) for q in queues):return 'NO_EFFECT'
    return 'INCONCLUSIVE'


def verdict_b(rows,target):
    selected=[r for r in rows if r['repeat']<=3 and r['target_service_FPS']==target]
    count=5 if target==240 else 4
    if len(selected)!=count*3 or any(r.get('integrity_status')!='VALID' for r in selected):return 'INCONCLUSIVE'
    maximum=max(r['edge_r'] for r in selected)
    if any(r['path_timely']['EDGE']['timely_ratio']<.90 for r in selected if r['edge_r']==maximum):return 'EDGE_PATH_LIMITED'
    reference=200 if target==240 else 184
    refs={r['repeat']:r for r in selected if 8*r['local_r']==reference}
    groups={c:[r for r in selected if r['cell']==c] for c in {r['cell'] for r in selected if 8*r['local_r']!=reference}}
    for group in groups.values():
        if all(r['timely_FPS']>refs[r['repeat']]['timely_FPS'] and r['worst_stream_TIR']>=refs[r['repeat']]['worst_stream_TIR'] for r in group):return 'SPLIT_BY_TIMELY_CAPACITY_SUPPORTED'
    if all(refs[r['repeat']]['timely_FPS']>r['timely_FPS'] for group in groups.values() for r in group):return 'REFERENCE_BEST'
    return 'INCONCLUSIVE'


def statistics(rows):
    flat=[flatten(r) for r in rows];result=[]
    for cell in sorted({r['cell'] for r in flat}):
        group=[r for r in flat if r['cell']==cell]
        for metric in sorted({k for r in group for k,v in r.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}):
            values=[r[metric] for r in group if r.get('integrity_status')=='VALID' and isinstance(r.get(metric),(int,float)) and math.isfinite(r[metric])]
            result.append(dict(cell=cell,metric=metric,planned=len(group),valid_n=len(values),
                repeat_values={r['repeat']:r.get(metric) for r in group},mean=st.mean(values) if values else None,
                sample_SD=st.stdev(values) if len(values)>1 else None,min=min(values) if values else None,max=max(values) if values else None))
    return result


def predictions(block,results):
    primary=[r for r in results if r['repeat']<=3]
    if any(r['integrity_status']!='VALID' for r in primary):return {'status':'INCONCLUSIVE','reason':'Incomplete/invalid primary evidence','verdict_effect':'NONE'}
    groups={cell:[r for r in primary if r['cell']==cell] for cell in {r['cell'] for r in primary}}
    if block=='A':
        def group(load,pattern):return {r['repeat']:r for r in groups[f'L{load}-{pattern}']}
        def improvement(load):
            a,b=group(load,'ALIGNED'),group(load,'STAGGERED')
            return [dict(repeat=i,timely_delta=b[i]['timely_FPS']-a[i]['timely_FPS'],queue_p95_delta=b[i]['local_queue_ms']['p95']-a[i]['local_queue_ms']['p95']) for i in (1,2,3)]
        a1=improvement(184);a3=improvement(192)
        return dict(A1=all(r['timely_delta']>0 and r['queue_p95_delta']<0 for r in a1),A1_observations=a1,
            A2='DESCRIPTIVE_ONLY: high/small not assigned an invented threshold',A2_observations=improvement(176),
            A3=all(r['timely_delta']>0 for r in a3) and all(group(192,'STAGGERED')[i]['path_timely']['LOCAL']['timely_ratio']<group(184,'STAGGERED')[i]['path_timely']['LOCAL']['timely_ratio'] for i in (1,2,3)),A3_observations=a3,verdict_effect='NONE')
    winners={};means={}
    for target in (200,240):
        values={cell:st.mean(r['timely_FPS'] for r in rr) for cell,rr in groups.items() if rr[0]['target_service_FPS']==target}
        top=max(values.values());winners[target]=[cell for cell,v in values.items() if v==top];means[target]=top
    return dict(B1=all(160<=8*groups[cell][0]['local_r']<=176 for cell in winners[240]),
        B2=225<=means[240]<=235 and means[240]>st.mean(r['timely_FPS'] for r in groups['S240-L200E40']),
        B3=all(160<=8*groups[cell][0]['local_r']<=176 for cell in winners[200]) and means[200]>=195,
        B4=all(r['path_timely']['EDGE']['timely_ratio']>=.90 for r in results),
        tied_winning_cells=winners,maximum_configuration_mean_timely_FPS=means,
        selection_scope='R1-R3 configuration means; ties retained; observed maximum, no global optimum claim',verdict_effect='NONE')


def analyze(block,destination):
    plan=cfg.load_plan(block);root=cfg.out(block);results=[];before={}
    if destination.exists():raise RuntimeError('No analysis overwrite')
    for c in plan['order']:
        d=root/c['run_id'];before.update({str(p):cfg.sha(p) for p in d.rglob('*') if p.is_file()})
        try:
            m=json.loads((d/'manifest.json').read_text())
            for k in ('cell','repeat','local_r','edge_r','admission_pattern','block'):
                if m.get(k)!=c[k]:raise ValueError('Condition mismatch: '+k)
            fn=old.verify_lifecycle
            types.FunctionType(fn.__code__,dict(fn.__globals__,OUT=root,PLAN=root/'plan.json'))(m,c)
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            saved=json.loads((d/'summary.json').read_text())
            for k in ('integrity_status','admitted_frames','completed_frames','expired_dropped_frames','timely_completed_frames'):
                if saved.get(k)!=s.get(k):raise ValueError('Raw replay mismatch: '+k)
        except Exception:s=dict(integrity_status='INVALID',errors=[traceback.format_exc()])
        s.update(c);results.append(s)
    assert all(cfg.sha(p)==h for p,h in before.items())
    destination.mkdir(parents=True,exist_ok=False)
    write_csv(destination/'per_run_metrics.csv',[flatten(r) for r in results])
    write_csv(destination/'condition_statistics.csv',statistics(results))
    write_csv(destination/'primary_R1_R3_statistics.csv',statistics([r for r in results if r['repeat']<=3]))
    for key in ('slot_rank_outcomes','latency_decomposition','per_stream'):
        entries=[dict(run_id=r['run_id'],cell=r['cell'],repeat=r['repeat'],**v) for r in results for v in r.get(key,[])]
        if entries:write_csv(destination/(key+'.csv'),entries)
    verdicts=([dict(load=n,verdict=verdict_a([r for r in results if r['target_service_FPS']==n])) for n in (176,184,192)] if block=='A' else
              [dict(demand=n,verdict=verdict_b(results,n)) for n in (200,240)])
    for name,value in [('replay.json',results),('verdict.json',verdicts),('prediction_assessment.json',predictions(block,results)),('preservation.json',dict(status='PASS',input_sha256=before))]:
        with (destination/name).open('x') as f:json.dump(value,f,indent=2)
    if block=='B':
        curve=[dict(cell=r['cell'],repeat=r['repeat'],demand=r['target_service_FPS'],local_load=8*r['local_r'],
            integrity_status=r['integrity_status'],**r.get('path_timely',{}).get('LOCAL',{})) for r in results]
        write_csv(destination/'local_timely_curve.csv',curve)
        brackets=[]
        for demand in (200,240):
            for threshold in (.95,.99):
                rr=[r for r in curve if r['demand']==demand and r['repeat']<=3];passed=[];failed=[]
                for load in sorted({r['local_load'] for r in rr}):
                    group=[r for r in rr if r['local_load']==load]
                    if len(group)==3 and all(r['integrity_status']=='VALID' and r.get('timely_ratio',-1)>=threshold for r in group):passed.append(load)
                    elif len(group)==3 and all(r['integrity_status']=='VALID' and r.get('timely_ratio',1)<threshold for r in group):failed.append(load)
                top=max(passed) if passed else None
                brackets.append(dict(demand=demand,threshold=threshold,highest_3_of_3_passing_Local_load=top,
                    next_3_of_3_failing_tested_load=min([x for x in failed if top is not None and x>top],default=None),
                    passing_loads=passed,failing_loads=failed,scope='Observed split-specific configurations; no interpolation or isolated-Local capacity claim'))
        write_csv(destination/'timely_capacity_brackets.csv',brackets)
        # Plot only recorded results. No smoothing/interpolation/fitting or invented intervals.
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axs=plt.subplots(1,2,figsize=(10,4))
        for demand in (200,240):
            group=[r for r in curve if r['demand']==demand and r['repeat']<=3 and r['integrity_status']=='VALID']
            loads=sorted({r['local_load'] for r in group})
            for ax,key in zip(axs,('timely_FPS','timely_ratio')):
                for repeat in (1,2,3):
                    rs=sorted([r for r in group if r['repeat']==repeat],key=lambda r:r['local_load'])
                    ax.plot([r['local_load'] for r in rs],[r[key] for r in rs],alpha=.2,linewidth=.7)
                ax.plot(loads,[st.mean(r[key] for r in group if r['local_load']==load) for load in loads],marker='o',label=f'S{demand} mean R1–R3')
                ax.set_xlabel('Assigned Local FPS');ax.set_ylabel(key);ax.legend();ax.grid(alpha=.2)
        fig.tight_layout();fig.savefig(destination/'local_timely_curves.png',dpi=200);fig.savefig(destination/'local_timely_curves.pdf');plt.close(fig)
    print(json.dumps(verdicts))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--block',choices=['A','B'],required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();analyze(a.block,a.output)
