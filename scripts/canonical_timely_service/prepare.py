#!/usr/bin/env python3
"""Freeze a NEW plan/bundle only. Does not execute clocks, inference or networking."""
from datetime import datetime, timezone
import json
from pathlib import Path
from timely_common import ROOT, OUT, PLAN, DEADLINES, expected_order, placement_manifest, sha


def build_plan():
    previous=json.loads((ROOT/'results/equal_service_map/plan.json').read_text())
    for rel,digest in previous['source_sha256'].items():
        if sha(ROOT/rel)!=digest:raise RuntimeError('Frozen source changed: '+rel)
    sources=dict(previous['source_sha256'])
    sources.update({str(p.relative_to(ROOT)):sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
    deps={name:sha(ROOT/'scripts/edge_raw_capacity_gate'/name) for name in
          ('formal_server.py','formal_protocol.py','profile_edge_concurrency.py')}
    deps['edge_server.py']=sha(Path(__file__).with_name('edge_server.py'))
    evidence=dict(previous['authoritative_evidence_sha256'])
    for rel in ('results/equal_service_map/plan.json','results/equal_service_map/POWER_SCOPE_AUDIT.md',
                'results/timely_service_audit/analysis01/verification.json'):
        evidence[rel]=sha(ROOT/rel)
    return dict(campaign='CANONICAL_TIMELY_SERVICE_MAP',attempt='P01',
        freeze_status='FROZEN_CANONICAL_TIMELY_SERVICE_V1',frozen_utc=datetime.now(timezone.utc).isoformat(),
        smoke=[],order=expected_order(),placement=placement_manifest(),deadlines_ms=list(DEADLINES),
        inputs=previous['inputs'],engine_provenance=previous['engine_provenance'],cache=previous['cache'],
        edge_host=previous['edge_host'],source_sha256=sources,authoritative_evidence_sha256=evidence,
        edge_dependency_sha256=deps,stability=previous['stability'],
        runtime=dict(K=8,C_L=2,C_E=1,B=1,precision='FP16',model='RT-DETR Warehouse v1.0.2 deployable_rn50',
            power_mode='MAXN',CUDA_Graph=False,dynamic_batching=False,source_FPS_per_stream=30,
            physical_decode_resize_FPS=240,edge_port=5000,frequency_MHz=1575,restore_range_MHz=[315,1575],
            active_seconds=60,repeats=3,local_warmup_inferences_per_worker=30,Edge_warmup_inferences=50),
        timely=dict(cohort='active-admitted source-due frames including completion in drain',
            latency='Thor completion_timestamp_ns - logical_arrival_ns; Edge response equality checked',
            on_time='latency_ns <= D_ms * 1000000 (inclusive integer comparison)',
            raw_completed_FPS='completion inside [active_start, active_end) /60',
            timely_FPS='on_time cohort /60',late_FPS='completed late cohort /60; missing separate',
            TIR='on_time /admitted',worst_stream_TIR='minimum of8streamTIR per run',
            summary='equal repeat means and sampleSD; invalid/missing retained; no historical pooling',
            timely_good_threshold=None),
        energy=dict(scope='Thor VIN module+carrier input, excludes Edge and wall conversion loss',
            audit_path='results/equal_service_map/POWER_SCOPE_AUDIT.md',
            integration='reuse canonical active-window timestamped rail integration; do not sum rails',
            VIN_J_per_timely_frame='active VIN joules /on-time active-admitted frames; drain energy excluded',
            zero_timely_frames='N/A; no infinity, zero energy or invented replacement',
            missing_VIN='ENERGY_SCOPE_UNRESOLVED /N/A; performance evidence retained'),
        interpretation='Raw STABLE does not imply timely-good. No deadline dropping/controller. A/B identical source/admitted IDs, one preprocessing implementation. Between-rate B comparisons also change allocation; not causal admission-only effects.',
        run_policy='No automatic retry/resume; exclusive new run dirs; failed evidence retained. Stop on frequency/restore/session alignment failure; unstable raw workload is not abort reason. Execution requires subsequent user authorization and Edge deployment.')


def write_plan(p):
    OUT.mkdir(parents=True,exist_ok=False)
    with PLAN.open('x') as f:json.dump(p,f,indent=2);f.write('\n')
    lines=['# Canonical Timely-Service Map — formal preparation', '',
        '**WAITING_FOR_CANONICAL_TIMELY_SERVICE_DEPLOYMENT. No GPU/network campaign executed.**', '',
        'K8, physical30FPS/stream,240FPS decode AND resize in every condition;1575MHz;LocalC2/EdgeC1;B1/FP16;RAW640. Same frozen video hashes, preprocessing and runtime. No graphs/batching/controller/deadline dropping.',
        'Source logical due=t0+stream_phase+floor(frame_index*1e9/30); all8phases=0. Same30FPS timeline and phase-accumulator admission in all cells. Same admitted IDs within each A/B pair. A never connects to Edge. Excluded frames still decode+resize; B places a subset with uniform Edge eligibility without changing due time.',
        '18runs,60s active,3repeats, natural drain. No additional smoke. Fixed balanced/reversed ordering below; odd repeat count cannot perfectly balance A/B order. Local warmup30actual inferences/worker, Edge50beforeREADY only in B, unchanged premeasurement empty queue. Existing live Equal-Service harness reused, not historical-capacity harness.',
        'Future campaign performs existing-helper idle1575pin/min-max readback/default315–1575restore preflight once, then existing per-run pin/restore/lifecycle. Preparation does NOT execute this preflight. OC3 annotates PROTECTION_LIMITED; not an invalidity/abort trigger. No setting/package changes.',
        'Raw stability remains VALID + continuous-time final30s g_B,H<=0.5 + no drops/cap saturation + complete drain. B_H/B_L/B_E retained. No additional timely-good threshold. Intentionally unstable Local240 must complete active interval and drain; no outcome-based retries.',
        'Deadlines40/60/80/100/150/200ms are offline metrics only, not execution actions. Active-admitted cohort includes drain completion. Thor source due to Thor completion/returned result; no cross-host subtraction. 33.3ms frame interval is not a deadline.',
        'Report admitted/raw active completion/timely/lateFPS,counts,TIR,stream timelyFPS/TIR,worststream and path metrics. Existing global/local/edgebacklog, stage latency,frontend,frequency,temp,OC3before/after/delta and rail telemetry retained. Condition mean/sampleSD; all repeats and invalids visible. No historical pooling, no statistical significance claim.',
        'VIN scope reuses results/equal_service_map/POWER_SCOPE_AUDIT.md: Thor module+carrier input only. Integrate only active timestamps. VIN J/timely frame=activeVINenergy/on-timecohort; does not include drain or Edge energy. Zero on-time=>N/A. MissingVIN=>N/A, never fabricate or sum rails. This is a measured accounting ratio, not whole-system energy efficiency.',
        'Questions: deadline-conditioned160/200/240service; whether reducing admission increases timelyFPS/worststreamTIR; A/B placement differences; Local240vsHybrid240 useful gain. Paired numeric differences, no predetermined winner. Between-rate B changes both admission and allocation (Edge16/16/40); do not call it isolated admission causality.', '',
        '|Order|Run|Condition|Local FPS|Edge FPS|', '|---:|---|---|---:|---:|']
    for c in p['order']:lines.append(f"|{c['order_index']}|{c['run_id']}|{c['cell']}|{8*c['local_r']}|{8*c['edge_r']}|")
    (OUT/'EXPERIMENT_PLAN.md').write_text('\n\n'.join(lines[:11])+'\n\n'+'\n'.join(lines[11:])+'\n')
    # Everything is a new directory; byte-copy runtime dependencies only, no assets.
    bundle=OUT/'edge_bundle_v1';bundle.mkdir()
    for name in p['edge_dependency_sha256']:
        source=Path(__file__).with_name(name) if name=='edge_server.py' else ROOT/'scripts/edge_raw_capacity_gate'/name
        with (bundle/name).open('xb') as f:f.write(source.read_bytes())
    with (bundle/'plan.json').open('xb') as f:f.write(PLAN.read_bytes())
    files=sorted(bundle.iterdir())
    sums=''.join(f'{sha(path)}  {path.name}\n' for path in files)
    with (bundle/'SHA256SUMS').open('x') as f:f.write(sums)
    print('Plan SHA256:',sha(PLAN));print(sums)


if __name__=='__main__':
    if OUT.exists():raise SystemExit('Existing preparation directory; no overwrite')
    write_plan(build_plan())
