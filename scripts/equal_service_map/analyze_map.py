#!/usr/bin/env python3
"""Read-only raw replay into a NEW analysis directory; no experiment execution."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics
import traceback
import numpy as np
from common import ROOT, OUT, PLAN, load_plan, sha, decorate, prior
import analyze_coupling as original

read_csv=original.read_csv

def adapted_summary_source():
    s=original.adapted_summary_source();rep=prior.hybrid.replace_once
    s=rep(s,"e=int(manifest['edge_r'])", "e=int(manifest['edge_r']); local_r=int(manifest['local_r']); target=int(manifest['target_service_FPS']); mode=manifest['supply_mode']")
    s=rep(s,"logical_arrival_ns=val(r,'logical_arrival_ns')),t0,e)", "logical_arrival_ns=val(r,'logical_arrival_ns')),t0,target,mode)")
    s=rep(s,"'LOCAL':int(duration*25)","'LOCAL':int(duration*local_r)")
    s=rep(s,"int(duration*200)","int(duration*8*local_r)",2)
    return s

_ns=dict(original.h.__dict__,decorate=decorate)
exec(compile(adapted_summary_source(),'<equal-service-canonical-raw-replay>','exec'),_ns)
_replay=_ns['summarize']
RAILS=('VDD_GPU','VDD_CPU_SOC_MSS','VIN_SYS_5V0','VIN')


def rail_integrals(manifest,power,completed):
    """Current mW (first field), per rail; canonical endpoint/trapezoid semantics.

    Never sum rails. Reject missing fields rather than bridge unobserved samples.
    Endpoint interpolation integrates observations only, not a power/capacity model.
    """
    t0,t1=manifest['active_start_ns'],manifest['active_end_ns'];duration=(t1-t0)/1e9
    ordered=sorted(power,key=lambda r:int(r['timestamp_ns']));result={}
    for rail in RAILS:
        try:
            stamps=np.array([(int(r['timestamp_ns'])-t0)/1e9 for r in ordered])
            if len(stamps)<2 or stamps[0]>0 or stamps[-1]<duration or np.any(np.diff(stamps)<=0):
                raise ValueError('trace must bracket active interval with strictly increasing timestamps')
            # Use nearest bracketing samples; missing fields anywhere in the needed span fail closed.
            left=max(i for i,x in enumerate(stamps) if x<=0)
            right=min(i for i,x in enumerate(stamps) if x>=duration)
            xs0=stamps[left:right+1];watts=[]
            for row in ordered[left:right+1]:
                match=re.search(r'\b'+re.escape(rail)+r' (\d+)mW/',row.get('raw_tegrastats',''))
                if not match:raise ValueError('missing named instantaneous rail field')
                watts.append(int(match[1])/1000)
            watts=np.asarray(watts);inside=(xs0>0)&(xs0<duration)
            xs=np.concatenate(([0.],xs0[inside],[duration]))
            ys=np.concatenate(([np.interp(0,xs0,watts)],watts[inside],[np.interp(duration,xs0,watts)]))
            if np.max(np.diff(xs))>.5 or np.max(np.diff(xs0))>.5 or not np.isfinite(ys).all() or np.any(ys<0):
                raise ValueError('power gap >0.5s or invalid watts')
            energy=float(np.trapz(ys,xs))
            result[rail]=dict(status='VALID',avg_power_W=energy/duration,active_energy_J=energy,
                J_per_completed_inference=energy/completed if completed else None,samples=len(watts))
        except (ValueError,KeyError,TypeError) as error:
            result[rail]=dict(status='UNAVAILABLE',reason=str(error),avg_power_W=None,active_energy_J=None,J_per_completed_inference=None)
    return result


def summarize(manifest,frames,power):
    s=_replay(manifest,frames,power)
    s.update(experiment='EQUAL_SERVICE_MAP',target_service_FPS=manifest.get('target_service_FPS'),
             supply_mode=manifest.get('supply_mode'),cell=manifest.get('cell'),
             frequency_MHz=manifest.get('requested_freq_MHz'),local_r=manifest.get('local_r'))
    if manifest.get('active_start_ns') is None or manifest.get('active_end_ns') is None:return s
    edge=[r for r in frames if r['phase']=='active' and r.get('placement')=='EDGE']
    for name,a,b in [('edge_inference_ms','edge_inference_start_ns','edge_inference_end_ns'),
                     ('edge_preprocess_ms','edge_preprocess_start_ns','edge_preprocess_end_ns')]:
        s[name]=original.h.quantiles([(int(r[b])-int(r[a]))/1e6 for r in edge if r.get(a) not in ('',None) and r.get(b) not in ('',None)])
    s['rails']=rail_integrals(manifest,power,s['total_completed_active_frames'])
    vin=s['rails']['VIN'];valid_scope=vin['status']=='VALID'
    s.update(power_scope='VIN: Thor module + carrier input; excludes Edge and wall-adapter losses; other rails separate',
        energy_scope_status='THOR_DEVICE_INPUT_CONFIRMED' if valid_scope else 'ENERGY_SCOPE_UNRESOLVED',
        E_device_J=vin['active_energy_J'],device_avg_power_W=vin['avg_power_W'],
        device_J_per_completed_inference=vin['J_per_completed_inference'],
        energy_comparison_eligible=bool(s['queue_stable'] and valid_scope),
        energy_note='Active monotonic time integration only; no Edge/network equipment energy; no rail summation',
        explicit_admission_exclusions=s['admission_skipped_frames'])
    return s


def flatten(obj,prefix=''):
    out={}
    for k,v in obj.items():
        if isinstance(v,dict):out.update(flatten(v,prefix+k+'_'))
        elif isinstance(v,list):out[prefix+k]=json.dumps(v,separators=(',',':'))
        else:out[prefix+k]=v
    return out


def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

# Primary device cost + QoS and resource/protection diagnostics all must not worsen
# before using "dominates". Component rails are never added to VIN.
COSTS=('device_J_per_completed_inference','E_device_J','global_E2E_ms_p95','global_E2E_ms_p99',
       'rails_VDD_GPU_avg_power_W','rails_VDD_CPU_SOC_MSS_avg_power_W','rails_VIN_SYS_5V0_avg_power_W',
       'OC3_delta','g_B_H','backlog_at_active_end','backlog_peak')


def classify(rows):
    groups={m:sorted([r for r in rows if r['supply_mode']==m],key=lambda r:r['repeat']) for m in ('A','B')}
    if any(len(g)!=3 or [r['repeat'] for r in g]!=[1,2,3] or any(r['integrity_status']!='VALID' for r in g) for g in groups.values()):return 'INCONCLUSIVE'
    stable={m:sum(bool(r['queue_stable']) for r in g) for m,g in groups.items()}
    if stable=={'A':3,'B':0}:return 'ONLY_LOCAL_FEASIBLE'
    if stable=={'A':0,'B':3}:return 'ONLY_HYBRID_FEASIBLE'
    if stable!={'A':3,'B':3}:return 'INCONCLUSIVE'
    if any(r.get('energy_scope_status')!='THOR_DEVICE_INPUT_CONFIRMED' or any(not finite(r.get(k)) for k in COSTS) for r in rows):return 'INCONCLUSIVE'
    delta={k:[b[k]-a[k] for a,b in zip(groups['A'],groups['B'])] for k in COSTS}
    # Consistent non-worsening in ALL paired observations; strict benefit in >=1 metric
    # in all three rounds. Screening rule, no significance/universal margin claim.
    plus={k:all(x>0 for x in v) for k,v in delta.items()}
    minus={k:all(x<0 for x in v) for k,v in delta.items()}
    if all(all(x>=0 for x in v) for v in delta.values()) and any(plus.values()):return 'LOCAL_ONLY_DOMINATES'
    if all(all(x<=0 for x in v) for v in delta.values()) and any(minus.values()):return 'HYBRID_DOMINATES'
    if any(plus.values()) and any(minus.values()):return 'TRADEOFF_PARETO'
    return 'INCONCLUSIVE'


def write_csv(path,rows):
    with path.open('x',newline='') as f:
        w=csv.DictWriter(f,list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)


def aggregate(rows):
    stats=[]
    for cell in sorted({r['cell'] for r in rows}):
        group=[r for r in rows if r['cell']==cell]
        keys=sorted({k for r in group for k,v in r.items() if finite(v) and not k.endswith('_ns')})
        for k in keys:
            values=[r[k] for r in group if r['integrity_status']=='VALID' and finite(r.get(k))]
            stats.append(dict(cell=cell,metric=k,planned=3,present=len(group),valid_n=len(values),
                mean=statistics.mean(values) if values else None,sample_SD=statistics.stdev(values) if len(values)>1 else None))
    return stats


def analyze(output):
    if output.exists():raise RuntimeError('No analysis overwrite')
    plan=load_plan();before={};rows=[];errors=[]
    for c in plan['order']:
        d=OUT/c['run_id']
        try:
            for p in d.rglob('*'):
                if p.is_file():before[str(p)]=sha(p)
            m=json.loads((d/'manifest.json').read_text())
            for k,v in [('run_id',c['run_id']),('repeat',c['repeat']),('edge_r',c['edge_r']),('local_r',c['local_r']),('target_service_FPS',c['target_service_FPS']),('supply_mode',c['supply_mode']),('requested_freq_MHz',c['frequency_MHz'])]:
                if m.get(k)!=v:raise ValueError('Run identity mismatch: '+k)
            if m.get('execution_manifest_sha256')!=sha(PLAN):raise ValueError('Plan SHA mismatch')
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            if m.get('child_returncode')!=0 or m.get('PROCESS_LIFECYCLE')!='PASS' or not m.get('status_finalized') or not m.get('frequency_restore_ok'):raise ValueError('Lifecycle/frequency failure')
            if not all(m.get(k) for k in ('active_phase_completed','drain_completed','cleanup_started','cleanup_completed')):raise ValueError('Incomplete lifecycle')
            pre=json.loads((OUT/'frequency_preflight.json').read_text())
            if pre.get('status')!='PASS' or pre.get('plan_sha256')!=sha(PLAN) or m.get('frequency_preflight',{}).get('sha256')!=sha(OUT/'frequency_preflight.json'):raise ValueError('Preflight provenance mismatch')
            pin=m.get('pin_readback_Hz',{})
            if (pin.get('min_freq'),pin.get('max_freq'))!=(c['frequency_MHz']*10**6,)*2:raise ValueError('Pin readback missing/mismatch')
            for k in ('child_returncode','frequency_restore_ok','PROCESS_LIFECYCLE','status_finalized'):s[k]=m[k]
        except Exception:
            error=traceback.format_exc();errors.append(dict(run_id=c['run_id'],error=error))
            s=dict(run_id=c['run_id'],integrity_status='INVALID',queue_stable=False,errors=[error])
        s.update(cell=c['cell'],supply_mode=c['supply_mode'],target_service_FPS=c['target_service_FPS'],repeat=c['repeat'],order_index=c['order_index'])
        rows.append(s)
    flat=[flatten(r) for r in rows];comparisons=[];paired=[]
    for target in (160,176,184,200):
        group=[r for r in flat if r['target_service_FPS']==target]
        comparisons.append(dict(target_service_FPS=target,classification=classify(group),
            A_stable=sum(r['queue_stable'] for r in group if r['supply_mode']=='A'),B_stable=sum(r['queue_stable'] for r in group if r['supply_mode']=='B')))
        for repeat in (1,2,3):
            a=next(r for r in group if r['supply_mode']=='A' and r['repeat']==repeat)
            b=next(r for r in group if r['supply_mode']=='B' and r['repeat']==repeat)
            for key in COSTS+('aggregate_completed_fps','local_completed_FPS','edge_completed_FPS'):
                good=a['integrity_status']==b['integrity_status']=='VALID' and finite(a.get(key)) and finite(b.get(key))
                paired.append(dict(target_service_FPS=target,repeat=repeat,metric=key,A=a.get(key),B=b.get(key),
                    B_minus_A=b[key]-a[key] if good else None,
                    comparison_eligible=bool(good and a['queue_stable'] and b['queue_stable'])))
    output.mkdir(parents=True,exist_ok=False)
    for name,data in [('per_run_metrics.csv',flat),('condition_summary.csv',aggregate(flat)),('equal_service_map.csv',comparisons),('paired_differences.csv',paired)]:write_csv(output/name,data)
    with (output/'replay.json').open('x') as f:json.dump(rows,f,indent=2)
    with (output/'gate_verdict.md').open('x') as f:
        f.write('# Equal-service screening\n\nAll 24 planned runs retained; invalid/missing runs are not imputed. Mean/sample SD are across valid run statistics, not pooled latency quantiles. Three repeats do not establish statistical significance. Mixed stability is INCONCLUSIVE.\n\n')
        for r in comparisons:f.write(f"- S={r['target_service_FPS']}: {r['classification']}; A {r['A_stable']}/3, B {r['B_stable']}/3 stable.\n")
        f.write('\nVIN measures Thor module+carrier input only. No Edge/server/wall-plug energy claim. All rails reported separately; no summation. Dominance requires non-worsening across every frozen metric in all paired rounds and a consistent strict benefit; otherwise repeat-consistent opposing costs give TRADEOFF_PARETO, or INCONCLUSIVE. No coupling model, fitted capacity or automatic winner/controller claim. Small crossover differences need later selected-condition confirmation.\n')
    assert all(sha(p)==v for p,v in before.items()),'Existing artifact changed'
    with (output/'verification.json').open('x') as f:json.dump(dict(input_sha256=before,preservation='PASS',errors=errors,plan_sha256=sha(PLAN)),f,indent=2)
    print(json.dumps(comparisons,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    analyze(ap.parse_args().output)
