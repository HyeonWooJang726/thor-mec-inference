#!/usr/bin/env python3
"""Create exclusive new preparation artifacts only; never run a workload."""
from datetime import datetime, timezone
import json
from pathlib import Path
from pruning_common import ROOT,OUT,PLAN,sha,expected_order,canonical


def build_plan():
    old=json.loads((ROOT/'results/canonical_timely_service/plan.json').read_text())
    for name,digest in old['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Frozen dependency changed: '+name)
    sources=dict(old['source_sha256'])
    sources.update({str(p.relative_to(ROOT)):sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
    baseline={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'results/canonical_timely_service/analysis01').glob('*')) if p.is_file()}
    baseline['results/canonical_timely_service/plan.json']=sha(ROOT/'results/canonical_timely_service/plan.json')
    evidence=dict(old['authoritative_evidence_sha256']);evidence.update(baseline)
    deps={n:sha(ROOT/'scripts/edge_raw_capacity_gate'/n) for n in ('formal_server.py','formal_protocol.py','profile_edge_concurrency.py')}
    deps['edge_server.py']=sha(Path(__file__).with_name('edge_server.py'))
    return dict(campaign='EXPIRED_WORK_PRUNING',attempt='P01',freeze_status='FROZEN_EXPIRED_WORK_PRUNING_V1',
        frozen_utc=datetime.now(timezone.utc).isoformat(),smoke=[],order=expected_order(),source_phase_ns=[0]*8,
        placement=canonical.placement_manifest(),inputs=old['inputs'],engine_provenance=old['engine_provenance'],
        cache=old['cache'],edge_host=old['edge_host'],runtime=old['runtime'],deadlines_ms=[100,150],
        source_sha256=sources,authoritative_evidence_sha256=evidence,baseline_sha256=baseline,
        edge_dependency_sha256=deps,energy=old['energy'],
        rule='Immediately before Local inference start or Edge socket submission: monotonic_ns >= logical_arrival_ns + D => EXPIRED_DROP. No post-start cancellation. Surviving FIFO unchanged.',
        baseline='Existing canonical T200-B/T240-B analysis01 only; historical repeat-index comparisons, not contemporaneous paired or significance tests. Baseline never rerun.',
        cohort='Active-admitted frames; retain drain completions and explicit expiry terminals. No expiry for warmup.',
        accounting=dict(source_target_per_run=14400,source_target_per_stream=1800,
            TIR_source='timely/physical-source-target (14400 aggregate;1800 per stream)',
            TIR_admission='timely/admitted diagnostic; expired remains denominator failure',
            B='assigned-completed; expired remains unserved, never counted as completion',
            U='assigned-completed-expired_terminal; actual unfinished work',
            regression='Continuous-time final30s OLS separately for B_H/B_L/B_E and U_H/U_L/U_E',
            no_fake_stability='No raw sustainable-capacity claim from pruning-induced U decrease',
            on_time='completion-logical_arrival <= D inclusive, including drain',
            latency='Executed/completed cohort; also report wait-until-expiry and all Local wait-until-disposition to expose selection effects'),
        verdict=dict(PRUNING_SUPPORTED='3/3 VALID; each repeat timelyFPS exceeds corresponding historical FIFO repeat; worst-stream and each same-ID stream timelyFPS do not decrease',
            FAIRNESS_REGRESSION='3/3 aggregate timely gains but at least one same-ID stream timelyFPS decreases; conservatively descriptive, no significance claim',
            NO_TIMELY_GAIN='3/3 no timely gain, expiry present, late-completedFPS does not increase',
            INCONCLUSIVE='Mixed direction, insufficient/integrity-invalid repeats, or otherwise not resolved'),
        execution_policy='Preparation only. Future explicit campaign: one existing-helper pin/restore preflight, then12 runs, no additional smoke/retry. Failures preserved. All expired IDs explicitly partition assigned IDs with submitted IDs at Edge END. No Edge inference cancellation.')


def write_plan(p):
    OUT.mkdir(parents=True,exist_ok=False)
    with PLAN.open('x') as f:json.dump(p,f,indent=2);f.write('\n')
    lines=['# Expired-Work Pruning Pilot', '', '**WAITING_FOR_EXPIRED_WORK_PRUNING_DEPLOYMENT**', '',
        'Preparation only: no GPU/network/frequency operation. Existing canonical18-run FIFO data remains authoritative and unchanged.',
        'K8,30FPS/stream,240FPS decode+resize,1575MHz,LocalC2/EdgeC1,B1/FP16,RAW640. Zero-phase logical capture/due times and exact canonical admission/placement IDs are unchanged. P200=184Local+16Edge; P240=200Local+40Edge. D100/D150,60s,3repeats. Local warmup30actual inferences/worker and Edge50/session remain unchanged.',
        'Only waiting work is pruned: now >= source_due+D immediately before Local inference or Edge socket submission. Execution already started/submitted is never cancelled even if completion is late. Survivors retain original FIFO order; no EDF or deadline-aware admission. No producer-side pruning: every physical frame still decodes/resizes.',
        'Source-normalized TIR uses14400physical source targets (1800/stream); admitted-normalized TIR is diagnostic. Expired drops remain timely failures. on_time uses <= D and includes active-admitted work completed in drain. Deadline equality is pruned if still waiting; a previously started frame completing exactly at D is timely.',
        'Preserve completion-only B=assigned-completed plus actual unfinished U=B-expired. Report final30s continuous-time OLS for both; expiry is an explicit terminal event, never a fabricated completion. Drain requires U=0; B can end at number expired. Do not infer raw capacity stability from U flattening.',
        'Edge server inference/backend/framing is reused unchanged. Only END accounting accepts a sorted explicit never-submitted expiry-ID ledger. Seen+expired must partition all assigned IDs; received requests still execute and drain. No intentional server drop; no retry/cancellation.',
        'Report all individual/repeat mean+sampleSD metrics: source/admitted/expired/executed/completed/timely/late,source and admission TIR,per-stream timely/worst/SD,latency/queues, B/U, VIN J/timelyframe. Queue/service latency is executed cohort; expired waiting and all-frame wait-until-disposition reported separately. Preserve every invalid/missing run.',
        'VIN scope inherits existing audit: active Thor module+carrier input only; no Edge/drain energy or rail summation. ActiveVINjoules/timelycohort is an accounting ratio. Zero timely or missingVIN => N/A.',
        'Baseline analysis01 T200-B/T240-B at D100/150 is reused with explicit source-denominator renormalization. Repeat-index comparisons are descriptive historical comparisons, not randomized contemporaneous pairs; thermal/time-order confounding remains. No significance claim. PRUNING_SUPPORTED requires all3 aggregate gains without worst-stream or any same-ID stream regression; mixed/invalid evidence is INCONCLUSIVE. FAIRNESS_REGRESSION flags any same-ID decrease when all3 aggregate gains exist.',
        'Frozen order below rotates/reverses cells. No order/repeat change after outcomes. Future execution requires manual Edge deployment and explicit user authorization; preparation does not run frequency preflight.', '',
        '|Order|Run ID|Local/Edge FPS|D ms|','|---:|---|---:|---:|']
    for c in p['order']:lines.append(f"|{c['order_index']}|{c['run_id']}|{8*c['local_r']}/{8*c['edge_r']}|{c['deadline_ms']}|")
    with (OUT/'EXPERIMENT_PLAN.md').open('x') as f:f.write('\n\n'.join(lines[:14])+'\n'+'\n'.join(lines[14:])+'\n')
    bundle=OUT/'edge_bundle_v1';bundle.mkdir()
    for name in p['edge_dependency_sha256']:
        src=Path(__file__).with_name(name) if name=='edge_server.py' else ROOT/'scripts/edge_raw_capacity_gate'/name
        with (bundle/name).open('xb') as f:f.write(src.read_bytes())
    with (bundle/'plan.json').open('xb') as f:f.write(PLAN.read_bytes())
    with (bundle/'SHA256SUMS').open('x') as f:
        for path in sorted(bundle.iterdir()):
            if path.name!='SHA256SUMS':f.write(f'{sha(path)}  {path.name}\n')
    print('Plan SHA256:',sha(PLAN))


if __name__=='__main__':
    if OUT.exists():raise SystemExit('Existing preparation; no overwrite')
    write_plan(build_plan())
