#!/usr/bin/env python3
"""Add best-of-grid analysis without changing any frozen runtime/analyzer/plan.

Without --input-analysis, run the frozen pairwise analyzer into a NEW directory,
then add files there. With --input-analysis, read its replay.json and write only
best-of-grid outputs into a separate NEW directory. No inference/network actions.
"""
import argparse
from collections import defaultdict
from fractions import Fraction
import json
import math
from pathlib import Path
import statistics as st
import traceback

import analyze_map_d100 as pairwise
from map_common import PLAN,sha,expected_order

METRICS=('timely_FPS','worst_stream_timely_FPS','worst_stream_TIR',
         'late_completed_FPS','expired_drop_FPS','VIN_J_per_timely_frame')
CELLS={mode:tuple(f'T{target}-{mode}' for target in (160,200,240)) for mode in ('A','B')}


def finite(x):return type(x) in (int,float) and math.isfinite(x)


def audit_row(row,condition):
    errors=[]
    if row.get('integrity_status')!='VALID':errors.append('Raw replay is not VALID')
    for key in ('run_id','cell','repeat','supply_mode','target_service_FPS','deadline_ms'):
        if row.get(key)!=condition[key]:errors.append('Identity/deadline mismatch: '+key)
    streams=row.get('per_stream',[])
    if not isinstance(streams,list) or len(streams)!=8 or any(not isinstance(s,dict) for s in streams):
        errors.append('Malformed per-stream metrics');return errors,None
    if any(type(s.get('stream_id')) is not int for s in streams) or sorted(s['stream_id'] for s in streams)!=list(range(8)):
        errors.append('Missing/duplicate stream identities');return errors,None
    counts=[s.get('timely_completed_frames') for s in streams]
    if any(type(n) is not int or not 0<=n<=1800 for n in counts):
        errors.append('Invalid timely frame counts');return errors,None
    minimum=min(counts)
    # Ranking uses exact integer counts, not a rounding tolerance or tie-break.
    expected=dict(worst_stream_timely_FPS=minimum/60,worst_stream_TIR=minimum/1800,timely_FPS=sum(counts)/60)
    for key,value in expected.items():
        if row.get(key)!=value:errors.append('Count/metric mismatch: '+key)
    if row.get('source_frames')!=14400:errors.append('Physical source denominator mismatch')
    return errors,minimum


def evaluate(results):
    index=defaultdict(list)
    for r in results:index[r.get('run_id')].append(r)
    expected=expected_order();identities={c['run_id'] for c in expected}
    issues=['Unexpected run: '+str(k) for k in index if k not in identities]
    checked={};counts={};candidates=[]
    for c in expected:
        rows=index[c['run_id']];errors=[];count=None
        if len(rows)!=1:errors=['Missing/duplicate planned run']
        else:errors,count=audit_row(rows[0],c)
        key=(c['cell'],c['repeat']);r=rows[0] if len(rows)==1 else {}
        checked[key]=dict(r,**{k:c[k] for k in ('run_id','cell','repeat','supply_mode','target_service_FPS','deadline_ms')},
                          integrity_status='INVALID' if errors else 'VALID')
        counts[key]=count if not errors else None
        issues.extend(f"{c['run_id']}: {e}" for e in errors)
        entry=dict(scope='REPEAT',repeat=c['repeat'],cell=c['cell'],supply_mode=c['supply_mode'],
                   run_id=c['run_id'],integrity_status=checked[key]['integrity_status'])
        for metric in METRICS:entry[metric]=r.get(metric)
        candidates.append(entry)
    for mode,cells in CELLS.items():
        for cell in cells:
            rows=[checked[cell,r] for r in (1,2,3)]
            entry=dict(scope='AGGREGATE',repeat='ALL',cell=cell,supply_mode=mode,
                integrity_status='VALID' if all(r['integrity_status']=='VALID' for r in rows) else 'INVALID')
            for metric in METRICS:
                values=[r.get(metric) for r in rows]
                complete=all(finite(v) for v in values)
                entry[metric]=st.mean(values) if complete else None
                entry[metric+'_sample_SD']=st.stdev(values) if complete else None
            candidates.append(entry)
    selections=[];groups={}
    for repeat in (1,2,3,'ALL'):
        scope='AGGREGATE' if repeat=='ALL' else 'REPEAT'
        for mode,cells in CELLS.items():
            subset=[r for r in candidates if r['scope']==scope and r['repeat']==repeat and r['supply_mode']==mode]
            valid=len(subset)==3 and all(r['integrity_status']=='VALID' for r in subset)
            scores={}
            if valid:
                scores={cell:Fraction(sum(counts[cell,r] for r in (1,2,3)),180) if repeat=='ALL'
                        else Fraction(counts[cell,repeat],60) for cell in cells}
            winners=sorted(cell for cell in scores if scores[cell]==max(scores.values())) if scores else []
            groups[repeat,mode]=dict(valid=valid,winners=winners,score=max(scores.values()) if scores else None)
            for row in subset:row['selected']=row['cell'] in winners
            for winner in winners:
                row=next(r for r in subset if r['cell']==winner)
                selections.append(dict(row,best_group='Best-Local' if mode=='A' else 'Best-Hybrid',
                    selected_configurations=winners,tie_count=len(winners)))
            if not winners:
                selections.append(dict(scope=scope,repeat=repeat,supply_mode=mode,
                    best_group='Best-Local' if mode=='A' else 'Best-Hybrid',selected_configurations=[],
                    integrity_status='INVALID',reason='All three candidates must be available and valid'))
    comparisons=[]
    for repeat in (1,2,3,'ALL'):
        a,b=groups[repeat,'A'],groups[repeat,'B']
        if not a['valid'] or not b['valid']:
            comparisons.append(dict(scope='AGGREGATE' if repeat=='ALL' else 'REPEAT',repeat=repeat,integrity_status='INVALID'))
            continue
        # Retain all tie combinations; do not select another winner using secondary metrics.
        for ac in a['winners']:
            for bc in b['winners']:
                ar=next(s for s in selections if s['repeat']==repeat and s.get('cell')==ac)
                br=next(s for s in selections if s['repeat']==repeat and s.get('cell')==bc)
                entry=dict(scope=ar['scope'],repeat=repeat,integrity_status='VALID',Best_Local=ac,Best_Hybrid=bc,
                    Local_selected_set=a['winners'],Hybrid_selected_set=b['winners'])
                for metric in METRICS:
                    av,bv=ar.get(metric),br.get(metric)
                    entry['Local_'+metric]=av;entry['Hybrid_'+metric]=bv
                    entry['delta_'+metric]=bv-av if finite(av) and finite(bv) else None
                if repeat=='ALL':
                    for metric in METRICS:
                        entry['Local_'+metric+'_sample_SD']=ar.get(metric+'_sample_SD')
                        entry['Hybrid_'+metric+'_sample_SD']=br.get(metric+'_sample_SD')
                        differences=[checked[bc,r].get(metric)-checked[ac,r].get(metric) for r in (1,2,3)
                            if finite(checked[bc,r].get(metric)) and finite(checked[ac,r].get(metric))]
                        entry['delta_'+metric+'_sample_SD']=st.stdev(differences) if len(differences)==3 else None
                comparisons.append(entry)
    verdict='INCONCLUSIVE';reasons=[]
    complete=not issues and all(g['valid'] for g in groups.values())
    consistent=complete and all(len({tuple(groups[r,m]['winners']) for r in (1,2,3)})==1 for m in ('A','B'))
    gains=[groups[r,'B']['score']-groups[r,'A']['score'] for r in (1,2,3)] if complete else []
    if not complete:reasons.append('Incomplete/invalid candidate grid; no silent exclusion of losing or missing cells')
    elif not consistent:reasons.append('Selected operating-point set differs across repeats; this takes priority over positive gains')
    elif all(g>0 for g in gains):verdict='EDGE_TIMELY_CAPACITY_EXTENSION_SUPPORTED'
    elif all(g<=0 for g in gains):verdict='NO_BEST_OF_GRID_EDGE_GAIN'
    else:reasons.append('Best-of-grid worst-stream gain direction is not consistent across all three repeats')
    # Existing pairwise computation/verdict is reused unmodified for context.
    ordered=[checked[c['cell'],c['repeat']] for c in expected]
    try:pairs,_=pairwise.paired(ordered)
    except (KeyError,TypeError,ValueError):pairs=[]
    pair_context=[dict(target_service_FPS=t,verdict=pairwise.verdict([p for p in pairs if p['target_service_FPS']==t])) for t in (160,200,240)]
    decision=dict(verdict=verdict,reasons=reasons,issues=issues,
        repeat_worst_stream_gain_FPS=[float(g) for g in gains],winner_sets_consistent=consistent,
        pairwise_context=pair_context,selection='Max worst-stream timely FPS, exact timely-frame count ranking; ties all retained',
        aggregate_selection='Max over configurations of mean of three per-run worst-stream timely FPS; never mean of per-repeat maxima',
        interpretation='Observed best among three sampled configurations, not an independently validated optimum or significance claim')
    return candidates,selections,comparisons,decision


def analyze(output,input_analysis=None):
    output=Path(output).resolve()
    if output.exists():raise RuntimeError('New output directory required; no overwrite')
    if input_analysis is None:
        pairwise.analyze(output)  # The frozen analyzer and every original output remain unchanged.
        source=output
    else:
        source=Path(input_analysis).resolve()
        if not source.is_dir() or source==output or source in output.parents:
            raise RuntimeError('Existing input analysis and separate new output required')
    before={str(p):sha(p) for p in source.rglob('*') if p.is_file()}
    before[str(PLAN)]=sha(PLAN)
    results=json.loads((source/'replay.json').read_text())
    candidates,selections,comparisons,decision=evaluate(results)
    if not all(sha(Path(p))==digest for p,digest in before.items()):raise RuntimeError('Input changed')
    if input_analysis is not None:output.mkdir(parents=True,exist_ok=False)
    for name,rows in [('best_of_grid_candidates.csv',candidates),('best_of_grid_selections.csv',selections),
                      ('best_of_grid_comparison.csv',comparisons)]:
        pairwise.write_csv(output/name,[pairwise.flatten(r) for r in rows])
    with (output/'best_of_grid_verdict.json').open('x') as f:json.dump(decision,f,indent=2)
    with (output/'best_of_grid_verdict.md').open('x') as f:
        f.write('# D100 Best-Local vs Best-Hybrid\n\n'+decision['verdict']+'\n\n')
        f.write('Primary selection: D100 worst-stream timely FPS. Local candidates T160-A/T200-A/T240-A; Hybrid candidates T160-B/T200-B/T240-B. Each repeat independently selects its observed maximum. Aggregate selects the configuration with maximum mean of3per-run minima; it does not average per-repeat winning configurations. All exact ties retained, with secondary metrics for each tied configuration; no arbitrary tie-break.\n\n')
        f.write('Gate: complete VALID grid required. Changing winner sets across repeats takes priority and yields INCONCLUSIVE, even if all observed gains are positive. Otherwise3strictly positive worst-stream gains => EDGE_TIMELY_CAPACITY_EXTENSION_SUPPORTED; all3nonpositive => NO_BEST_OF_GRID_EDGE_GAIN; mixed signs => INCONCLUSIVE. No invented margin/significance criterion.\n\n')
        f.write('Source-normalized worst-stream TIR uses1800source frames/stream. VIN J/timelyframe retains active Thor-only scope. Missing energy is N/A and is not a capacity-selection criterion. Original pairwise analysis remains intact. Best-of-grid selection uses these observations, not held-out validation; do not claim a global optimum.\n\n')
        for reason in decision['reasons']:f.write('- '+reason+'\n')
    after_ok=all(sha(Path(p))==digest for p,digest in before.items())
    with (output/'best_of_grid_verification.json').open('x') as f:
        json.dump(dict(preservation='PASS' if after_ok else 'FAIL',input_analysis=str(source),input_sha256=before,
            extension_source_sha256=sha(Path(__file__))),f,indent=2)
    if not after_ok:raise RuntimeError('Original analysis changed')
    print(json.dumps(decision,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--input-analysis',type=Path,help='Optional existing frozen-analyzer output; otherwise run its raw replay first')
    args=parser.parse_args();analyze(args.output,args.input_analysis)
