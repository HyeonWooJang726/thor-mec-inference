#!/usr/bin/env python3
"""Offline raw comparison; no hardware imports/actions, no historical writes."""
import csv,gzip,json,sys,statistics,re,math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/hybrid_capacity_extension'))
import analyze_hybrid as h
OUT=ROOT/'results/hybrid_coupling_pilot'

def main():
    boundaries=list(csv.DictReader((ROOT/'results/local_capacity_characterization/boundary_summary.csv').open()))
    b=[r for r in boundaries if r['frequency_MHz']=='1575' and r['endpoint_role']=='stable']
    assert len(b)==1 and b[0]['aggregate_admission_FPS']=='200'
    paths=[ROOT/'results/local_capacity_characterization'/rid for rid in json.loads(b[0]['run_ids'])]
    paths.append(ROOT/'results/hybrid_capacity_extension/HYBRID_SMOKE01')
    output=[];details=[];schemas={}
    for path in paths:
        m=json.loads((path/'manifest.json').read_text());s=json.loads((path/'summary.json').read_text())
        f=h.read_csv(path/'per_frame.csv.gz');p=h.read_csv(path/'power_trace.csv.gz')
        schemas[str(path.relative_to(ROOT))]={'frame_fields':list(f[0]),'power_fields':list(p[0])}
        hybrid='HYBRID' in path.name
        replay=(h.summarize if hybrid else h.local_analysis.summarize)(m,f,p)
        assert s['integrity_status']=='VALID' and s['child_returncode']==0 and s['frequency_restore_ok']
        assert replay['integrity_status']=='VALID',replay['errors']
        keys=['source_frames','admitted_frames','aggregate_completed_fps','g_B','avg_power_W','active_concurrency_mean','active_concurrency_peak']
        keys+=['local_service_ms','local_queue_ms'] if hybrid else ['service_ms','queue_wait_ms']
        def eq(a,b):
            if isinstance(a,dict):return all(eq(a[k],b[k]) for k in a)
            if isinstance(a,(int,float)):return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9)
            return a==b
        for key in keys:assert eq(s[key],replay[key]),(path.name,key,s[key],replay[key])
        t0,t1=m['active_start_ns'],m['active_end_ns'];dur=(t1-t0)/1e9
        source=[r for r in f if r['phase']=='active']
        local=[r for r in source if (r.get('placement')=='LOCAL' if hybrid else int(r['admitted'])==1)]
        active=lambda rs,key:[r for r in rs if h.val(r,key) is not None and t0<=h.val(r,key)<t1]
        row=dict(run_id=path.name,configuration='HYBRID_SMOKE' if hybrid else 'HISTORICAL_LOCAL200',seconds=dur,
                 local_assigned_FPS=len(local)/dur,local_completed_FPS=len(active(local,'completion_timestamp_ns'))/dur,
                 g_B_L=s['g_B_L'] if hybrid else s['g_B'],
                 local_active_end_backlog=s['backlogs']['L']['active_end_backlog'] if hybrid else s['backlog_at_active_end'],
                 local_after_drain=s['backlogs']['L']['after_drain_backlog'] if hybrid else s['backlog_after_drain'],
                 active_concurrency_mean=s['active_concurrency_mean'],active_concurrency_peak=s['active_concurrency_peak'],
                 VDD_GPU_integrated_mean_W=s['avg_power_W'],temperature_C=s['temperature'],OC3_delta=s['OC3_delta'],
                 OC3_per_active_second=s['OC3_delta']/dur,supply_status=s['supply_status'],
                 source_FPS=len(source)/dur,decode_ready_FPS=len(active(source,'source_pulled_ns'))/dur,
                 local_ready_FPS=len(active(local,'ready_timestamp_ns'))/dur,
                 total_ready_FPS=s['payload_ready_FPS'] if hybrid else s['aggregate_ready_fps'],
                 actual_freq_MHz=s['actual_freq_mean_MHz'])
        for name,a,z in [('service','inference_start_timestamp_ns','completion_timestamp_ns'),('queue','ready_timestamp_ns','inference_start_timestamp_ns'),('decode_to_ready_proxy','source_pulled_ns','ready_timestamp_ns'),('source_to_decode','logical_arrival_ns','source_pulled_ns')]:
            values=[(h.val(r,z)-h.val(r,a))/1e6 for r in local if h.val(r,a) is not None and h.val(r,z) is not None]
            row.update({name+'_'+k+'_ms':v for k,v in h.quantiles(values).items()})
        # Common cohort sensitivity: only service intervals fully inside first 10 s.
        common=[r for r in local if h.val(r,'inference_start_timestamp_ns')>=t0 and h.val(r,'completion_timestamp_ns')<t0+10**10]
        row['first10_fully_inside_service_mean_ms']=statistics.mean((h.val(r,'completion_timestamp_ns')-h.val(r,'inference_start_timestamp_ns'))/1e6 for r in common)
        rails={}
        for r in p:
            if t0<=int(r['timestamp_ns'])<t1:
                for name,mw in re.findall(r'\b([A-Z][A-Z0-9_]*) (\d+)mW/',r.get('raw_tegrastats','')):rails.setdefault(name,[]).append(int(mw)/1000)
        for name,v in rails.items():row[name+'_sample_mean_W']=statistics.mean(v)
        details.append(dict(raw_replay='PASS',fields_checked=keys,all_completed_latency_cohort='active logical frames, including drain',rail_scope='named rails; VDD_CPU_SOC_MSS is combined CPU/SOC/MSS, not CPU-only',**row))
        output.append(row)
    keys=list(dict.fromkeys(k for row in output for k in row))
    with (OUT/'offline_comparison.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,keys);w.writeheader();w.writerows(output)
    with (OUT/'offline_replay.json').open('x') as f:json.dump(dict(schema=schemas,runs=details),f,indent=2)
    lines=['# Existing Local 200 FPS versus Hybrid smoke','', 'Historical confirmed stable boundary: three 60-s runs; Hybrid: one 10-s valid smoke. No new measurement. Raw replay matched stored metrics for all four runs.', '', '| Metric | Local200 mean ± sample SD (n=3) | Hybrid smoke (n=1) |','|---|---:|---:|']
    for key in keys:
        vs=[r.get(key) for r in output[:3]];v=output[3].get(key)
        if all(isinstance(x,(int,float)) for x in vs) and isinstance(v,(int,float)):
            lines.append(f'| {key} | {statistics.mean(vs):.6f} ± {statistics.stdev(vs):.6f} | {v:.6f} |')
    lines+=['','Both supply_status=NORMAL. Service is a **host** H2D/execute/D2H/synchronization interval, not pure GPU kernel time. Queue is ready→service start. All-frame service/queue quantiles include drain; the separately labeled first10 cohort only includes service intervals wholly within the first 10 seconds.', '', 'The observed Local service interval lengthens while host concurrency remains near two and Local ready supply is 200 FPS. Thus the evidence is not consistent with a simple persistent ready-supply shortfall; it does not identify CPU, memory, GPU, network or scheduling as the cause. Increased host service duration can include host scheduling delays.', '', 'Comparability limitations: 60 s ×3 versus 10 s ×1, 30-s versus 5-s final regression windows, different historical admission/placement phases, extra Hybrid RAW serialization/hash/response bookkeeping, preprocessing implementation and thermal starting conditions. Historical post-decode→ready is a frontend proxy including bookkeeping, **not isolated preprocessing latency**. OC3 raw counts span different durations. Named rail diagnostics are arithmetic means; primary VDD_GPU is canonical time-integrated power.', '', 'No interference verdict or causal claim is made from this one Hybrid smoke. The five-condition pilot fixes Local frame identities and common decode/resize workload to distinguish changes associated with added Edge admission. One ascending pass cannot establish repeat consistency or eliminate time-order effects.']
    (OUT/'offline_comparison.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:40]))
if __name__=='__main__':main()
