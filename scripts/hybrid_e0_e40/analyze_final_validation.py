#!/usr/bin/env python3
"""Read-only final raw audit, independent event-sweep OLS, and Edge response ledger.

No benchmark/clock/network action. Frozen analyzers stay unchanged; outputs must
be new. Edge-host logs are optional cross-checks, never invented when absent.
"""
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import struct
import sys

sys.dont_write_bytecode = True
import analyze_formal as frozen
from common import ROOT, OUT, PLAN, sha, load_plan
import numpy as np


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def compare(actual, stored, path, checked, failures):
    if isinstance(actual, dict):
        for k,v in actual.items():
            if k not in stored:failures.append(dict(field=path+'.'+k,stored='MISSING',replay=v))
            else:compare(v,stored[k],path+'.'+k,checked,failures)
    elif isinstance(actual,list):
        if not isinstance(stored,list) or len(actual)!=len(stored):
            failures.append(dict(field=path,stored=stored,replay=actual))
        else:
            for i,(x,y) in enumerate(zip(actual,stored)):compare(x,y,path+f'[{i}]',checked,failures)
    else:
        checked[0]+=1
        eq=actual==stored
        if isinstance(actual,float) and isinstance(stored,(int,float)):
            eq=math.isclose(actual,stored,rel_tol=1e-11,abs_tol=1e-9)
        if not eq:failures.append(dict(field=path,stored=stored,replay=actual))


def sweep(rows,t0,t1):
    """Integrate event-level constant backlog segments, independently of row OLS."""
    events=defaultdict(int);arrivals=[];completions=[]
    for r in rows:
        a=int(r['logical_arrival_ns']);c=int(r['completion_timestamp_ns'])
        assert t0<=a<t1 and c>=a
        arrivals.append(a);completions.append(c);events[a]+=1;events[c]-=1
    arrivals.sort();completions.sort()
    left=t1-30*10**9;terms=[];area=[];q=peak=0;last=t0;peak_at=None;minimum=0
    for stamp,delta in sorted(events.items()):
        x,y=max(last,left),min(stamp,t1)
        if y>x:
            u,v=(x-left)/1e9,(y-left)/1e9
            terms.append(q*((v-15)**2-(u-15)**2)/2)
            area.append(q*(v-u))
        q+=delta;minimum=min(minimum,q)
        if stamp<t1 and q>peak:peak=q;peak_at=(stamp-t0)/1e9
        last=stamp
    if last<t1:
        u=(max(last,left)-left)/1e9
        terms.append(q*(15**2-(u-15)**2)/2);area.append(q*(30-u))
    assert minimum>=0 and q==0
    count=lambda t:bisect_left(arrivals,t)-bisect_left(completions,t)
    return dict(g_B=math.fsum(terms)/(30**3/12),peak_backlog=peak,peak_time_s=peak_at,
        active_end_backlog=count(t1),after_drain_backlog=q,min_backlog=minimum,
        window_start_ns=left,window_end_ns=t1,window_mean_backlog=math.fsum(area)/30,
        at_seconds={str(s):count(t0+s*10**9) for s in range(61)},
        window_arrivals=bisect_left(arrivals,t1)-bisect_left(arrivals,left),
        window_completions=bisect_left(completions,t1)-bisect_left(completions,left))


def response_ledger(path):
    ids=[]
    with path.open('rb') as f:
        while True:
            chunk=f.read(13208)  # !Q request ID + logits(8400) + boxes(4800), float32.
            if not chunk:break
            assert len(chunk)==13208,'truncated response binary'
            ids.append(struct.unpack('!Q',chunk[:8])[0])
            assert np.isfinite(np.frombuffer(chunk[8:],dtype=np.float32)).all()
    return ids


def mean_sd(values):
    if not values or any(v is None for v in values):return 'N/A'
    return f'{statistics.mean(values):.6f} ± {statistics.stdev(values):.6f}' if len(values)>1 else str(values[0])


def table(rows,keys):
    def fmt(v):return 'N/A' if v is None else f'{v:.6f}' if isinstance(v,float) else str(v)
    return '\n'.join(['| '+' | '.join(keys)+' |','| '+' | '.join('---' for _ in keys)+' |']+
        ['| '+' | '.join(fmt(r.get(k)) for k in keys)+' |' for r in rows])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=OUT/'final_analysis01')
    ap.add_argument('--edge-dir',type=Path,default=OUT/'edge_formal01')
    args=ap.parse_args()
    if args.output.exists():raise RuntimeError('Refusing to overwrite analysis')
    plan=load_plan();before={};checks=[];errors=[];checked=[0];rows=[];ledgers=[];per_stream=[];waves={};r5_raw=None
    def protect(p):
        if p.is_dir():
            for x in p.rglob('*'):
                if x.is_file():before[str(x)]=sha(x)
        else:before[str(p)]=sha(p)
    protect(PLAN);protect(OUT/'frequency_preflight.json')
    for p,digest in plan['source_sha256'].items():
        assert sha(ROOT/p)==digest,('source mismatch',p)
        protect(ROOT/p)
    edge_available=args.edge_dir.is_dir()
    if edge_available:protect(args.edge_dir)
    else:checks.append('Independent Edge-host directory absent; use Thor raw returned timestamps, response bytes, READY/FINAL. No claim of independent Edge-host log replay.')
    pre=json.loads((OUT/'frequency_preflight.json').read_text())
    assert pre['status']=='PASS' and pre['plan_sha256']==sha(PLAN)
    masks=[]
    for c in plan['order']:
        d=OUT/c['run_id'];protect(d)
        m=json.loads((d/'manifest.json').read_text());stored=json.loads((d/'summary.json').read_text())
        frames=frozen.read_csv(d/'per_frame.csv.gz');power=frozen.read_csv(d/'power_trace.csv.gz')
        s=frozen.summarize(m,frames,power)
        compare(s,stored,c['run_id'],checked,errors)
        assert s['integrity_status']=='VALID',s['errors']
        assert m['execution_manifest_sha256']==sha(PLAN) and m['frequency_preflight']['sha256']==sha(OUT/'frequency_preflight.json')
        for k,v in [('child_returncode',0),('PROCESS_LIFECYCLE','PASS'),('status_finalized',True),('frequency_restore_ok',True)]:
            assert m.get(k)==stored.get(k)==v,(c['run_id'],k)
            s[k]=v
        assert all(m.get(k) for k in ('active_phase_completed','drain_completed','cleanup_completed','premeasurement_queue_empty'))
        t0,t1=m['active_start_ns'],m['active_end_ns'];assert t1-t0==60*10**9
        active=[r for r in frames if r['phase']=='active'];assert len(active)==14400
        identity=[(int(r['stream_id']),int(r['frame_id'])) for r in active]
        assert len(set(identity))==14400
        local=[r for r in active if r['placement']=='LOCAL'];edge=[r for r in active if r['placement']=='EDGE']
        admitted=[r for r in active if int(r['admitted'])==1]
        assert len(local)==12000 and len(edge)==480*c['edge_r'] and len(admitted)==len(local)+len(edge)
        masks.append({(int(r['stream_id']),int(r['frame_id'])) for r in local})
        for sid in range(8):
            sr=[r for r in active if int(r['stream_id'])==sid]
            l=sum(r['placement']=='LOCAL' for r in sr);e=sum(r['placement']=='EDGE' for r in sr);sk=sum(r['placement']=='SKIP' for r in sr)
            gap=len(sr)-l-e-sk;assert (len(sr),l,e,gap)==(1800,1500,60*c['edge_r'],0)
            per_stream.append(dict(run_id=c['run_id'],stream_id=sid,source=len(sr),local_assigned=l,edge_assigned=e,
                explicit_exclusions=sk,terminal_placement_gap=gap,
                local_drain_completed=sum(r['placement']=='LOCAL' and bool(r['completion_timestamp_ns']) for r in sr),
                edge_drain_completed=sum(r['placement']=='EDGE' and bool(r['completion_timestamp_ns']) for r in sr)))
        for label,rr in [('H',admitted),('L',local),('E',edge)]:
            b=sweep(rr,t0,t1);waves[c['run_id'],label]=b
            assert math.isclose(b['g_B'],s['g_B_'+label],rel_tol=1e-10,abs_tol=1e-9),(c['run_id'],label,b['g_B'],s['g_B_'+label])
            for k in ('peak_backlog','active_end_backlog','after_drain_backlog'):assert b[k]==s['backlogs'][label][k]
            completed=sum(t0<=int(r['completion_timestamp_ns'])<t1 for r in rr)
            field={'H':'aggregate_completed_fps','L':'local_completed_FPS','E':'edge_completed_FPS'}[label]
            assert completed/60==s[field]
        assert math.isclose(s['g_B_H'],s['g_B_L']+s['g_B_E'],abs_tol=1e-9)
        ef=m.get('edge_final',{});binary_ids=[];host_check='NOT_APPLICABLE'
        if edge:
            assert json.loads((d/'edge_final.json').read_text())==ef
            assert json.loads((d/'edge_ready.json').read_text())==m['edge_ready']
            binary_ids=response_ledger(d/'edge_responses.bin')
            assert Counter(binary_ids)==Counter(int(r['edge_request_id']) for r in edge)==Counter(range(2400))
            assert all(r['payload_sha256']==r['raw_sha256'] for r in edge)
            assert all(ef[k]==2400 for k in ('received','completed','responses_sent'))
            host_check='UNAVAILABLE'
            if edge_available:
                ed=args.edge_dir/c['run_id'];es=json.loads((ed/'summary.json').read_text())
                er=frozen.read_csv(ed/'requests.csv');indexed={int(r['request_id']):r for r in er}
                assert len(er)==len(indexed)==2400 and es['integrity_status']=='VALID'
                for r in edge:
                    q=indexed[int(r['edge_request_id'])]
                    for k in ('receive_complete_ns','queue_enter_ns','queue_start_ns','preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns'):
                        assert int(q[k])==int(r['edge_'+k]),(c['run_id'],k)
                    assert q['raw_sha256']==r['raw_sha256']
                for k in ('received','completed','responses_sent','drops','duplicates','queue_cap_saturation','drain_completed'):
                    assert es[k]==ef[k]
                host_check='PASS'
        else:
            assert m['edge_usage']=='NOT_USED' and ef['status']=='NOT_USED'
            assert not (d/'edge_responses.bin').exists()
        ledger=dict(run_id=c['run_id'],source_duplicates=len(identity)-len(set(identity)),
            missing_local=sum(not r['completion_timestamp_ns'] for r in local),
            missing_edge=sum(not r['completion_timestamp_ns'] for r in edge),
            response_binary_records=len(binary_ids),response_duplicates=len(binary_ids)-len(set(binary_ids)),
            drops=int(bool(m.get('forced_drop')))+ef.get('drops',0),
            queue_cap_saturation=bool(m.get('queue_cap_saturation') or m.get('queue_overflow') or ef.get('queue_cap_saturation')),
            placement_accounting_correct=s['placement_accounting_correct'],drain_complete=s['backlog_after_drain']==0,
            max_terminal_placement_gap=0,Edge_reported_status=ef.get('integrity_status','NOT_USED'),Edge_host_raw_crosscheck=host_check)
        assert not any(ledger[k] for k in ('source_duplicates','missing_local','missing_edge','response_duplicates','drops','queue_cap_saturation'))
        ledgers.append(ledger)
        s.update(repeat=c['repeat'],edge_r=c['edge_r'],order_index=c['order_index'],**{k:v for k,v in ledger.items() if k!='run_id'})
        rows.append(s)
        if c['run_id']=='HEF_R5_E40_P01':r5_raw=(m,active)
    assert all(mask==masks[0] for mask in masks)
    historical=[]
    for rid in plan['baseline_local240_run_ids']:
        d=ROOT/'results/k8_workload_gate'/rid;protect(d)
        m=json.loads((d/'manifest.json').read_text());stored=json.loads((d/'summary.json').read_text())
        fr=frozen.read_csv(d/'per_frame.csv.gz');pw=frozen.read_csv(d/'power_trace.csv.gz')
        s=frozen.prior.h.local_analysis.summarize(m,fr,pw)
        compare(s,stored,rid,checked,errors)
        rr=[r for r in fr if r['phase']=='active' and int(r['admitted'])==1]
        b=sweep(rr,m['active_start_ns'],m['active_end_ns']);assert math.isclose(b['g_B'],s['g_B'],abs_tol=1e-9)
        historical.append(dict(run_id=rid,offered_FPS=len(rr)/60,completed_FPS=s['aggregate_completed_fps'],g_B=s['g_B'],
            active_end_backlog=s['backlog_at_active_end'],after_drain_backlog=s['backlog_after_drain'],supply_status=s['supply_status'],
            hardware_status=s['hardware_status'],OC3_delta=s['OC3_delta'],integrity_status=s['integrity_status'],
            p95_ms=s['latency_ms']['p95'],p99_ms=s['latency_ms']['p99']))
    if errors:
        print(json.dumps(errors,indent=2));raise RuntimeError('Stored/raw mismatch; no final verdict')
    result=frozen.verdict(rows);flat=[frozen.flatten(s) for s in rows]
    stats=frozen.aggregate(flat)
    detailed=[]
    for r in stats:
        rr=sorted([x for x in flat if x['edge_r']*8==r['edge_FPS']],key=lambda x:x['repeat'])
        detailed.append(dict(r,**{f'R{x["repeat"]}':x.get(r['metric']) for x in rr}))
    r5='HEF_R5_E40_P01';trajectory=[]
    for sec in range(61):trajectory.append(dict(seconds=sec,**{f'B_{p}':waves[r5,p]['at_seconds'][str(sec)] for p in ('H','L','E')}))
    m,rr=r5_raw;t0=m['active_start_ns'];edge=[r for r in rr if r['placement']=='EDGE']
    stalls={}
    for name,a,b in [('client_pending','payload_ready_ns','socket_submission_ns'),('socket_send','socket_submission_ns','socket_send_complete_ns'),
                     ('Edge_E2E','logical_arrival_ns','completion_timestamp_ns')]:
        r=max(edge,key=lambda r:int(r[b])-int(r[a]))
        stalls[name]=dict(request_id=int(r['edge_request_id']),duration_ms=(int(r[b])-int(r[a]))/1e6,
                         start_Thor_seconds=(int(r[a])-t0)/1e9,end_Thor_seconds=(int(r[b])-t0)/1e9)
    diag=dict(run_id=r5,active_start_ns=t0,active_end_ns=m['active_end_ns'],
        method='independent piecewise-constant event sweep: integral (t-45)*B(t) dt over [30,60], denominator 2250 s^3; drain excluded',
        paths={p:waves[r5,p] for p in ('H','L','E')},max_observed_delays=stalls,
        interpretation='Coherent recorded Edge backlog buildup and recovery, not a regression arithmetic/window artifact. Physical cause of send/client delay is not identified. Retained without outlier removal.')
    summaries=[]
    for e in (0,5):
        group=[r for r in rows if r['edge_r']==e]
        summaries.append(dict(condition=f'E{8*e}',n=5,valid=sum(r['integrity_status']=='VALID' for r in group),
            stable=sum(r['queue_stable'] for r in group),**{k:mean_sd([r[k] for r in group]) for k in (
            'total_offered_FPS','local_completed_FPS','edge_completed_FPS','aggregate_completed_fps','completion_offered_ratio',
            'g_B_H','g_B_L','g_B_E','backlog_peak','backlog_at_active_end','backlog_after_drain','avg_power_W','temperature','OC3_delta')}))
    lines=['# Formal E0/E40 final raw validation','',result,'',
        f'Raw replay: {checked[0]} scalar checks against stored summaries, zero mismatch. Independent event-sweep slopes/peaks/end/drain '
        'agree with frozen per-request-integral OLS for all ten formal and three historical runs. All input artifacts preserved.', '',
        '## Scope and integrity', '',
        'Thor ten runs: raw frame/power traces, per-stream IDs, source timestamps, complete placement/admission ledger, lifecycle, frequency preflight/restore. '
        'Each E40 additionally verifies all2400 binary response IDs, finite output values, payload-hash round trips, returned Edge timestamps and persisted READY/FINAL. '
        'E0 excludes2400 complementary source frames by design, with no network; this is not a drop of admitted work.', '',
        f'Independent Edge-host directory available: {edge_available}. '+
        ('Edge per-request logs cross-check exactly against returned timestamps/hashes and FINAL counts.' if edge_available else
         'Requested edge_formal01 is absent locally. Edge5/5 VALID is verified from the server FINAL reports preserved on Thor, not independently replayed Edge-host files. '
         'Thor-observable returned completion/accounting and the frozen feasibility criterion can still be verified; this archival limitation remains explicit.'), '',
        table(ledgers,['run_id','drops','missing_local','missing_edge','response_duplicates','queue_cap_saturation','drain_complete','max_terminal_placement_gap','Edge_host_raw_crosscheck']), '',
        '## Conditions: mean ± sample SD', '',table(summaries,list(summaries[0])), '',
        '## All ten observations', '',table(flat,['run_id','total_offered_FPS','local_completed_FPS','edge_completed_FPS','aggregate_completed_fps',
            'completion_offered_ratio','g_B_H','g_B_L','g_B_E','backlog_peak','backlog_at_active_end','backlog_after_drain','queue_classification','supply_status','hardware_status','OC3_delta']), '',
        'Full metrics: per_run_metrics.csv and condition_summary.csv (R1–R5, mean, sample SD for each metric). '
        'Latency distributions include all active-logical completions including drain, matching frozen semantics. Run quantiles are averaged, not pooled. '
        'E0 Edge latencies are N/A. Host clocks are never subtracted across machines. Power is VDD_GPU canonical integrated mean; CPU/SOC rail is a telemetry sample mean. '
        'OC3 delta is the frozen before/after run counter diagnostic, not an invalidation rule.', '',
        '## Historical Local-only full240 versus E40', '',table(historical,list(historical[0])), '',
        'The historical baseline uses K8/C_L2/B1/FP16/1575 MHz, the same source mapping, 60-s active interval and final30-s unified backlog criterion. '
        'Historical Local-only assigns all240 FPS Local; formal E40 shares resize and deterministically sends40 FPS over RAW640 while keeping200 FPS Local. '
        'The Local engine is unchanged. The preprocessing/harness plumbing and execution session differ; this is a historical, not a simultaneous randomized Local240 control. '
        'All historical repeats remain separate, frontend NORMAL and protection-limited; no pooling or new Local240 run.', '',
        '## R5/E40 negative slope audit', '',
        f'Window absolute monotonic ns: [{t0+30*10**9}, {m["active_end_ns"]}]; relative [30,60] s. No drain observations enter OLS.', '',
        table([dict(path=p,**{k:v for k,v in waves[r5,p].items() if not isinstance(v,dict)}) for p in ('H','L','E')],
              ['path','g_B','peak_backlog','peak_time_s','active_end_backlog','after_drain_backlog','window_arrivals','window_completions']), '',
        table([r for r in trajectory if r['seconds'] in (20,23,25,27,30,35,38,39,40,50,60)],['seconds','B_H','B_L','B_E']), '',
        'The final window starts with existing Edge backlog and includes its recovery. Negative global slope is therefore a recorded backlog decrease, '
        'not deleted data, a shifted regression window, drain leakage or a numerical sign error. The Local component is positive and is reported separately. '
        'A negative OLS slope is not a promise of uniformly low delay or monotonic backlog. Large transient Edge latency remains in the quantiles. '
        'The client-pending and send-duration maxima are recorded in r5_e40_diagnostic.json; they locate observed waiting but do not prove a network/GPU causal mechanism.', '',
        '## Paper claim and limitations', '',
        ('Under the measured testbed configuration, the full 240-FPS workload was unsustainable under Local-only execution, whereas allocating '
         '200 FPS to Local execution and 40 FPS to the Edge sustained the same 240-FPS workload.' if result=='CAPACITY_EXTENSION_CONFIRMED' else
         'The proposed capacity-extension claim is not confirmed by the frozen criterion.'), '',
        'If confirmed, the scope is five60-s formal repetitions under this testbed and the declared backlog criterion, supported by a separate historical '
        'Local-only baseline. Active completion is slightly below offered rate because residual work drains after the active window. '
        'This is not zero-backlog, deadline/latency-guarantee, indefinite sustainability, energy superiority or universal network/workload/platform evidence. '
        'R5 transient recovery and repeated OC3 are retained. Coupling pilot verdict is unchanged.', '',
        '## Every requested metric by repeat', '']
    for e in (0,40):
        lines += [f'### E{e}', '',table([r for r in detailed if r['edge_FPS']==e],['metric','R1','R2','R3','R4','R5','mean','sample_SD']), '']
    assert all(sha(Path(p))==digest for p,digest in before.items())
    args.output.mkdir(parents=True,exist_ok=False)
    frozen.write_csv(args.output/'per_run_metrics.csv',flat)
    frozen.write_csv(args.output/'condition_summary.csv',detailed)
    frozen.write_csv(args.output/'per_stream_accounting.csv',per_stream)
    frozen.write_csv(args.output/'historical_local240.csv',historical)
    frozen.write_csv(args.output/'r5_e40_backlog_1s.csv',trajectory)
    save(args.output/'r5_e40_diagnostic.json',diag)
    with (args.output/'gate_verdict.md').open('x') as f:f.write('\n'.join(lines)+'\n')
    save(args.output/'verification.json',dict(verdict=result,raw_replay_scalar_checks=checked[0],mismatches=errors,
        independent_event_sweep='PASS',Edge_host_directory=str(args.edge_dir),Edge_host_raw_available=edge_available,
        input_sha256=before,preservation='PASS',scope_notes=checks,no_GPU_run=True,no_network_run=True))
    assert all(sha(Path(p))==digest for p,digest in before.items())
    print(result);print(json.dumps(summaries,indent=2));print('R5',json.dumps(diag,indent=2))


if __name__=='__main__':main()
