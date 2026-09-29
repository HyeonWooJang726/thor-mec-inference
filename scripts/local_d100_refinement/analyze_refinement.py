#!/usr/bin/env python3
"""Read-only raw replay; combine distinct campaigns only as labeled Local grid cells."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import statistics as st
import traceback
import types
from refinement_common import ROOT,OUT,PLAN,GRID,load_plan,sha,decorate,proven_analysis as parent,best_grid,expected_order

read_csv,flatten,write_csv,aggregate=parent.read_csv,parent.flatten,parent.write_csv,parent.aggregate
fn=parent._summarize
raw_summary=types.FunctionType(fn.__code__,dict(fn.__globals__,decorate=decorate))
fn=parent.summarize
adapted_summary=types.FunctionType(fn.__code__,dict(fn.__globals__,_summarize=raw_summary))


def summarize(m,frames,power):
    s=adapted_summary(m,frames,power)
    if m.get('supply_mode')!='A' or m.get('edge_r')!=0:
        s['errors'].append('Edge forbidden in Local refinement')
        s.update(integrity_status='INVALID',validity='INVALID',pipeline_audit_status='FAIL')
    s['experiment']='LOCAL_D100_REFINEMENT'
    return s


def verify_lifecycle(m,c):
    fn=parent.verify_lifecycle
    return types.FunctionType(fn.__code__,dict(fn.__globals__,OUT=OUT,PLAN=PLAN))(m,c)


METRICS=('timely_FPS','worst_stream_timely_FPS','worst_stream_TIR','late_completed_FPS','expired_drop_FPS',
    'VIN_J_per_timely_frame','local_queue_ms_p50','local_queue_ms_p95','local_queue_ms_p99',
    'local_service_ms_p50','local_service_ms_p95','local_service_ms_p99','unfinished_at_active_end',
    'unfinished_after_drain','OC3_delta')


def grid_analysis(new,historical,reference='repeat_best_envelope'):
    history_conditions=best_grid.expected_order();new_conditions=expected_order()
    issues=[];audited={};counts={}
    for cohort,rows,conditions in [('D100_MAP',historical,history_conditions),('LOCAL_REFINEMENT',new,new_conditions)]:
        ids=[r.get('run_id') for r in rows]
        if len(rows)!=len(conditions) or set(ids)!={c['run_id'] for c in conditions}:issues.append(cohort+': missing/extra/duplicate runs')
        for c in conditions:
            matches=[r for r in rows if r.get('run_id')==c['run_id']]
            r=matches[0] if len(matches)==1 else {}
            errors,n=best_grid.audit_row(r,c) if r else (['missing/duplicate'],None)
            issues.extend(c['run_id']+': '+e for e in errors)
            key=(c['cell'],c['repeat'])
            audited[key]=dict(r,cohort=cohort,integrity_status='VALID' if not errors else 'INVALID')
            counts[key]=n if not errors else None
    local_cells=[f'T{n}-A' if n in (160,200,240) else f'L{n}' for n in GRID]
    candidates=[];selections=[];winner_sets={}
    for repeat in (1,2,3,'ALL'):
        scope='AGGREGATE' if repeat=='ALL' else 'REPEAT';scores={};subset=[]
        for target,cell in zip(GRID,local_cells):
            rs=[audited[cell,r] for r in ((1,2,3) if repeat=='ALL' else (repeat,))]
            valid=all(r['integrity_status']=='VALID' for r in rs)
            entry=dict(scope=scope,repeat=repeat,cell=cell,target_service_FPS=target,cohort=rs[0]['cohort'],
                       integrity_status='VALID' if valid else 'INVALID')
            for metric in METRICS:
                values=[flatten(r).get(metric) for r in rs]
                complete=all(best_grid.finite(v) for v in values)
                entry[metric]=st.mean(values) if complete else None
                entry[metric+'_sample_SD']=st.stdev(values) if complete and len(values)>1 else None
            if valid:
                ns=[counts[cell,r] for r in ((1,2,3) if repeat=='ALL' else (repeat,))]
                scores[cell]=Fraction(sum(ns),60*len(ns))
            subset.append(entry)
        winners=[cell for cell in local_cells if scores.get(cell)==max(scores.values())] if len(scores)==7 else []
        winner_sets[str(repeat)]=winners
        # Diagnostic ordering only: it does NOT remove any primary tie.
        selected=[r for r in subset if r['cell'] in winners]
        selected.sort(key=lambda r:(-r['timely_FPS'],r['VIN_J_per_timely_frame'] is None,
                                    r['VIN_J_per_timely_frame'] if r['VIN_J_per_timely_frame'] is not None else 0,r['cell']))
        for i,r in enumerate(selected,1):
            selections.append(dict(r,primary_tied_configurations=winners,diagnostic_order=i,
                diagnostic_note='Aggregate timely FPS descending, then VIN J/timely ascending; ties still retained'))
        for r in subset:r['selected']=r['cell'] in winners
        candidates.extend(subset)
    # Preserve both frozen aggregate-Hybrid selection and per-repeat Hybrid maxima.
    hcells=['T160-B','T200-B','T240-B']
    hybrid_valid=all(counts[c,r] is not None for c in hcells for r in (1,2,3))
    hybrid_fixed=[];envelope=[];fixed_rows=[]
    if hybrid_valid:
        hscores={c:sum(counts[c,r] for r in (1,2,3)) for c in hcells}
        hybrid_fixed=[c for c in hcells if hscores[c]==max(hscores.values())]
        for rep in (1,2,3):
            top=max(counts[c,rep] for c in hcells)
            envelope.append(dict(repeat=rep,selected=[c for c in hcells if counts[c,rep]==top],worst_stream_timely_FPS=top/60))
        fixed_rows=[dict(cell=c,values=[counts[c,r]/60 for r in (1,2,3)]) for c in hybrid_fixed]
    comparisons=[];labels=[]
    for local in winner_sets['ALL']:
        local_values=[counts[local,r]/60 for r in (1,2,3)]
        references=([('repeat_best_envelope',[e['worst_stream_timely_FPS'] for e in envelope])]
                    if reference=='repeat_best_envelope' else [(r['cell'],r['values']) for r in fixed_rows])
        for name,hv in references:
            if len(hv)!=3:continue
            verdict='EDGE_ROLE_INCONCLUSIVE'
            if not issues:
                if min(local_values)>max(hv):verdict='EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
                elif min(hv)>max(local_values):verdict='EDGE_TIMELY_EXTENSION_CANDIDATE'
            comparisons.append(dict(Local=local,Hybrid_reference=name,Local_values=local_values,Hybrid_values=hv,
                Local_mean=st.mean(local_values),Local_sample_SD=st.stdev(local_values),Local_min=min(local_values),Local_max=max(local_values),
                Hybrid_mean=st.mean(hv),Hybrid_sample_SD=st.stdev(hv),Hybrid_min=min(hv),Hybrid_max=max(hv),
                delta_mean_Local_minus_Hybrid=st.mean(local_values)-st.mean(hv),verdict=verdict))
            labels.append(verdict)
    final=labels[0] if labels and len(set(labels))==1 and not issues else 'EDGE_ROLE_INCONCLUSIVE'
    decision=dict(verdict=final,issues=issues,local_winners=winner_sets,
        historical_fixed_Hybrid_winners=hybrid_fixed,historical_fixed_Hybrid_repeats=fixed_rows,
        historical_repeat_best_Hybrid=envelope,comparison_reference=reference,
        rule='Strict non-overlap of observed3repeat worst-streamFPS ranges; equality/overlap or invalid => inconclusive. Not a significance test.',
        limits='Seven sampled Local rates, historical Hybrid, no global optimum/general Edge-necessity claim; noncontemporaneous cohorts and selection on measured data.')
    return candidates,selections,comparisons,decision


def load_history(plan):
    for rel,h in plan['historical_sha256'].items():
        if sha(ROOT/rel)!=h:raise RuntimeError('Historical evidence changed: '+rel)
    return json.loads((ROOT/plan['history_replay']).read_text())


def analyze(output):
    if output.exists():raise RuntimeError('New analysis destination required')
    plan=load_plan();historical=load_history(plan);before={str(PLAN):sha(PLAN)};results=[]
    for c in plan['order']:
        d=OUT/c['run_id'];before.update({str(p):sha(p) for p in d.rglob('*') if p.is_file()})
        try:
            m=json.loads((d/'manifest.json').read_text());verify_lifecycle(m,c)
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            stored=json.loads((d/'summary.json').read_text())
            for k in ('integrity_status','source_frames','admitted_frames','expired_dropped_frames','completed_frames','timely_completed_frames','admitted_identity_sha256'):
                if stored.get(k)!=s.get(k):raise ValueError('Raw/stored mismatch: '+k)
        except Exception:s=dict(integrity_status='INVALID',errors=[traceback.format_exc()])
        s.update({k:c[k] for k in ('run_id','cell','repeat','supply_mode','target_service_FPS','deadline_ms','order_index')});results.append(s)
    candidates,selections,comparisons,decision=grid_analysis(results,historical,plan['comparison_reference'])
    if any(sha(Path(p))!=h for p,h in before.items()):raise RuntimeError('Inputs changed during analysis')
    load_history(plan)
    output.mkdir(parents=True,exist_ok=False)
    streams=[dict(run_id=s['run_id'],cell=s['cell'],repeat=s['repeat'],integrity_status=s['integrity_status'],**r) for s in results for r in s.get('per_stream',[])]
    flat=[flatten(s) for s in results]
    write_csv(output/'per_run_metrics.csv',flat)
    if streams:write_csv(output/'per_stream_metrics.csv',streams)
    write_csv(output/'condition_metrics.csv',aggregate(flat,['cell']))
    if streams:write_csv(output/'condition_stream_metrics.csv',aggregate(streams,['cell','stream_id']))
    for name,rows in [('local_grid_candidates.csv',candidates),('best_local_selections.csv',selections),('hybrid_reference_comparison.csv',comparisons)]:
        write_csv(output/name,[flatten(r) for r in rows])
    with (output/'replay.json').open('x') as f:json.dump(results,f,indent=2)
    with (output/'refinement_verdict.json').open('x') as f:json.dump(decision,f,indent=2)
    with (output/'refinement_verdict.md').open('x') as f:
        f.write('# Local D100 refinement\n\n'+decision['verdict']+'\n\n')
        f.write('Select max mean of3per-run worst-stream timelyFPS across160/168/176/184/192/200/240. Every primary tie retained; aggregate timelyFPS then lowerVINJ/timelyframe provide diagnostic order only. Repeat winners also shown. No curve fitting/exact optimum claim.\n\n')
        f.write(decision['rule']+'\n\n'+decision['limits']+'\n\n')
        f.write('Physical source denominator14400/run and1800/stream. Expired remains timely failure. B=assigned-completed; U=B-expired. VIN is active Thor module+carrier energy only, excludes drain/Edge. MissingVIN/zero timely=>N/A. Historical coarse cells retain their own cohort labels; repeat indices across campaigns are not contemporaneous pairs.\n')
    with (output/'verification.json').open('x') as f:json.dump(dict(preservation='PASS',new_planned=12,
        new_valid=sum(s['integrity_status']=='VALID' for s in results),input_sha256=before,historical_sha256=plan['historical_sha256']),f,indent=2)
    print(json.dumps(decision,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();analyze(a.output)
