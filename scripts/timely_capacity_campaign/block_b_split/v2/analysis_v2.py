"""Log-only V2 replay. Primary split gate excludes all capped admission conditions."""
import argparse
import json
import types
import traceback
from pathlib import Path
from collections import Counter
from bootstrap import ROOT,V2,frozen as cfg
import config_v2 as conf
import campaign_analysis as old
import wifi_v2
read_csv=old.read_csv

def summarize(m,frames,power):
    s=old.summarize(m,frames,power)
    if s.get('integrity_status')!='VALID':return s
    source=[r for r in frames if r.get('phase')=='active']
    duration=(m['active_end_ns']-m['active_start_ns'])/1e9
    for label,stats in s['slot_counts'].items():
        values=[int(k) for k,n in stats['histogram'].items() for _ in range(n)]
        stats.update(old.quantiles(values))
    for path,stats in s['path_timely'].items():
        rows=[r for r in source if r.get('placement')==path]
        stats['completed_cohort_FPS']=sum(old.val(r,'completion_timestamp_ns') is not None for r in rows)/duration
        stats['active_completed_FPS']=sum(m['active_start_ns']<=(old.val(r,'completion_timestamp_ns') or 0)<m['active_end_ns'] for r in rows)/duration
    s.update(source_demand_FPS=m['source_demand_FPS'],analysis_class=m['analysis_class'],original_cell=m['original_cell'],
        source_normalization_FPS=240,admission_r=m['target_service_FPS']//8,admitted_FPS=s['admitted_frames']/duration,
        unadmitted_FPS=(len(source)-s['admitted_frames'])/duration,
        source_normalized_TIR=s['timely_completed_frames']/len(source),
        source_timely_shortfall_FPS=240-s['timely_FPS'],
        admitted_timely_shortfall_FPS=s['admitted_frames']/duration-s['timely_FPS'],
        completed_cohort_FPS=s['completed_frames']/duration,
        wifi=wifi_v2.compare(m.get('wifi_start',{}),m.get('wifi_end',{})),
        run_end_diagnostics=m.get('run_end_diagnostics',{}))
    return s

def primary_gate(rows,demand):
    selected=[r for r in rows if r['source_demand_FPS']==demand and r['analysis_class']=='B-PRIMARY' and r['repeat']<=3]
    refname=f'S{demand}-L'+('200E40' if demand==240 else '184E16')
    refs={r['repeat']:r for r in selected if r['original_cell']==refname}
    groups={name:[r for r in selected if r['original_cell']==name] for name in {r['original_cell'] for r in selected if r['original_cell']!=refname}}
    if set(refs)!={1,2,3} or not groups or any(len(g)!=3 or {r['repeat'] for r in g}!={1,2,3} for g in groups.values()) or any(r.get('integrity_status')!='VALID' for r in selected):return 'INCONCLUSIVE'
    for group in groups.values():
        if all(r['timely_FPS']>refs[r['repeat']]['timely_FPS'] and r['worst_stream_TIR']>=refs[r['repeat']]['worst_stream_TIR'] for r in group):return 'SPLIT_BY_TIMELY_CAPACITY_SUPPORTED'
    if all(refs[r['repeat']]['timely_FPS']>r['timely_FPS'] for group in groups.values() for r in group):return 'REFERENCE_BEST'
    return 'INCONCLUSIVE'

def prediction_report(rows,preflight):
    report={f'A{i}':dict(status='INCONCLUSIVE',reason='Block A frozen analysis is independent; not inferred from Block B') for i in range(1,4)}
    apath=cfg.out('A')/'analysis01/replay.json'
    if apath.exists():
        try:
            ar=json.loads(apath.read_text())
            if len(ar)==18 and all(r.get('integrity_status')=='VALID' for r in ar):
                arpt=old.predictions('A',ar)
                for key in ('A1','A3'):report[key]=dict(status='SUPPORTED' if arpt[key] else 'NOT_SUPPORTED',observations=arpt[key+'_observations'],source=str(apath),verdict_effect='NONE')
                report['A2']=dict(status='INCONCLUSIVE',reason='Original high/small prediction has no quantitative threshold; no threshold added',observations=arpt['A2_observations'])
        except Exception:report['A_audit_error']=traceback.format_exc()
    for demand,keys in ((240,('B1','B2')),(200,('B3',))):
        rr=[r for r in rows if r['source_demand_FPS']==demand and r['analysis_class']=='B-PRIMARY' and r['repeat']<=3]
        expected=5 if demand==240 else 4
        cells={r['cell'] for r in rr}
        if len(cells)!=expected or len(rr)!=3*expected or any(r.get('integrity_status')!='VALID' for r in rr):
            for k in keys:report[k]=dict(status='INCONCLUSIVE',reason='Original full-demand grid incomplete or invalid; capped work excluded')
            continue
        means={c:old.st.mean(r['timely_FPS'] for r in rr if r['cell']==c) for c in cells};top=max(means.values());winners=[c for c,v in means.items() if v==top]
        locs={8*r['local_r'] for r in rr if r['cell'] in winners};in_range=all(160<=x<=176 for x in locs)
        ref=old.st.mean(r['timely_FPS'] for r in rr if 8*r['local_r']==(200 if demand==240 else 184))
        for k in keys:
            passed=in_range if k=='B1' else (top>ref and 225<=top<=235) if k=='B2' else (in_range and top>=195)
            report[k]=dict(status='SUPPORTED' if passed else 'NOT_SUPPORTED',observed_top_configuration_means=winners,top_mean_FPS=top,reference_mean_FPS=ref,verdict_effect='NONE')
    runs=preflight.get('runs',[]);sel=conf.select(runs)
    valid=len(runs)==8 and all(r.get('integrity_status')=='VALID' for r in runs) and len(rows)==35 and all(r.get('integrity_status')=='VALID' for r in rows)
    observed=[r['Edge_timely_ratio'] for r in runs if r.get('integrity_status')=='VALID']
    observed += [r['path_timely']['EDGE']['timely_ratio'] for r in rows if r.get('integrity_status')=='VALID']
    report['B4']=dict(status='NOT_SUPPORTED' if any(x<.90 for x in observed) else 'SUPPORTED' if valid else 'INCONCLUSIVE',
        scope='Preflight and integrated Edge observations retained separately; any valid below90% observation contradicts B4. Full valid evidence required for SUPPORTED. Original prediction preserved.',selection=sel)
    return report

def analyze(emax,destination):
    planpath=conf.branch_path(emax);plan=conf.load(planpath);root=planpath.parent
    if destination.exists():raise RuntimeError('No output overwrite')
    results=[];hashes={}
    for c in plan['order']:
        d=root/c['run_id'];hashes.update({str(p):cfg.sha(p) for p in d.rglob('*') if p.is_file()})
        try:
            m=json.loads((d/'manifest.json').read_text())
            for k in ('cell','repeat','local_r','edge_r','analysis_class','source_demand_FPS','target_service_FPS','branch_E_max'):
                if m.get(k)!=c[k]:raise ValueError('Condition mismatch: '+k)
            fn=old.old.verify_lifecycle
            types.FunctionType(fn.__code__,dict(fn.__globals__,OUT=root,PLAN=planpath))(m,c)
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            saved=json.loads((d/'summary.json').read_text())
            for k in ('integrity_status','admitted_frames','completed_frames','expired_dropped_frames','timely_completed_frames'):
                if saved.get(k)!=s.get(k):raise ValueError('Stored/raw mismatch: '+k)
        except Exception:s=dict(integrity_status='INVALID',errors=[traceback.format_exc()])
        s.update(c);results.append(s)
    destination.mkdir(parents=True,exist_ok=False)
    old.write_csv(destination/'per_run_metrics.csv',[old.flatten(r) for r in results])
    old.write_csv(destination/'condition_statistics_all_repeats.csv',old.statistics(results))
    old.write_csv(destination/'condition_statistics_R1_R3.csv',old.statistics([r for r in results if r['repeat']<=3]))
    for key in ('per_stream','slot_rank_outcomes','latency_decomposition'):
        entries=[dict(run_id=r['run_id'],cell=r['cell'],repeat=r['repeat'],**v) for r in results for v in r.get(key,[])]
        if entries:old.write_csv(destination/(key+'.csv'),entries)
    capped=[old.flatten(r) for r in results if r['analysis_class']=='B-CAPPED']
    if capped:old.write_csv(destination/'B_CAPPED_descriptive.csv',capped)
    verdict=[dict(source_demand_FPS=d,verdict=primary_gate(results,d),scope='B-PRIMARY R1-R3 ONLY; capped excluded') for d in (200,240)]
    pf=V2/'preflight01/selection.json';preflight=json.loads(pf.read_text()) if pf.exists() else {}
    curve=[dict(cell=r['cell'],repeat=r['repeat'],source_demand_FPS=r['source_demand_FPS'],admitted_FPS=r['target_service_FPS'],
        analysis_class=r['analysis_class'],local_load=8*r['local_r'],integrity_status=r['integrity_status'],
        Local_queue_p95=r.get('local_queue_ms',{}).get('p95'),Local_queue_p99=r.get('local_queue_ms',{}).get('p99'),
        **r.get('path_timely',{}).get('LOCAL',{})) for r in results]
    old.write_csv(destination/'local_timely_curve.csv',curve)
    brackets=[]
    for demand in (200,240):
        for threshold in (.95,.99):
            passed=[];failed=[];mixed=[]
            for load in sorted({r['local_load'] for r in curve if r['source_demand_FPS']==demand}):
                group=[r for r in curve if r['source_demand_FPS']==demand and r['local_load']==load and r['repeat']<=3]
                if len(group)==3 and all(r['integrity_status']=='VALID' and r['timely_ratio']>=threshold for r in group):passed.append(load)
                elif len(group)==3 and all(r['integrity_status']=='VALID' and r['timely_ratio']<threshold for r in group):failed.append(load)
                else:mixed.append(load)
            top=max(passed,default=None)
            brackets.append(dict(demand=demand,threshold=threshold,highest_3_of_3_passing_tested_load=top,next_3_of_3_failing_load=min((x for x in failed if top is not None and x>top),default=None),passing=passed,failing=failed,mixed_or_invalid=mixed,
                scope='Split/admission-specific observed points, R1-R3; no interpolation or isolated Local capacity claim'))
    old.write_csv(destination/'local_timely_brackets.csv',brackets)
    # Cross-block description only: read A's independent analysis if already available.
    a=cfg.out('A')/'analysis01/replay.json';comparison=[]
    if a.exists():
        hashes[str(a)]=cfg.sha(a)
        for r in json.loads(a.read_text()):
            if r.get('admission_pattern')=='ALIGNED' and 8*r.get('local_r',0) in (176,184):comparison.append(dict(old.flatten(r),block='A'))
    comparison += [dict(block='B',**{k:v for k,v in old.flatten(r).items() if k!='block'}) for r in results if 8*r['local_r'] in (176,184)]
    if comparison:old.write_csv(destination/'cross_block_descriptive.csv',comparison)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(10,7))
    for ax,key in zip(axes.flat,('timely_FPS','timely_ratio','Local_queue_p95','Local_queue_p99')):
        for demand in (200,240):
            for cls in ('B-PRIMARY','B-CAPPED'):
                rr=[r for r in curve if r['integrity_status']=='VALID' and r['source_demand_FPS']==demand and r['analysis_class']==cls]
                if rr:ax.scatter([r['local_load'] for r in rr],[r.get(key) for r in rr],label=f'S{demand} {cls}')
        ax.set_xlabel('Assigned Local FPS');ax.set_ylabel(key);ax.grid(alpha=.2)
        if ax.collections:ax.legend(fontsize=7)
    fig.tight_layout();fig.savefig(destination/'local_timely_curve.png',dpi=180);fig.savefig(destination/'local_timely_curve.pdf');plt.close(fig)
    assert all(cfg.sha(p)==h for p,h in hashes.items())
    for name,value in [('replay.json',results),('B_PRIMARY_verdict.json',verdict),('prediction_assessment.json',prediction_report(results,preflight)),('preservation.json',dict(status='PASS',input_sha256=hashes))]:
        with (destination/name).open('x') as f:json.dump(value,f,indent=2)
    with (destination/'INTERPRETATION.md').open('x') as f:f.write('B-PRIMARY alone supports controlled split comparisons. B-CAPPED changes admission and placement together: descriptive measured operating regime only. Source-normalized TIR always uses 240 FPS; unadmitted frames are not hidden. Endpoint Wi-Fi snapshots cannot establish intervening reconnects or causality. Missing/invalid runs remain visible. No statistical significance, optimality or universal necessity claim. Prediction B1/B2 remain INCONCLUSIVE if original full-demand grid is capped.\n')
    print(json.dumps(verdict))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--emax',type=int,choices=conf.LEVELS,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();analyze(a.emax,a.output)
