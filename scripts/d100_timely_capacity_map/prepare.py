#!/usr/bin/env python3
"""Freeze fresh plan and portable Edge bundle; no experiment execution."""
from datetime import datetime,timezone
import json
from pathlib import Path
from map_common import ROOT,OUT,PLAN,sha,expected_order,canonical


def build_plan():
    old=json.loads((ROOT/'results/expired_work_pruning/plan.json').read_text())
    for name,digest in old['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Frozen source changed: '+name)
    sources=dict(old['source_sha256'])
    sources.update({str(p.relative_to(ROOT)):sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
    deps={n:sha(ROOT/'scripts/edge_raw_capacity_gate'/n) for n in ('formal_server.py','formal_protocol.py','profile_edge_concurrency.py')}
    deps['pruning_edge_server.py']=sha(ROOT/'scripts/expired_work_pruning/edge_server.py')
    deps['edge_server.py']=sha(Path(__file__).with_name('edge_server.py'))
    evidence=dict(old['authoritative_evidence_sha256'])
    for n in ('results/expired_work_pruning/plan.json','results/expired_work_pruning/analysis01/pruning_verdict.md','results/expired_work_pruning/analysis01/verification.json'):
        evidence[n]=sha(ROOT/n)
    return dict(campaign='D100_TIMELY_CAPACITY_SOURCE_MAP',attempt='P01',freeze_status='FROZEN_D100_TIMELY_CAPACITY_MAP_V1',
        frozen_utc=datetime.now(timezone.utc).isoformat(),smoke=[],order=expected_order(),deadlines_ms=[100],
        source_phase_ns=[0]*8,placement=canonical.placement_manifest(),runtime=old['runtime'],
        inputs=old['inputs'],engine_provenance=old['engine_provenance'],cache=old['cache'],edge_host=old['edge_host'],
        source_sha256=sources,authoritative_evidence_sha256=evidence,edge_dependency_sha256=deps,
        accounting=old['accounting'],energy=old['energy'],rule=old['rule'],cohort=old['cohort'],
        primary=['per-stream timelyFPS','worst-stream timelyFPS','source-normalized worst-stream TIR'],
        secondary=['aggregate timelyFPS/source TIR','expired/lateFPS','Local/Edge activecompletedFPS','Localqueue p50/p95/p99',
                   'EdgeE2E','actual unfinished U','active Thor VINJ/timelyframe'],
        comparisons='Within each target and repeat, B minus A. Verify identical source-due/admitted identities. All paths prune at D100, no historical pooling. Three repeats, mean/sampleSD and all per-stream differences.',
        verdict=dict(HYBRID_TIMELY_CAPACITY_GAIN='3 valid pairs; aggregate timelyFPS and worst-stream timelyFPS both strictly increase in every pair',
            LOCAL_BETTER='3 valid pairs; aggregate timelyFPS and worst-stream timelyFPS both strictly decrease in every pair',
            NO_EDGE_TIMELY_GAIN='3 valid pairs; both metrics nonpositive in every pair, with at least one tie; strict Local superiority has priority',
            INCONCLUSIVE='Any invalid/missing pair, changed admitted IDs, mixed repeat direction or aggregate/worst-stream trade-off'),
        sufficiency='S160 timely shortfall and per-stream fulfillment are numeric only; no invented sufficient/timely-good threshold.',
        policy='Preparation only. Future explicit execution:18runs, no new smoke/retry; existing-helper preflight and per-run1575pin/readback/315-1575restore. A has no network connection; B9sessions use existing pruning END ledger. Preserve invalids. No graphs/batching/EDF/controller or admission/frequency/placement changes.')


def write_plan(plan):
    OUT.mkdir(parents=True,exist_ok=False)
    with PLAN.open('x') as f:json.dump(plan,f,indent=2);f.write('\n')
    lines=['# Formal D100 Timely Capacity-Source Map', '', '**WAITING_FOR_D100_TIMELY_MAP_DEPLOYMENT**', '',
        'Preparation only: no GPU/network/frequency preflight executed. Same canonical zero-phase live-video harness and validated expiry implementation. Source due=t0+floor(frame_index*1e9/30), all8stream phases zero. Deadline starts at source due, not decode/ready. Every condition decodes/resizes240FPS; admitted IDs identical within each A/B target pair.',
        'K8,30FPS/stream,1575MHz,LocalC2/EdgeC1,B1,FP16,RAW640; no graphs/batching. Localwarmup30actual inferences/worker and Edgewarmup50/session unchanged. D100,60sactive,3repeats;18runs and no additional smoke. A never opens an Edge connection. All surviving frames remain FIFO.',
        'T160-A=160/0;T160-B=144/16;T200-A=200/0;T200-B=184/16;T240-A=240/0;T240-B=200/40(Local/EdgeFPS). Admission is20/25/30FPS per stream, canonical phase accumulator and deterministic Edge eligibility unchanged.',
        'Prune only if now >= source_due+100ms immediately before Local inference or Edge socket submission. Already running/submitted requests finish naturally. No cancellation, EDF, arrival delay, early producer drop or adaptive placement. All source frames still decode/resize; original admission exclusions remain explicit.',
        'Primary: each stream timelyFPS; minimum stream timelyFPS; source-normalized worst-streamTIR. Source denominator14400/run or1800/stream, not admitted count. TIR_admission is separate diagnostic. Timely completion is latency<=100ms inclusive for active-admitted cohort including drain. Every expired drop stays a timely failure.',
        'Report admitted/expired/executed/completed/timely/late, Local/Edge active completion, all stream values/SD/worst, queue/service/pathE2E, B and U. B=assigned-completed retains expired unserved work; U=B-expired is actual unfinished work. Expiry never fabricates completion. Final30s continuous-timeOLS for B/U; no raw stability claim from pruning-induced U reduction.',
        'Executed-frame queue/latency quantiles and expired waiting times are distinct; report all Local wait-until-disposition as well. Active VIN energy scope is existing audited Thor module+carrier input, excludes Edge/drain; no rail summation. VIN J/timelyframe N/A when unavailable/zero timely.',
        'A/B are adjacent within each repeat. R2 reverses R1; R3 rotates targets and alternates pair orientation. Three repeats cannot perfectly balance order. Pair by target+repeat, retain every run. Mean and sampleSD, no statistical significance claim. All source-due/admitted identities independently checked from raw before a pair is eligible.',
        'HYBRID_TIMELY_CAPACITY_GAIN:3validpairs, B>A for both aggregate and worst-stream timelyFPS every repeat. LOCAL_BETTER: both B<A every repeat. NO_EDGE_TIMELY_GAIN: both B<=A every repeat with ties preventing strict Local superiority. Mixed signs, aggregate/worst-stream trade-off, missing/invalid or ID mismatch => INCONCLUSIVE. Every same-ID stream difference is additionally reported; no claim that worst-stream improvement guarantees all streams improve.',
        'S160 Local sufficiency is shown as timely shortfall/per-stream fulfillment without arbitrary PASS threshold. S200/S240 quantify paired timely capacity gain and queue differences; do not infer causal CPU/GPU/network mechanism. Prior FIFO/pruning campaigns remain historical context only, not pooled primary evidence.',
        'Future authorized campaign uses existing frequency helper only: idle pin/readback/restore preflight once, then pin1575 and restore315–1575 per run. OC3 is PROTECTION_LIMITED diagnostic, not automatic invalidity. No system/package/network changes. No retries; failures preserved.', '',
        '|Order|Run ID|Cell|Local/Edge FPS|','|---:|---|---|---:|']
    for c in plan['order']:lines.append(f"|{c['order_index']}|{c['run_id']}|{c['cell']}|{8*c['local_r']}/{8*c['edge_r']}|")
    with (OUT/'EXPERIMENT_PLAN.md').open('x') as f:f.write('\n\n'.join(lines[:16])+'\n'+'\n'.join(lines[16:])+'\n')
    bundle=OUT/'edge_bundle_v1';bundle.mkdir()
    for name in plan['edge_dependency_sha256']:
        src=(Path(__file__).with_name(name) if name=='edge_server.py' else
             ROOT/'scripts/expired_work_pruning/edge_server.py' if name=='pruning_edge_server.py' else ROOT/'scripts/edge_raw_capacity_gate'/name)
        with (bundle/name).open('xb') as f:f.write(src.read_bytes())
    with (bundle/'plan.json').open('xb') as f:f.write(PLAN.read_bytes())
    with (bundle/'SHA256SUMS').open('x') as f:
        for p in sorted(bundle.iterdir()):
            if p.name!='SHA256SUMS':f.write(f'{sha(p)}  {p.name}\n')
    print('Plan SHA256:',sha(PLAN))


if __name__=='__main__':
    if OUT.exists():raise SystemExit('Existing preparation; no overwrite')
    write_plan(build_plan())
