#!/usr/bin/env python3
"""Formal E0/E40 raw replay; same canonical accounting, power and OLS definitions."""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import traceback

from common import ROOT, OUT, PLAN, load_plan, sha
import analyze_coupling as prior
read_csv = prior.read_csv


def summarize(manifest, frames, power):
    s = prior.summarize(manifest, frames, power)
    if manifest.get('active_start_ns') is None:
        return s
    edge = [r for r in frames if r['phase']=='active' and r.get('placement')=='EDGE']
    for name, a, b in [('edge_inference_ms','edge_inference_start_ns','edge_inference_end_ns'),
                       ('edge_preprocess_ms','edge_preprocess_start_ns','edge_preprocess_end_ns')]:
        s[name] = prior.h.quantiles([(int(r[b])-int(r[a]))/1e6 for r in edge if r.get(a) not in ('',None) and r.get(b) not in ('',None)])
    s.update(experiment='FORMAL_HYBRID_E0_E40',
             explicit_admission_exclusions=s['admission_skipped_frames'],
             inference_timing_scope='Edge host H2D/execute/D2H/synchronize interval, not kernel-only')
    return s


def flatten(obj, prefix=''):
    out = {}
    for k,v in obj.items():
        if isinstance(v,dict):out.update(flatten(v,prefix+k+'_'))
        elif not isinstance(v,list):out[prefix+k]=v
    return out


def verdict(rows):
    if len(rows)!=10 or any(r.get('integrity_status')!='VALID' for r in rows):
        return 'INCONCLUSIVE'
    e0=[r for r in rows if r['edge_r']==0];e40=[r for r in rows if r['edge_r']==5]
    if len(e0)!=5 or len(e40)!=5:return 'INCONCLUSIVE'
    if sum(not r['queue_stable'] for r in e0)>=2:return 'HARNESS_BASELINE_NOT_STABLE'
    if all(r['queue_stable'] for r in e0):
        if all(r['queue_stable'] and r['total_offered_FPS']==240 and r['placement_accounting_correct']
               and r['backlog_after_drain']==0 for r in e40):return 'CAPACITY_EXTENSION_CONFIRMED'
        if sum(not r['queue_stable'] for r in e40)>=2:return 'CAPACITY_EXTENSION_NOT_CONFIRMED'
    return 'INCONCLUSIVE'


def aggregate(rows):
    metrics=sorted({k for r in rows for k,v in r.items() if prior.finite(v)
                    and not k.endswith('_ns') and k not in ('repeat','order_index','edge_r','K','C_L','C_E','child_pid','child_returncode')})
    result=[]
    for e in (0,5):
        group=[r for r in rows if r['edge_r']==e]
        for metric in metrics:
            values=[r.get(metric) for r in group if r['integrity_status']=='VALID' and prior.finite(r.get(metric))]
            result.append(dict(edge_FPS=8*e,metric=metric,planned=5,present=len(group),
                valid_n=len(values),mean=statistics.mean(values) if values else None,
                sample_SD=statistics.stdev(values) if len(values)>1 else None))
    return result


def write_csv(path, rows):
    with path.open('x',newline='') as f:
        w=csv.DictWriter(f,list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)


def analyze(output):
    if output.exists():raise RuntimeError('No analysis overwrite')
    plan=load_plan();rows=[];before={};replay_errors=[]
    for c in plan['order']:
        d=OUT/c['run_id']
        try:
            for p in d.rglob('*'):
                if p.is_file():before[str(p)]=sha(p)
            m=json.loads((d/'manifest.json').read_text())
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            if m.get('execution_manifest_sha256')!=sha(PLAN):raise ValueError('Plan SHA mismatch')
            for k,v in (('run_id',c['run_id']),('repeat',c['repeat']),('edge_r',c['edge_r']),('order_index',c['order_index'])):
                if m.get(k)!=v:raise ValueError('Condition identity mismatch '+k)
            for k in ('child_returncode','frequency_restore_ok','PROCESS_LIFECYCLE','status_finalized'):
                s[k]=m.get(k)
            if (s['child_returncode']!=0 or not s['frequency_restore_ok'] or
                s['PROCESS_LIFECYCLE']!='PASS' or not s['status_finalized']):raise ValueError('Process/lifecycle/frequency failure')
            pre=json.loads((OUT/'frequency_preflight.json').read_text())
            if pre.get('status')!='PASS' or pre.get('plan_sha256')!=sha(PLAN):raise ValueError('Frequency preflight invalid')
            if m.get('frequency_preflight',{}).get('sha256')!=sha(OUT/'frequency_preflight.json'):raise ValueError('Run preflight provenance mismatch')
        except Exception:
            err=traceback.format_exc();replay_errors.append(dict(run_id=c['run_id'],error=err))
            s=dict(run_id=c['run_id'],integrity_status='INVALID',queue_stable=False,errors=[err])
        s.update(edge_r=c['edge_r'],repeat=c['repeat'],order_index=c['order_index'])
        rows.append(s)
    result=verdict(rows);flat=[flatten(s) for s in rows];stats=aggregate(flat)
    historical=[]
    for rid in plan['baseline_local240_run_ids']:
        p=ROOT/'results/k8_workload_gate'/rid/'summary.json';before[str(p)]=sha(p)
        s=json.loads(p.read_text())
        historical.append(dict(run_id=rid,provenance='HISTORICAL_LOCAL_ONLY_NOT_POOLED',offered_FPS=240,
            completed_FPS=s['aggregate_completed_fps'],g_B=s['g_B'],active_end_backlog=s['backlog_at_active_end'],
            after_drain=s['backlog_after_drain'],p95_ms=s['latency_ms']['p95'],p99_ms=s['latency_ms']['p99'],supply_status=s['supply_status']))
    output.mkdir(parents=True,exist_ok=False)
    write_csv(output/'per_run_metrics.csv',flat);write_csv(output/'condition_summary.csv',stats)
    write_csv(output/'historical_local240.csv',historical)
    lines=['# Formal E0/E40 validation','',result,'',
        'All ten planned IDs are shown; missing/corrupt/lifecycle-failed runs are INVALID. No retry or imputation. '
        'Mean/sample SD use integrity-valid run-level statistics (ddof=1), not pooled quantiles. E0 Edge latency is N/A. '
        'OC3 is a protection annotation, not invalidation. VDD_GPU is the canonical time-weighted mean; other rail diagnostics '
        'are sample means. Service overlap is not GPU kernel overlap.','',
        '| Run | Validity | STABLE | Local FPS | Edge FPS | Total FPS | g_B,H | Drain end |',
        '|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append('| '+' | '.join(str(r.get(k,'N/A')) for k in ('run_id','integrity_status','queue_stable',
            'local_completed_FPS','edge_completed_FPS','aggregate_completed_fps','g_B_H','backlog_after_drain'))+' |')
    for e in (0,5):
        rr=[r for r in rows if r['edge_r']==e]
        lines+=['',f'E{8*e}: {sum(r["integrity_status"]=="VALID" for r in rr)}/5 VALID; '
                f'{sum(r.get("queue_stable",False) for r in rr)}/5 STABLE.']
    lines+=['','Historical Local-only 240 FPS is a separate baseline, never pooled. It uses the same K8 sources, C_L2/B1/1575 MHz, '
        '60-s active/final-30-s regression and canonical B(t), but assigns all 240 FPS Local and uses the original Local preprocessing/harness. '
        'This campaign shares resize then branches: E0 excludes 40 FPS after decode/resize and has no network; E40 assigns 200/40 with '
        'the frozen stagger. Both preserve 240-FPS source/decode/resize and identical Local frame IDs. Latencies include natural-drain completions. '
        'Historical engine/pipeline differences in representation/extra transport hooks are not a contemporaneous randomized Local240 control. '
        'The P02 verdict remains COUPLING_NOT_SUPPORTED_BY_PILOT; no coupling or energy superiority claim is made.','',
        'Repeated unstable means at least two integrity-valid runs; a single inconsistent run is INCONCLUSIVE. '
        'Any missing/invalid run makes the campaign INCONCLUSIVE. Full confirmation requires 5/5 in BOTH conditions.']
    if result=='CAPACITY_EXTENSION_CONFIRMED':
        lines+=['','Under this measured testbed, historical Local-only full 240-FPS service was unstable, while 200-FPS Local '
                'plus 40-FPS Edge assignment is stable in all five formal repeats. This is not a guarantee for other networks/workloads.']
    with (output/'gate_verdict.md').open('x') as f:f.write('\n'.join(lines)+'\n')
    assert all(sha(p)==v for p,v in before.items())
    with (output/'verification.json').open('x') as f:
        json.dump(dict(verdict=result,replay_errors=replay_errors,input_sha256=before,preservation='PASS',
                       plan_sha256=sha(PLAN),GPU_executed=False,network_executed=False),f,indent=2)
    print(result)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    analyze(ap.parse_args().output)
