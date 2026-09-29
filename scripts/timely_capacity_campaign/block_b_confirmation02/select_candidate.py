"""Recompute exploratory candidate from immutable Grid02 frame traces."""
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import grid_config as c

PRIOR=c.OUT.parent/'block_b_grid02'
ETA=0.99


def main():
    target=c.OUT/'GRID02_SELECTION_RECOMPUTE.json'
    if target.exists(): raise RuntimeError('Selection recompute already frozen')
    plan=json.loads((PRIOR/'plan.json').read_text())
    h1=json.loads((PRIOR/'analysis01/H1_summary.json').read_text())
    if h1['verdict']!='H1_NOT_SUPPORTED':raise RuntimeError('Grid02 H1 provenance changed')
    with (PRIOR/'analysis01/per_run.csv').open(newline='') as stream:
        prior={r['run_id']:r for r in csv.DictReader(stream)}
    by_condition=defaultdict(dict)
    inspected=[]
    for condition in plan['order']:
        if condition['seconds']!=60:continue
        run_id=condition['run_id'];path=PRIOR/run_id
        manifest=json.loads((path/'manifest.json').read_text())
        summary=json.loads((path/'summary.json').read_text())
        if summary['integrity_status']!='VALID' or summary['terminal_accounting_status']!='PASS' or \
                summary['true_unfinished_after_drain']!=0 or manifest['frequency_restore_ok'] is not True:
            raise RuntimeError('Prior run invalid: '+run_id)
        total=[0]*8;timely=[0]*8;late=[0]*8;expired=[0]*8;seen=set()
        with gzip.open(path/'per_frame.csv.gz','rt',newline='') as stream:
            for row in csv.DictReader(stream):
                if row['phase']!='active':continue
                sid=int(row['stream_id']);fid=int(row['frame_id']);key=(sid,fid)
                if sid not in range(8) or fid not in range(1800) or key in seen:
                    raise RuntimeError('Prior frame identity mismatch: '+run_id)
                seen.add(key);total[sid]+=1
                due=int(row['logical_arrival_ns'])
                if row['terminal_state']=='COMPLETED' and row['completion_timestamp_ns'] not in ('',None):
                    if int(row['completion_timestamp_ns'])-due<=100_000_000:timely[sid]+=1
                    else:late[sid]+=1
                elif row['terminal_state']=='EXPIRED_DROP' and row['expired_drop_ns'] not in ('',None):
                    expired[sid]+=1
                else:raise RuntimeError('Nonexclusive prior terminal state: '+run_id)
        if len(seen)!=14400 or total!=[1800]*8 or any(total[k]!=timely[k]+late[k]+expired[k] for k in range(8)):
            raise RuntimeError('Prior source/terminal accounting mismatch: '+run_id)
        worst=min(timely[k]/total[k] for k in range(8))
        if abs(worst-float(prior[run_id]['worst_stream_TIR']))>1e-12:
            raise RuntimeError('Grid02 analysis/raw worst-TIR mismatch: '+run_id)
        rate=condition['target_service_FPS'];pattern=condition['admission_pattern']
        label=f'L{rate}'+('A' if pattern=='ALIGNED' else 'S')
        repeat=condition['repeat']
        if repeat in by_condition[label]:raise RuntimeError('Duplicate repeat '+label)
        by_condition[label][repeat]=worst
        inspected.append({'run_id':run_id,'condition':label,'repeat':repeat,
            'worst_stream_TIR_from_raw':worst,'per_stream_terminal_partition':'PASS'})
    if len(inspected)!=30:raise RuntimeError('Not 30 measured Grid02 runs')
    table={}
    feasible=[]
    for label,values in sorted(by_condition.items()):
        if set(values)!=set(range(1,6)):raise RuntimeError('Incomplete Grid02 repeats: '+label)
        ordered=[values[i] for i in range(1,6)]
        passed=all(x>=ETA for x in ordered)
        table[label]={'five_worst_stream_TIR':ordered,'exploratory_feasible':passed}
        if passed:feasible.append(label)
    if not feasible:raise RuntimeError('No exploratory-feasible configuration')
    highest=max(int(label[1:4]) for label in feasible)
    candidates=[label for label in feasible if int(label[1:4])==highest]
    selected=candidates[0] if len(candidates)==1 else 'MULTIPLE_CANDIDATES'
    report={'rule':'all five Grid02 repeats worst_stream_TIR >= eta; choose highest Local assigned FPS',
        'eta':ETA,'Grid02_status':'exploratory source only','Grid02_H1':'H1_NOT_SUPPORTED',
        'Grid02_plan_sha256':c.sha(PRIOR/'plan.json'),
        'Grid02_analysis_per_run_sha256':c.sha(PRIOR/'analysis01/per_run.csv'),
        'Grid02_analysis_per_stream_sha256':c.sha(PRIOR/'analysis01/per_stream.csv'),
        'raw_frame_rows_checked':sum(8*1800 for _ in inspected),
        'per_run_raw_reconstruction':inspected,'by_condition':table,
        'exploratory_feasible_set':feasible,'highest_feasible_Local_FPS':highest,
        'candidate':selected,'mu_backlog_lower_used':False}
    if selected!='L200S':
        report['status']='STOP_CANDIDATE_NOT_L200S'
        with target.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
        raise RuntimeError('Candidate is not L200S; preparation stopped')
    report['status']='PASS'
    with target.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({'candidate':selected,'feasible_set':feasible,'inspected_runs':len(inspected)}))


if __name__=='__main__':main()
