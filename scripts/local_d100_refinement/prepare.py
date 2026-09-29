#!/usr/bin/env python3
"""Prepare only: immutable12-run Local-only plan, with labeled historical evidence."""
from datetime import datetime,timezone
import json
from pathlib import Path
from refinement_common import ROOT,OUT,PLAN,sha,expected_order,placement_manifest,GRID,best_grid


def build_plan(reference='repeat_best_envelope'):
    if reference not in ('repeat_best_envelope','fixed_mean_winner'):raise ValueError('Unknown comparison reference')
    old=json.loads((ROOT/'results/d100_timely_capacity_map/plan.json').read_text())
    for rel,digest in old['source_sha256'].items():
        if sha(ROOT/rel)!=digest:raise RuntimeError('Frozen source changed: '+rel)
    sources=dict(old['source_sha256'])
    for folder in ('scripts/d100_timely_capacity_map','scripts/local_d100_refinement'):
        sources.update({str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/folder).glob('*.py'))})
    historical={}
    for folder in ('results/d100_timely_capacity_map/analysis01','results/d100_timely_capacity_map/best_of_grid01'):
        historical.update({str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/folder).iterdir()) if p.is_file()})
    historical['results/d100_timely_capacity_map/plan.json']=sha(ROOT/'results/d100_timely_capacity_map/plan.json')
    history_path='results/d100_timely_capacity_map/analysis01/replay.json'
    rows=json.loads((ROOT/history_path).read_text());decision=best_grid.evaluate(rows)[-1]
    if decision['issues']:raise RuntimeError('Historical D100 grid invalid')
    preserved=json.loads((ROOT/'results/d100_timely_capacity_map/best_of_grid01/best_of_grid_verdict.json').read_text())
    if decision!=preserved:raise RuntimeError('Historical Best-of-grid replay mismatch')
    evidence=dict(old['authoritative_evidence_sha256']);evidence.update(historical)
    runtime=dict(old['runtime'],C_E=None,edge_port=None,Edge_warmup_inferences=0,network_connection=False)
    return dict(campaign='LOCAL_D100_TIMELY_REFINEMENT',attempt='P01',freeze_status='FROZEN_LOCAL_D100_REFINEMENT_V1',
        frozen_utc=datetime.now(timezone.utc).isoformat(),order=expected_order(),smoke=[],deadlines_ms=[100],
        source_phase_ns=[0]*8,placement=placement_manifest(),runtime=runtime,
        inputs=old['inputs'],engine_provenance=old['engine_provenance'],cache=old['cache'],edge_host=old['edge_host'],
        unused_edge_provenance='Cache/IP retained solely for existing read-only capability checks; no Edge connection or warmup',
        source_sha256=sources,authoritative_evidence_sha256=evidence,historical_sha256=historical,history_replay=history_path,
        historical_best_grid_verdict=preserved,final_local_grid=list(GRID),
        rule=old['rule'],accounting=old['accounting'],energy=old['energy'],comparison_reference=reference,
        selection='max(mean of3per-run worst-stream timelyFPS) over7Local configurations; repeat winners also retained; exact primary ties ALL retained',
        tie_diagnostics='Aggregate timelyFPS descending, then VINJ/timelyframe ascending, only diagnostic presentation; no override of primary ties',
        role_rule='Strict non-overlap of observed3repeat worst-streamFPS ranges for selected Local and historical Hybrid reference. Equal/overlapping ranges or invalid/incomplete grid => EDGE_ROLE_INCONCLUSIVE. All primary ties must agree. No significance/CI claim.',
        interpretation='Historical coarse cells and new refinement cells retain cohort provenance. Repeated index across campaigns is not contemporaneous pairing. No final Local/Edge superiority before execution; no global/exact optimum claim.',
        policy='Prepare only. Future explicitly authorized12runs of60s,3repeats, fixed order, no extra smoke/retry. Existing helper pin/readback/restore preflight once; per-run1575pin and315–1575restore. No Edge/server/bundle/deployment needed. No settings/package change.')


def write_plan(plan):
    OUT.mkdir(parents=True,exist_ok=False)
    with PLAN.open('x') as f:json.dump(plan,f,indent=2);f.write('\n')
    lines=['# D100 Local-only Timely Capacity Refinement','', '**WAITING_FOR_LOCAL_D100_REFINEMENT**','',
        'Preparation only. No GPU workload, clock-control preflight or network experiment executed. Existing D10018runs remain unchanged; new campaign has only L168/L176/L184/L192,3repeats each,60sactive. No Edge connection, server or deployment.',
        'K8,30FPS/stream,240FPS physical decode AND resize;1575MHz,LocalC2,FP16/B1,D100. Same source mapping/hashes, zero phases and source due=t0+floor(frame_index*1e9/30). t0/warmup/queue initialization, preprocessing, TensorRT worker and telemetry are inherited unchanged. Local warmup30actual inferences/worker. No CUDA Graph/batching/controller/DVFS sweep.',
        'Extend only the canonical phase-accumulator admission grid: floor((f+1)*r/30)>floor(f*r/30),r=21/22/23/24. Every admitted frame goes Local. Excluded frames still decode+resize. Private function bindings extend the table without mutating any frozen module/source. Canonical160/200/240 masks remain identical.',
        'Exactly the same expired-work pruning: now>=source_due+100ms immediately before Local TRT start => EXPIRED_DROP. Already-started inference continues; remaining FIFO order preserved. No EDF/preemption/early producer drop. Same100ms inclusive timely-completion definition including active-admitted drain completions.',
        'Record aggregate/per-stream/worst-stream timelyFPS; source-normalized worstTIR (1800/stream;14400aggregate); admitted/executed/completed/late/expired counts; queue/service mean/p50/p95/p99; actual unfinished U; active VINJ/timelyframe;OC3/temperature/frequency. B=assigned-completed retains expired unserved work; U=B-expired. Expiry is not a completion or raw capacity proof. VIN scope excludes Edge/drain; missing/zero timely=>N/A.',
        'Final7-point Local grid160/168/176/184/192/200/240. Historical coarse cells are D100-map T160-A/T200-A/T240-A only. New12runs are independently raw-replayed. All individual repeats/streams plus mean/sampleSD. Primary rank=max configuration mean of3per-run worst-streamFPS (not min of mean streamFPS or mean of repeat maxima). Every exact primary tie remains selected. Diagnostic tie order: higher aggregate timelyFPS, then lowerVINJ/timelyframe; no energy-driven primary tie removal.',
        'Historical Best-Hybrid changes across repeats. Retain BOTH aggregate-selected fixed configuration repeat values and per-repeat Hybrid maximum envelope. Frozen comparison reference: '+plan['comparison_reference']+'. Observed-range non-overlap is a conservative descriptive rule, not a statistical test: Local minimum>Hybrid maximum => EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING; Hybrid minimum>Local maximum => EDGE_TIMELY_EXTENSION_CANDIDATE; range overlap/equality or missing/invalid => EDGE_ROLE_INCONCLUSIVE. All primary ties must support the same conclusion. No final claim now.',
        'Selection is within7sampled Local rates, not interpolation/exact optimum. Historical/new cohorts are not contemporaneous randomized pairs; time/thermal/protection confounding and selection on measured data remain. The Hybrid envelope can select different configurations per repeat and is explicitly an observed envelope, not one deployed policy. All comparisons and both reference definitions remain visible.',
        'Future authorized execution: same existing frequency helper idle1575pin/min-max readback/315–1575restore preflight once, then per-run pin/restore. Permission/pin/restore failure blocks campaign. OC3 is protection annotation, not automatic invalidity. No retry, source/package/system/network changes. Fixed order below; no outcome-dependent reorder.', '',
        '|Order|Run ID|Admission FPS/stream|Local FPS|','|---:|---|---:|---:|']
    for c in plan['order']:lines.append(f"|{c['order_index']}|{c['run_id']}|{c['local_r']}|{c['target_service_FPS']}|")
    with (OUT/'EXPERIMENT_PLAN.md').open('x') as f:f.write('\n\n'.join(lines[:13])+'\n'+'\n'.join(lines[13:])+'\n')
    print('Plan SHA256:',sha(PLAN))


if __name__=='__main__':
    if OUT.exists():raise SystemExit('Existing preparation; no overwrite')
    write_plan(build_plan())
