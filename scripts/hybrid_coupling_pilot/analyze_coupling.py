#!/usr/bin/env python3
"""Pilot-aware raw replay using frozen Hybrid validation/statistical definitions."""
import argparse,csv,inspect,json,math,statistics
from pathlib import Path
from pilot_common import ROOT,OUT,load_plan,decorate,hybrid
import analyze_hybrid as h
read_csv=h.read_csv

def adapted_summary_source():
    s=inspect.getsource(h.summarize);rep=hybrid.replace_once
    s=rep(s,"rows=[r for r in frames if r['phase']=='active']",
        "rows=[r for r in frames if r['phase']=='active']\n    e=int(manifest['edge_r'])\n    admitted_rows=[r for r in rows if int(r.get('admitted') or 0)==1]")
    s=rep(s,'admitted_frames=len(rows)','admitted_frames=len(admitted_rows)')
    s=rep(s,"finished=[r for r in rows if val(r,'completion_timestamp_ns') is not None]","finished=[r for r in admitted_rows if val(r,'completion_timestamp_ns') is not None]")
    s=rep(s,"logical_arrival_ns=val(r,'logical_arrival_ns')),t0)","logical_arrival_ns=val(r,'logical_arrival_ns')),t0,e)")
    s=rep(s,"int(r.get('admitted') or 0)!=1","int(r.get('admitted') or 0)!=expected['admitted']")
    s=rep(s,"'EDGE':int(duration*5)","'EDGE':int(duration*e)")
    s=rep(s,"entry['terminal_placement_gap']=len(rs)-sum(assigned.values())",
        "entry['unadmitted_source_frames']=sum(r.get('placement')=='SKIP' for r in rs)\n        entry['terminal_placement_gap']=len(rs)-sum(assigned.values())-entry['unadmitted_source_frames']")
    s=rep(s,"for r in rows:\n        if not ordered(r,common):", "for r in rows:\n        if r.get('placement')=='SKIP':\n            if not ordered(r,('logical_arrival_ns','b_ns','source_pulled_ns','resize_start_ns','resize_end_ns')):bad('unadmitted decode/resize timestamp corruption')\n            if any(val(r,k) is not None for k in ('payload_ready_ns','ready_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns','edge_request_id')):bad('unadmitted source received service')\n            continue\n        if not ordered(r,common):")
    s=rep(s,"len(finished)!=len(rows)","len(finished)!=len(admitted_rows)")
    s=rep(s,"expected_edge=int(duration*40)","expected_edge=int(duration*8*e)")
    start=s.index("    if any(ef.get(k)!=expected_edge")
    end=s.index("    if manifest.get('forced_drop')",start)
    block=s[start:end]
    s=s[:start]+"    if e:\n"+''.join('    '+line+'\n' for line in block.splitlines())+"    elif manifest.get('edge_usage')!='NOT_USED' or ef.get('status')!='NOT_USED' or manifest.get('edge_path_errors') or not manifest.get('edge_threads_exited'):\n        bad('zero Edge condition lifecycle corruption')\n"+s[end:]
    s=rep(s,"[('H',rows),('L',lrows),('E',erows)]","[('H',admitted_rows),('L',lrows),('E',erows)]")
    s=rep(s,'total_offered_FPS=len(rows)/duration','total_offered_FPS=len(admitted_rows)/duration')
    s=rep(s,'completion_offered_ratio=len(completed)/max(1,len(rows))','completion_offered_ratio=len(completed)/max(1,len(admitted_rows))')
    s=rep(s,"[('global',rows),('local',lrows),('edge',erows)]","[('global',admitted_rows),('local',lrows),('edge',erows)]")
    start=s.index('    # Reuse original source/ready diagnostic criteria;')
    end=s.index('    summary.update(frozen_power',start)
    s=s[:start]+'''    # Source pending uses all decoded frames; ready pending only admitted work.
    if all(val(r,'source_pulled_ns') for r in rows) and all(val(r,'ready_timestamp_ns') for r in admitted_rows):
        left=t1-int(min(30,duration/2)*1e9);slopes={}
        for name,key,rr in [('source','source_pulled_ns',rows),('frontend','ready_timestamp_ns',admitted_rows)]:
            slopes[name]=[local_analysis.queue_slope([r for r in rr if int(r['stream_id'])==sid],left,t1,'logical_arrival_ns',key) for sid in range(8)]
        deficit=max(0,len(admitted_rows)-len(active(admitted_rows,'ready_timestamp_ns')))/max(1,len(admitted_rows))
        limited=(deficit>.01 and (sum(slopes['frontend'])>.5 or max(slopes['frontend'])>.2)) or sum(slopes['source'])>.5 or max(slopes['source'])>.2
        summary.update(frontend_ready_deficit_fraction=deficit,source_pending_slope=sum(slopes['source']),frontend_pending_slope=sum(slopes['frontend']),supply_status='FRONTEND_LIMITED' if limited else 'NORMAL')
    else:summary['supply_status']='UNKNOWN'
    summary.update(edge_r=e,source_FPS=len(rows)/duration,admission_skipped_frames=len(rows)-len(admitted_rows),
                   concurrency_scope='host service interval overlap, not GPU kernel overlap',
                   edge_usage='ACTIVE' if e else 'NOT_USED')
    for name,rr,a,b in [('resize',rows,'resize_start_ns','resize_end_ns'),
                       ('local_decode_to_ready_proxy',lrows,'source_pulled_ns','ready_timestamp_ns'),
                       ('local_remaining_preprocess_proxy',lrows,'payload_ready_ns','ready_timestamp_ns')]:
        summary[name+'_ms']=quantiles([(val(r,b)-val(r,a))/1e6 for r in rr if val(r,a) is not None and val(r,b) is not None])
    # Queued Edge request awaiting sender, plus in-send interval. Same Thor clock.
    def pending(a,b):
        return backlog([dict(logical_arrival_ns=val(r,a),response_completion_ns=val(r,b)) for r in erows if val(r,a) is not None],t0,t1,min(30,duration/2))
    summary['edge_client_pending_backlog']=pending('payload_ready_ns','socket_submission_ns')
    summary['edge_send_inflight_backlog']=pending('socket_submission_ns','socket_send_complete_ns')
''' +s[end:]
    return s

ns=dict(h.__dict__,decorate=decorate)
exec(compile(adapted_summary_source(),'<coupling-raw-replay-adapter>','exec'),ns)
summarize=ns['summarize']

def flatten(s):
    r={k:v for k,v in s.items() if not isinstance(v,(dict,list))}
    for group in ('local_service_ms','local_queue_ms','edge_client_pending_ms','edge_send_ms',
                  'available_rail_power_W_diagnostic','edge_client_pending_backlog','edge_send_inflight_backlog'):
        r.update({group+'_'+k:v for k,v in s.get(group,{}).items()})
    return r

METRICS=(['local_completed_FPS','g_B_L']+
    [g+'_'+q for g in ('local_service_ms','local_queue_ms') for q in ('mean','p50','p95','p99')]+
    ['active_concurrency_mean','active_concurrency_peak','edge_completed_FPS','g_B_E','g_B_H',
     'decode_ready_FPS','resize_ready_FPS','payload_ready_FPS']+
    [g+'_'+q for g in ('edge_client_pending_ms','edge_send_ms') for q in ('mean','p50','p95','p99')]+
    ['avg_power_W','available_rail_power_W_diagnostic_VDD_CPU_SOC_MSS',
     'temperature','OC3_before','OC3_after','OC3_delta'])

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def aggregate_pairs(flat):
    """Keep both observations, including INVALID; aggregate only valid measurements.

    SD is across the two run-level statistics (ddof=1), not pooled frame quantiles.
    Empty Edge latency at E=0 remains unavailable, never a fabricated zero.
    """
    pairs=[]
    for e in (0,1,2,3,5):
        rr={r['pass_name']:r for r in flat if r['edge_r']==e}
        if set(rr)!={'A','B'}:raise ValueError('both A/B observations required')
        for metric in METRICS:
            a,b=rr['A'].get(metric),rr['B'].get(metric)
            valid=[r.get(metric) for r in rr.values() if r['integrity_status']=='VALID' and finite(r.get(metric))]
            both=len(valid)==2
            pairs.append(dict(edge_FPS=8*e,metric=metric,A_run=rr['A']['run_id'],B_run=rr['B']['run_id'],
                A_integrity=rr['A']['integrity_status'],B_integrity=rr['B']['integrity_status'],
                A_value=a,B_value=b,B_minus_A=b-a if both else None,valid_n=len(valid),
                mean=statistics.mean(valid) if valid else None,
                sample_SD=statistics.stdev(valid) if both else None))
    return pairs

def diagnostic_report(flat,pairs):
    """Descriptive paired differences, pass-wise rate ordering and rank associations.

    No thresholds, fitted model, significance tests or causal mechanism label.
    """
    def fmt(x):return f'{x:.6f}' if finite(x) else 'N/A'
    lines=['# Forward/reverse coupling pilot comparison','',
        'A and B are shown separately. Means/SD in rate_repeat_summary.csv use integrity-valid runs only; '
        'sample SD uses ddof=1. Run-level latency quantiles are averaged, never pooled. '
        'OC3 before/after are cumulative counters; their means/SD are bookkeeping only. '
        'OC3 delta is the within-run protection diagnostic.', '',
        '| Edge FPS | Metric | A | B | B−A | Mean | Sample SD | valid n |',
        '|---:|---|---:|---:|---:|---:|---:|---:|']
    selected=('local_completed_FPS','local_service_ms_mean','local_service_ms_p95','g_B_L','temperature','OC3_delta')
    for r in pairs:
        if r['metric'] in selected:
            lines.append('| '+ ' | '.join([str(r['edge_FPS']),r['metric']]+[fmt(r[k]) for k in ('A_value','B_value','B_minus_A','mean','sample_SD')]+[str(r['valid_n'])])+' |')
    lines+=['','Rate-step differences below sort each pass by Edge rate, even though B ran in reverse. '
            'They show whether Local completion/service changes have the same direction in both passes; '
            'no arbitrary similarity tolerance is applied.','',
            '| Edge step | Δ Local FPS A / B | Δ service mean ms A / B |','|---|---:|---:|']
    for e1,e2 in zip((0,1,2,3),(1,2,3,5)):
        deltas={}
        for p in ('A','B'):
            r1=next(r for r in flat if r['edge_r']==e1 and r['pass_name']==p)
            r2=next(r for r in flat if r['edge_r']==e2 and r['pass_name']==p)
            for key in ('local_completed_FPS','local_service_ms_mean'):
                deltas[p,key]=(r2[key]-r1[key] if r1['integrity_status']==r2['integrity_status']=='VALID'
                              and finite(r1.get(key)) and finite(r2.get(key)) else None)
        lines.append(f'| {8*e1}→{8*e2} | '+ ' | '.join(' / '.join(fmt(deltas[p,k]) for p in ('A','B')) for k in ('local_completed_FPS','local_service_ms_mean'))+' |')
    lines+=['','Descriptive Spearman rank association (average ranks for ties), separately within each pass and across both. '
            'This places Edge rate, chronological order, temperature and OC3 delta on the same association scale. '
            'Undefined constant/missing series are N/A. No p-values, fitted explanation or causal ranking is claimed.', '',
            '| Scope | Predictor | Local FPS rho / n | Service mean rho / n |','|---|---|---:|---:|']
    def rho(rows,x,y):
        v=[r for r in rows if r['integrity_status']=='VALID' and finite(r.get(x)) and finite(r.get(y))]
        if len(v)<2:return None,len(v)
        def ranks(key):
            values=[r[key] for r in v]
            return [sum(z<t for z in values)+(sum(z==t for z in values)+1)/2 for t in values]
        a,b=ranks(x),ranks(y)
        if len(set(a))<2 or len(set(b))<2:return None,len(v)
        return float(h.np.corrcoef(a,b)[0,1]),len(v)
    for scope in ('A','B','A+B'):
        rows=[r for r in flat if scope=='A+B' or r['pass_name']==scope]
        for x in ('edge_r','order_index','temperature','OC3_delta'):
            cells=[]
            for y in ('local_completed_FPS','local_service_ms_mean'):
                value,n=rho(rows,x,y);cells.append(fmt(value)+' / '+str(n))
            lines.append('| '+' | '.join([scope,x]+cells)+' |')
    lines+=['','Compare same-rate A/B differences with their temperature/OC3 changes before attributing a pattern to Edge rate. '
            'Forward/reverse ordering reduces the simple rate-versus-time confound but does not isolate temperature, '
            'hysteresis or protection effects. Two 10-s observations per rate are diagnostic evidence only. '
            'Neither higher rank association nor matching directions proves CPU/memory/network/GPU causation. '
            'No automated interference or mechanism verdict is assigned.']
    return '\n'.join(lines)+'\n'

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True);args=ap.parse_args()
    results=[]
    for c in load_plan()['order']:
        d=OUT/c['run_id']
        if not (d/'summary.json').exists():raise RuntimeError('planned pilot missing: '+str(d))
        m=json.loads((d/'manifest.json').read_text());s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
        s.update(pass_name=c['pass'],order_index=c['order_index'],edge_r=c['edge_r'],repeat=c['repeat'])
        if (m.get('run_id')!=c['run_id'] or m.get('repeat')!=c['repeat'] or m.get('edge_r')!=c['edge_r']
                or m.get('pass_name')!=c['pass'] or m.get('order_index')!=c['order_index']):
            s['errors'].append('A/B condition identity mismatch');s.update(integrity_status='INVALID',queue_stable=False)
        s.update(child_returncode=m.get('child_returncode'),PROCESS_LIFECYCLE=m.get('PROCESS_LIFECYCLE'),frequency_restore_ok=m.get('frequency_restore_ok'))
        if s['child_returncode']!=0 or s['PROCESS_LIFECYCLE']!='PASS' or not s['frequency_restore_ok']:
            s.update(integrity_status='INVALID',queue_stable=False)
        results.append(s)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    (out/'pilot_replay.json').write_text(json.dumps(results,indent=2)+'\n')
    flat=[flatten(s) for s in results]
    with (out/'pilot_summary.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,list(dict.fromkeys(k for r in flat for k in r)));w.writeheader();w.writerows(flat)
    pairs=aggregate_pairs(flat)
    with (out/'rate_repeat_summary.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,list(pairs[0]));w.writeheader();w.writerows(pairs)
    (out/'forward_reverse_comparison.md').write_text(diagnostic_report(flat,pairs))
    print('A/B observations, mean/sample SD and order/temperature/OC3 diagnostics saved; no causal verdict assigned.')
if __name__=='__main__':main()
