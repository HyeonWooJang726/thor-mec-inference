#!/usr/bin/env python3
"""Read-only run replay; write only K8 campaign-level analysis and preservation."""
import csv
import json
from pathlib import Path
import statistics
import subprocess

from run_k8_workload_gate import ROOT, OUT, PLAN, load_plan, sha, smoke_pass
from analyze_rate_dvfs_gate import read_csv, summarize


def mean_sd(values):
    if not values or any(v is None for v in values):
        return 'N/A'
    if len(values)<2:
        return f'{values[0]:.6f} (n=1; SD unavailable)'
    return f'{statistics.mean(values):.6f} ± {statistics.stdev(values):.6f}'


def main():
    plan = load_plan()
    inputs = json.loads((OUT/'input_manifest.json').read_text())
    before = inputs['existing_artifact_sha256_before']
    after = {p:sha(ROOT/p) if (ROOT/p).is_file() else None for p in before}
    changed = [p for p in before if after[p]!=before[p]]
    inputs['existing_artifact_sha256_after'] = after
    inputs['existing_artifact_preservation'] = {'status':'PASS' if not changed else 'FAIL',
                                               'file_count':len(before),'changed_paths':changed}
    (OUT/'input_manifest.json').write_text(json.dumps(inputs,indent=2)+'\n')
    summaries = []; mismatches = []
    for c in plan['smoke']+plan['order']:
        d = OUT/c['run_id']
        if not (d/'summary.json').exists():
            continue
        m = json.loads((d/'manifest.json').read_text())
        s = json.loads((d/'summary.json').read_text())
        # Invalid runs remain visible, without forcing missing measurements to zero.
        if s['integrity_status']=='VALID':
            raw = summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            for field,value in raw.items():
                if s.get(field)!=value:
                    mismatches.append({'run_id':c['run_id'],'field':field,'stored':s.get(field),'replay':value})
            expected = {'K':8,'C':2,'requested_freq_MHz':1575,'batch_size':1,
                        'admission_fps_per_stream':c['r'],'measurement_seconds':c['seconds'],
                        'plan_sha256':sha(PLAN),'child_returncode':0,'frequency_restore_ok':True,
                        'status_finalized':True,'inputs':plan['inputs']}
            for field,value in expected.items():
                if m.get(field)!=value:
                    mismatches.append({'run_id':c['run_id'],'field':'manifest.'+field,'stored':m.get(field),'expected':value})
        summaries.append(s)
    # A single canonical run table, including smoke explicitly tagged/excluded.
    records = []
    for s in summaries:
        record = dict(s,primary_included=s['kind']=='primary')
        for field,value in list(record.items()):
            if isinstance(value,(list,dict)):
                record[field] = json.dumps(value,separators=(',',':'))
        records.append(record)
    fields = list(dict.fromkeys(k for row in records for k in row)) or ['run_id','kind','integrity_status']
    with (OUT/'aggregate_summary.csv').open('w',newline='') as target:
        writer = csv.DictWriter(target,fieldnames=fields)
        writer.writeheader();writer.writerows(records)
    runs = [s for s in summaries if s['kind']=='primary']
    groups = {r:sorted([s for s in runs if s['admission_fps_per_stream']==r],key=lambda x:x['repeat']) for r in (21,27,30)}
    valid = [s for s in runs if s['integrity_status']=='VALID']
    smoke_ok,_ = smoke_pass(plan)
    verdict = 'INCONCLUSIVE'; explanation = 'Incomplete/inconsistent integrity or unresolved capacity/frontend evidence.'
    complete = len(runs)==9 and len(valid)==9 and smoke_ok and not mismatches and not changed
    if complete:
        repeated_front = any(sum(s['supply_status']=='FRONTEND_LIMITED' for s in g)>=2 for g in groups.values())
        all_normal = all(s['supply_status']=='NORMAL' for s in valid)
        consistent = all(len({s['queue_stable'] for s in g})==1 for g in groups.values())
        if repeated_front:
            verdict = 'K8_FRONTEND_CONTAMINATED'
            explanation = 'Repeated canonical FRONTEND_LIMITED annotation prevents a clean inference-capacity boundary interpretation. Do not freeze K8.'
        elif all_normal and consistent:
            if all(s['queue_stable'] for s in groups[30]):
                verdict = 'K8_UPPER_BOUND_NOT_FOUND'
                explanation = 'All r30 repeats are valid, NORMAL and stable. Only the lower-bound observation μ_L(1575 MHz) >= tested 240-FPS workload is supported; no exact/GPU-only capacity is estimated.'
            elif any(all(s['queue_stable'] for s in groups[r]) for r in (21,27)):
                verdict = 'K8_PRIMARY_ACCEPTABLE'
                stable_r = max(r for r in (21,27) if all(s['queue_stable'] for s in groups[r]))
                unstable_r = min(r for r in (21,27,30) if not any(s['queue_stable'] for s in groups[r]))
                explanation = f'A frontend-NORMAL stable-to-unstable transition is observed between tested {8*stable_r} and {8*unstable_r} FPS offered demands. This brackets an observed Local system transition, not exact or GPU-only capacity. K8 is acceptable as the subsequent workload.'
    lines = ['# K=8 Local Workload Feasibility Gate','',f'Final: **{verdict}**','',
             f'Smoke: {"PASS" if smoke_ok else "FAIL / not completed"}. Primary finalized {len(runs)}/9; integrity VALID {len(valid)}, INVALID {len(runs)-len(valid)}. No retries; smoke excluded from primary statistics.',
             '', 'K=8/C=2, RT-DETR Warehouse v1.0.2 deployable_rn50, canonical TensorRT FP16 B1. Eight distinct 1080p/30-FPS files; logical source aggregate 240 FPS. MAXN, requested GPC 1575 MHz. No historical pooling or C changes.',
             '', 'Canonical amended analyzer semantics are reused unchanged: B=logical admissions−completions; exact continuous-time g_B over active t=30..60 s; stable iff valid, g_B<=0.5 frames/s, no cap/drop. OC3 and source lag do not invalidate integrity. VDD_GPU power and energy use only active 60 s. J/frame only for stable runs. Latency quantiles cover the complete admitted active-source cohort including drain completions, as in the canonical analyzer. Concurrency denotes host service intervals, not measured kernel overlap.',
             '', 'Condition cells below are mean ± sample SD of valid repetitions. N/A means unavailable or J/frame undefined for an unstable repeat; no fabricated values. Repeat labels and all invalid records remain visible.',
             '', '| r | valid n | completed FPS | min stream FPS | FPS spread | g_B | GPU W | active J | J/frame | OC3 |',
             '|---:|---:|---|---|---|---|---|---|---|---|']
    metrics = ('aggregate_completed_fps','min_per_stream_completed_fps','per_stream_fps_spread','g_B','avg_power_W','active_energy_J','energy_per_frame_J','OC3_delta')
    for r,g in groups.items():
        good = [s for s in g if s['integrity_status']=='VALID']
        lines.append(f'| {r} | {len(good)} | '+' | '.join(mean_sd([s.get(f) for s in good]) for f in metrics)+' |')
    lines += ['', '| run | r | integrity | stability | frontend | hardware | OC3 | source/admitted/completed FPS | source/front slopes | ready deficit | concurrency peak/mean | actual MHz | restore / exit |',
              '|---|---:|---|---|---|---|---:|---|---|---|---|---|---|']
    for s in summaries:
        lines.append(f"| {s['run_id']} | {s['admission_fps_per_stream']} | {s['integrity_status']} | {s.get('queue_classification','N/A')} | {s.get('supply_status','N/A')} | {s.get('hardware_status','N/A')} | {s.get('OC3_delta','N/A')} | {s.get('source_fps','N/A')}/{s.get('aggregate_admitted_fps','N/A')}/{s.get('aggregate_completed_fps','N/A')} | {s.get('source_pending_slope','N/A')}/{s.get('frontend_pending_slope','N/A')} | {s.get('frontend_ready_deficit_fraction','N/A')} | {s.get('active_concurrency_peak','N/A')}/{s.get('active_concurrency_mean','N/A')} | {s.get('actual_freq_mean_MHz','N/A')} | {s.get('frequency_restore_ok','N/A')} / {s.get('child_returncode','N/A')} |")
    lines += ['', 'Per-stream service monitoring (R_k mean ± sample SD, stream ID order 0..7):']
    for r,g in groups.items():
        good = [s for s in g if s['integrity_status']=='VALID']
        lines.append(f'- r={r}: '+', '.join(mean_sd([s['per_stream'][i]['R_k'] for s in good]) for i in range(8)))
    lines += ['', explanation,
              '', 'r30 attribution: '+('frontend limitation observed; any accompanying inference saturation cannot be isolated from it.' if any(s.get('supply_status')=='FRONTEND_LIMITED' for s in groups[30]) else 'frontend NORMAL in all completed valid repetitions; growing B, if observed consistently, describes Local inference/system saturation, not an isolated GPU service law.' if len(groups[30])==3 and all(s['integrity_status']=='VALID' and s.get('supply_status')=='NORMAL' for s in groups[30]) else 'insufficient evidence to separate frontend and capacity.'),
              '', f'Raw replay mismatches: {json.dumps(mismatches)}.',
              f'Existing artifact preservation: {inputs["existing_artifact_preservation"]}.',
              '', 'Input SHA256 and before/after preservation inventories are in input_manifest.json. Source/plan hashes and lifecycle details are in every run manifest; all per-stream R/eta, backlog, source-to-decode/queue/service/E2E quantiles and telemetry are retained in summaries and aggregate_summary.csv.',
              '', 'Invalid records: '+json.dumps([{'run_id':s['run_id'],'errors':s.get('errors',[])} for s in summaries if s['integrity_status']!='VALID'])]
    (OUT/'gate_verdict.md').write_text('\n'.join(lines)+'\n')
    status = subprocess.check_output(['git','status','--short','--branch'],cwd=ROOT,text=True)
    (OUT/'final_git_status.txt').write_text(status)
    print(json.dumps({'verdict':verdict,'primary_finalized':len(runs),'valid':len(valid),'invalid':len(runs)-len(valid),
                      'smoke_pass':smoke_ok,'raw_replay_mismatches':mismatches,'preservation':inputs['existing_artifact_preservation']}))
    return 1 if mismatches or changed else 0


if __name__=='__main__':
    raise SystemExit(main())
