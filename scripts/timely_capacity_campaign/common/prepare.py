"""Freeze plans, masks, predictions and portable Edge launcher; no workload/control calls."""
from collections import Counter
from datetime import datetime,timezone
import csv
import gzip
import json
from pathlib import Path
import campaign_config as cfg

HERE=Path(__file__).resolve().parent


def write_json(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (gzip.open(path,'xt',newline='') if path.suffix=='.gz' else path.open('x',newline='')) as f:
        w=csv.DictWriter(f,fields);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v) if isinstance(v,(list,dict,tuple)) else v for k,v in r.items()})


def patterns(block):
    records=[];counts=[];skip=[]
    for cell,c in {c['cell']:c for c in cfg.expected_order(block)}.items():
        ms,slots=cfg.schedule(c['target_service_FPS'],8*c['edge_r'],c['admission_pattern'])
        for sid in range(8):
            admitted=[i for i in range(1800) if i%30 in ms[sid]];skipped=[i for i in range(1800) if i%30 not in ms[sid]]
            circular=[i for i in range(30) if i not in ms[sid]]
            skip.append(dict(cell=cell,stream_id=sid,phase_shift_frames=cfg.shifts(c['target_service_FPS']//8,c['admission_pattern'])[sid],
                cyclic_skip_gap_histogram=dict(Counter((circular[(i+1)%len(circular)]-f)%30 for i,f in enumerate(circular))) if circular else {},
                finite_60s_skip_gap_histogram=dict(Counter(b-a for a,b in zip(skipped,skipped[1:]))),
                admitted_frame_indices=admitted,skipped_frame_indices=skipped))
            for f in range(1800):
                row=cfg.decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=f*10**9//30),0,c)
                records.append(dict(cell=cell,**row))
        totals={k:[] for k in ('admitted','local','edge')}
        for f in range(30):
            n=sum(f in m for m in ms);e=sum(key[1]==f for key in slots)
            totals['admitted'].append(n);totals['edge'].append(e);totals['local'].append(n-e)
        for kind,values in totals.items():counts.append(dict(cell=cell,kind=kind,min=min(values),max=max(values),mean=sum(values)/30,histogram_slots_per_second=dict(Counter(values))))
    write_csv(cfg.out(block)/'planned_frame_ids.csv.gz',records)
    write_csv(cfg.out(block)/'skip_patterns.csv.gz',skip)
    write_csv(cfg.out(block)/'slot_distributions.csv',counts)


def edge_files():
    return {'edge_server.py':HERE.parent/'block_b_split/edge_server.py',
        'campaign_config.py':HERE/'campaign_config.py',
        'pruning_edge_server.py':cfg.ROOT/'scripts/expired_work_pruning/edge_server.py',
        **{n:cfg.ROOT/'scripts/edge_raw_capacity_gate'/n for n in ('formal_server.py','formal_protocol.py','profile_edge_concurrency.py')}}


def prepare(block):
    root=cfg.out(block)
    if (root/'plan.json').exists():raise RuntimeError('No plan overwrite')
    old=json.loads((cfg.ROOT/'results/d100_timely_capacity_map/plan.json').read_text())
    for rel,digest in old['source_sha256'].items():
        if cfg.sha(cfg.ROOT/rel)!=digest:raise RuntimeError('Frozen dependency changed: '+rel)
    sources=dict(old['source_sha256'])
    for folder in (HERE,HERE.parent/cfg.BLOCKS[block]):
        sources.update({str(p.relative_to(cfg.ROOT)):cfg.sha(p) for p in folder.glob('*.py')})
    prediction=HERE/'PREDICTION.md';sources[str(prediction.relative_to(cfg.ROOT))]=cfg.sha(prediction)
    deps={name:cfg.sha(path) for name,path in edge_files().items()} if block=='B' else {}
    frozen=dict(campaign='D100_LOCAL_TIMELY_CAPACITY_CAMPAIGN',block=block,attempt='P01',
        freeze_status='FROZEN_TCC_V1',frozen_utc=datetime.now(timezone.utc).isoformat(),
        order=cfg.expected_order(block),smoke=[],deadlines_ms=[100],source_phase_ns=[0]*8,
        placement=cfg.placement_manifest(block),inputs=old['inputs'],engine_provenance=old['engine_provenance'],
        cache=old['cache'],edge_host=old['edge_host'],runtime=dict(old['runtime'],network_connection=block=='B'),
        energy=old['energy'],accounting=old['accounting'],rule=old['rule'],idle_seconds=cfg.IDLE_SECONDS,
        idle_definition='10 seconds after previous child finalization/cleanup, before next run seed; no temperature-adaptive waits',
        prediction_path=str(prediction.relative_to(cfg.ROOT)),prediction_sha256=cfg.sha(prediction),
        source_sha256=sources,authoritative_evidence_sha256=dict(old['authoritative_evidence_sha256']),
        edge_dependency_sha256=deps,edge_preflight_order=cfg.preflight_order() if block=='B' else [],
        network_interface='wlP1p1s0' if block=='B' else None,
        approval='Independent explicit approval per block; CLI requires the exact plan SHA; no implicit A approval of B',
        stopping='No retry/overwrite/automatic resume; stop own block on invalid/frequency/lifecycle failure. Preserve all artifacts. Other block remains independently runnable.',
        NO_EFFECT_operational_rule='After strict directional A verdicts: every paired absolute timelyFPS difference <= BOTH within-pattern observed ranges, and every paired absolute queue p95 difference <= BOTH queue ranges. Otherwise INCONCLUSIVE. Descriptive, not statistical equivalence.',
        B_gate='Use R1-R3 paired with reference. Integrity first; any max-Edge-split R1-R3 Edge timely ratio<0.90 => EDGE_PATH_LIMITED; then supported/reference-best rules. R4-R5 reported separately and in 5-repeat stats.',
        B_preflight='Only after B approval: cached real RAW64030 with the same expired-only sender; E56,E72,E80 x30s once; no Local inference/decode/frequency control. E80 ratio<0.90 or invalid stops B; no automatic overrides.',
        skip_distribution='Compare cyclic 30-slot skip gaps. Fixed60s truncation omits the wraparound gap and may change a finite gap-bin count by one; both exact histograms saved. Source phases/timestamps unchanged.',
        metrics=['path timely/late/expired FPS and assigned-normalized ratios','per-stream/worst source-normalized TIR','Local queue/service/E2E',
            'source slot histograms; actual enqueue rank outcomes','frame-based latency decomposition and remaining budget negative fraction',
            'completion-only B and terminal U','VIN active J/timely cohort; no Edge energy','interface TX counter and payload-only TX','OC3/temperature/frequency/lifecycle'],
        CPU_validation_sha256={p.name:cfg.sha(p) for p in root.glob('*cpu_validation*.json')})
    if block=='B':
        audit=root/'read_only_audit.json';frozen['read_only_audit_sha256']=cfg.sha(audit)
        for rel in ('results/edge_raw_capacity_gate/edge_concurrency_run02/edge_concurrency_summary.csv',
                    'results/edge_raw_capacity_gate/tcp_sender.csv',
                    'results/edge_raw_capacity_gate/formal_analysis_primary04/edge_rate_summary.csv'):
            frozen['authoritative_evidence_sha256'][rel]=cfg.sha(cfg.ROOT/rel)
    patterns(block)
    write_json(root/'plan.json',frozen)
    digest=cfg.sha(root/'plan.json')
    (root/'plan.sha256').open('x').write(digest+'  plan.json\n')
    write_csv(root/'run_order.csv',frozen['order'])
    (root/'prediction.sha256').open('x').write(cfg.sha(prediction)+'  '+str(prediction.relative_to(cfg.ROOT))+'\n')
    lines=['# D100 Local Timely Capacity Campaign — Block '+block,'','**WAITING_FOR_CAMPAIGN_APPROVAL**','',
        'Preparation only: no GPU/network workload and no frequency control. Independent block plan, run IDs, output, hash and approval. No past baseline reruns.',
        'K8 source30FPS/stream, physical decode AND resize240FPS; source due=t0+floor(frame_index*1e9/30), all phases0. Active60s,Local1575MHz/C2/B1/FP16,EdgeC1/RAW640 when assigned. Original warmup30inferences/Localworker and50/session Edge unchanged. No graphs/batching/EDF/latest-start pruning.',
        'Expired-only rule is the original PruningAccounting/EdgeLink implementation: now>=due+100ms immediately before Local start/Edge submission; no cancellation after start/submission; FIFO survivors. Drop remains a timely failure. B=assigned-completed; actual unfinished U=B-expired. Drain requires U=0.',
        'Fixed10s idle after each child finalization before next seed. Record startGPUthermal readings, OC3before/after/delta and ongoing original telemetry. Missing thermal fields are explicitly unavailable. No adaptive cooling/clock/system settings.',
        'Future primary execution alone performs historical frequency-helper permission/start-range/1575pin/readback/315–1575restore preflight; each run pins/restores. None of this executes during preparation.',
        'Source/admission/split IDs saved in planned_frame_ids.csv.gz. STAGGERED rotates the existing periodic mask; it does not change source phases, due timestamps or total physical frontend work. Cyclic skip-gap histogram is identical perstream. Finite window endpoints censor one gap; skip_patterns.csv.gz preserves finite and cyclic histograms.',
        'A: three adjacent same-load pairs per repeat, pair order alternates; load order rotates/reverses. B:35runs, extra R4/R5 only four Local176/184 cells; primary comparisons useR1–R3 only, all5 separately retained. E16/E40 reference masks and placements are byte-for-byte value-identical to canonical rules.',
        'NO_EFFECT operationalization: '+frozen['NO_EFFECT_operational_rule'],
        'Block B precedence: '+frozen['B_gate'],
        'VIN scope inherited from frozen audit: active Thor module+carrier input, not Edge or total distributed energy. No rail sum. ActiveVINjoules/timely active-admitted frame includes drain completions in denominator; no drain energy. Missing VIN or zero timely=>N/A.',
        'Interface TX counter rate includes unrelated traffic/overhead, distinct from completed-send RAW640 image bytes/s. No attribution of application-only traffic from interface counters. Wireless PHY bitrate is not sustained TCP capacity.',
        'All metrics retained perrepeat plus mean, sampleSD,min,max. Source-normalized TIR denominator14400/1800. Local/Edge ratio denominator assigned, including expired. Latency uses same-host differences; no cross-host subtraction. Remaining budget uses exact Local start-source due, not sums of marginal percentiles.',
        'Slot-entry rank: all admitted entry timestamps and Local-only entry order kept separately; ties are N/A. Slot counts use exact30Hz source indices, not rounded33ms bins.',
        'Predictions are stored once in '+frozen['prediction_path']+' and are not verdict rules. Descriptive cross-block table compares A ALIGNED176/184 vs B176/184 without causal claims.', '',
        'Plan SHA256: `'+digest+'`','Prediction SHA256: `'+cfg.sha(prediction)+'`','',
        '|Order|Run ID|Source/admitted FPS|Local/Edge FPS|Pattern|','|---:|---|---:|---:|---|']
    for c in frozen['order']:lines.append(f"|{c['order_index']}|{c['run_id']}|240/{c['target_service_FPS']}|{8*c['local_r']}/{8*c['edge_r']}|{c['admission_pattern']}|")
    (root/'EXPERIMENT_PLAN.md').open('x').write('\n\n'.join(lines[:22])+'\n'+'\n'.join(lines[22:])+'\n')
    if block=='B':
        bundle=root/'edge_bundle_v1';bundle.mkdir()
        for name,path in edge_files().items():
            with (bundle/name).open('xb') as f:f.write(path.read_bytes())
        with (bundle/'plan.json').open('xb') as f:f.write((root/'plan.json').read_bytes())
        checksum_text=''.join(f'{cfg.sha(p)}  {p.name}\n' for p in sorted(bundle.iterdir()) if p.is_file())
        (bundle/'SHA256SUMS').open('x').write(checksum_text)
    write_deployment(block,digest)
    print(block,digest)


def write_deployment(block,digest):
    root=cfg.out(block);folder=cfg.BLOCKS[block];script=f'scripts/timely_capacity_campaign/{folder}/run_block.py'
    text=f'''# Block {block} — WAITING_FOR_CAMPAIGN_APPROVAL

Do not execute workload commands until this block is explicitly approved. Preparation did not run a pin, GPU inference or network session. No retry/overwrite, no automatic deployment.

Plan SHA256: `{digest}`

## Thor CPU-only check
```bash
cd /home/ainet/research/thor-mec-rate-dvfs-gate
python3 -B {script} check
```
'''
    if block=='A':text+='\nNo Edge deployment or connection. Block B readiness does not block A.\n'
    else:
        bundle=root/'edge_bundle_v1'
        text+='''
## Edge bundle
The existing expired-work-pruning `edge_v1` launcher cannot accept this new35-run order/plan hash. Reuse its backend, receive/inference worker, protocol, NumPy preprocessing and expiry END ledger byte-identically; deploy a new plan/session launcher into a NEW directory.
Manually transfer every file from this block's `edge_bundle_v1/` to `/tmp/tcc_split_edge_v1/` on Edge. No SSH/automatic copy. No engine/dataset transfer or rebuild.

```text
'''+(bundle/'SHA256SUMS').read_text()+'''```

## [Edge Server · Terminal] manual deployment
```bash
cd ~/research/thor-mec-inference
./venv/bin/python -B - <<'PYDEPLOY'
from pathlib import Path
import hashlib
src=Path('/tmp/tcc_split_edge_v1')
dst=Path('scripts/timely_capacity_campaign/block_b_split/edge_v1')
assert not dst.exists(), 'Existing deployment: STOP, no overwrite'
entries=[]
for line in (src/'SHA256SUMS').read_text().splitlines():
    digest,name=line.split('  ',1)
    assert Path(name).name==name
    data=(src/name).read_bytes()
    assert hashlib.sha256(data).hexdigest()==digest,name
    entries.append((name,data))
assert len(entries)==7
assert {name for name,_ in entries}=={'edge_server.py','pruning_edge_server.py','formal_server.py','formal_protocol.py','profile_edge_concurrency.py','campaign_config.py','plan.json'}
'''+f"assert hashlib.sha256((src/'plan.json').read_bytes()).hexdigest()=='{digest}'\n"+'''
dst.mkdir(parents=True,exist_ok=False)
for name,data in entries+[('SHA256SUMS',(src/'SHA256SUMS').read_bytes())]:
    with (dst/name).open('xb') as f:f.write(data)
print(dst.resolve())
PYDEPLOY
```
'''
        for phase in ('preflight','primary'):
            text+=f'''
## [Edge Server · Terminal] {phase} — only after B approval
```bash
cd ~/research/thor-mec-inference
./venv/bin/python -B scripts/timely_capacity_campaign/block_b_split/edge_v1/edge_server.py --phase {phase} \\
  --plan scripts/timely_capacity_campaign/block_b_split/edge_v1/plan.json \\
  --engine server/models/rtdetr_warehouse_v1.0.2.fp16.b1.engine \\
  --cache results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz \\
  --output results/timely_capacity_campaign/block_b_split/edge_{phase}01 \\
  --approve-plan-sha256 {digest}
```
'''
        text+=f'''
## [Thor · Terminal] B preflight — after Edge preflight LISTENING
```bash
cd /home/ainet/research/thor-mec-rate-dvfs-gate
python3 -B scripts/timely_capacity_campaign/common/edge_preflight.py --approve-plan-sha256 {digest}
```
Only E56,E72,E80 x30s once; original cached RAW64030, expired-only sender, C_E1, no Local inference/decode/frequency control. Inspect `edge_preflight01/gate.json`. E80<90% gives EDGE_PATH_LIMITED; invalid gives INCONCLUSIVE. Stop for user decision. No primary automatic chaining. Only after PASS start the separate primary Edge server above.
'''
    text+=f'''
## [Thor · Terminal] primary — future approved execution only
```bash
cd /home/ainet/research/thor-mec-rate-dvfs-gate
python3 -B {script} campaign --approve-plan-sha256 {digest}
```

## Post-run log-only analysis
```bash
python3 -B scripts/timely_capacity_campaign/common/campaign_analysis.py --block {block} --output results/timely_capacity_campaign/{folder}/analysis01
```
Thor results: `results/timely_capacity_campaign/{folder}/TCC{block}_R*/`. Preserve failed/invalid runs. Analyzer saves repeat values, mean/sampleSD/min/max, raw replay, placement and diagnostic tables; no source-result overwrite. Frequency preflight evidence is block-local.
'''
    if block=='B':text+='\nManually return complete Edge preflight/primary result directories to the corresponding new canonical block-B paths; no automatic transfer. Per-response timestamps and FINAL also remain on Thor.\n'
    (root/'DEPLOYMENT.md').open('x').write(text)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--block',choices=['A','B'],required=True);a=p.parse_args();prepare(a.block)
