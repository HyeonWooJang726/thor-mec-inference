"""Freeze V2.1 runtime independently of the unchanged experimental condition plan."""
import hashlib
import inspect
import json
from datetime import datetime,timezone
from pathlib import Path
from bootstrap_21 import ROOT,HERE,OUT,PLAN,EXPECTED_PLAN_SHA
import run_21

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def text(p,value):
    with p.open('x') as f:f.write(value)
def save(p,value):text(p,json.dumps(value,indent=2)+'\n')

def main():
    assert sha(PLAN)==EXPECTED_PLAN_SHA
    plan=json.loads(PLAN.read_text());assert len(plan['order'])==35
    assert json.loads((OUT/'behavior_validation.json').read_text())['status']=='PASS'
    old={p:h for p,h in plan['source_sha256'].items()}
    assert all(sha(ROOT/p)==h for p,h in old.items())
    new={str(p.relative_to(ROOT)):sha(p) for p in sorted(HERE.glob('*.py'))}
    adapted=run_21.adapted_source();text(OUT/'adapted_runtime_v2_1.txt',adapted)
    record=dict(version='V2.1',condition_plan_path=str(PLAN.relative_to(ROOT)),condition_plan_sha256=EXPECTED_PLAN_SHA,
        new_source_sha256=new,old_source_sha256=old,adapted_runtime_sha256=sha(OUT/'adapted_runtime_v2_1.txt'),
        run_order='Exactly original35 rows and IDs, new output namespace only',
        output_namespace=str((OUT/'E_MAX_72').relative_to(ROOT)),
        validation_sha256={p.name:sha(p) for p in OUT.glob('*validation.json')},
        created_utc=datetime.now(timezone.utc).isoformat(),scope='Instrumentation snapshot and explicit terminal diagnostics only',
        approval='Explicit V2.1 runtime SHA; no GPU/network/frequency execution in preparation')
    save(OUT/'runtime_manifest.json',record);digest=sha(OUT/'runtime_manifest.json')
    text(OUT/'runtime_manifest.sha256',digest+'  runtime_manifest.json\n')
    (OUT/'E_MAX_72').mkdir(exist_ok=False)
    edges={}
    bundle=PLAN.parent.parent/'edge_bundle_v2'
    for name,h in plan['edge_dependency_sha256'].items():
        assert sha(bundle/name)==h,name
        edges[name]=h
    assert sha(bundle/'E_MAX_72.json')==EXPECTED_PLAN_SHA
    save(OUT/'revision_record_v2_1.json',dict(status='BLOCK_B_V2_1_READY_WAITING_FOR_APPROVAL',
        previous_campaign_status='ABORTED_FOR_INSTRUMENTATION_BUG',old_plan_sha256=EXPECTED_PLAN_SHA,
        new_condition_plan_sha256=EXPECTED_PLAN_SHA,runtime_manifest_sha256=digest,
        old_source_sha256=old,new_source_sha256=new,Edge_dependencies_unchanged=edges,
        old_run_ids=[d.name for d in sorted(PLAN.parent.glob('TCCBV2_*'))],
        modified_original_files=[],exact_changes=[
            'checkpoint_21.py: immutable snapshots, per-manifest publication RLock, lock-free JSON encoding',
            'run_21.py: replace checkpoint capture only; queue counter snapshot under existing lock; new runtime provenance and output',
            'analysis_21.py: explicit true_unfinished/terminal partition; keep every existing integrity error and legacy backlog'],
        behavior_validation='4 branches,15 unique fixtures, unchanged worker/arrival/frontend AST and byte-equivalent raw decision/state traces',
        terminal_root_cause='Original pruning accounting already subtracts expired. Serialization exception skips final ready_queue_accounting publication (None). Legacy B=383 is diagnostic, not causal check operand.'))
    forensic=json.loads((OUT/'forensic_replay.json').read_text());bad=next(r for r in forensic if r['stored_integrity']=='INVALID')
    lines=['# BUGFIX V2.1 — instrumentation only','',
        'State: BLOCK_B_V2_1_READY_WAITING_FOR_APPROVAL. V2 E_MAX_72 is ABORTED_FOR_INSTRUMENTATION_BUG; its two run trees and all historical source/results remain unchanged.',
        '## Checkpoint race root cause',
        'V2 checkpoint directly passed the mutable manifest to common/run_campaign.py Context.write_json, then rate_dvfs_gate/run_rate_dvfs_gate.py write_json line34 json.dumps(indent=2). The live encoder yields between dictionary entries. EdgeLink.receiver finally publishes manifest[edge_final] (hybrid_capacity_extension/edge_link.py line126) without a shared capture lock. This is a source-confirmed concurrent structural writer. The preserved traceback confirms mutation during traversal; it does not identify the precise mutated key/interleaving.',
        'V2.1 wraps only the manifest in a publication-lock mapping. The existing worker/queue lock is held briefly to copy frame membership and queue counters; released before capture encoding. A separate manifest RLock protects root publication and immutable snapshot construction. Recursive freeze iterates CPython builtin shallow copies, never live nested containers; unsupported/free-threaded interpreters fail closed. JSON encoding, thawing and file I/O occur after locks are released. No sleep/retry/suppression. This is a structural snapshot, not an assertion of globally simultaneous multi-thread measurements.',
        '## Terminal-accounting root cause',
        'The original pruning analyzer already used U=assigned-completed-expired. Its exact queue-counter comparison at scripts/expired_work_pruning/analyze_pruning.py:80 failed because ready_queue_accounting was absent (None): the checkpoint exception occurred before final publication. It did NOT reject merely because legacy backlog_after_drain equalled383. Preserve that distinction.',
        'Checkpoint now records observed enqueue/start/expired counters at every capture. Existing final queue equality check remains unchanged. The analyzer explicitly adds true_unfinished_after_drain and per-path terminal_partition, rejects nonzero U/conflicting states/duplicate IDs, and retains every prior error. It never replaces lifecycle evidence using inferred raw counts.',
        '## Forensic replay',
        '|Path|Assigned|Completed|Expired|True unfinished|','|---|---:|---:|---:|---:|']
    for label,p in bad['terminal_partition'].items():lines.append(f"|{label}|{p['assigned']}|{p['completed']}|{p['expired_dropped']}|{p['true_unfinished']}|")
    lines += ['','Legacy backlog383 = expired383; U=0. Missing/duplicate source and admitted IDs=0. Raw terminal partition would pass corrected terminal accounting. The old run remains INVALID due to recorded race/process exit/lifecycle failures; no verdict rewrite. First run remains VALID on read-only replay.',
        '## Behavior and limitations','CPU reproduced old live-dict failure, tested1000 concurrent immutable snapshots and verified encoding releases locks. All4 branch plans and15 unique fixtures preserve admission/placement/source arrivals/pruning decisions/Edge submissions/timely-late-expired state. infer/front/arrivals/monitor/sample/save-records/fail AST are identical. Original sender/receiver class methods are reused with no changes. This establishes functional equivalence, not zero wall-clock overhead or new performance evidence.',
        '## Version and deployment',f'Original condition plan SHA: `{EXPECTED_PLAN_SHA}`',f'V2.1 runtime manifest SHA: `{digest}`',
        'All old/new file SHAs are in revision_record_v2_1.json and runtime_manifest.json. Edge dependency SHAs match the frozen bundle; no Edge code/protocol redeploy is needed if the deployed files match. Start a fresh Edge35-session process with output edge_E_MAX_72_v2_1_primary01. Thor starts original run1–35 in v2_1/E_MAX_72; no append/resume of V2.',
        'Exact new source locations: checkpoint_21.py:10–51; run_21.py:21–70; analysis_21.py:11 onward. Original files were not edited. See DEPLOYMENT_V2_1.md.']
    text(OUT/'BUGFIX_V2_1.md','\n\n'.join(lines)+'\n')
    deployment=f'''# V2.1 — WAITING FOR APPROVAL

No workload or frequency control was executed. Condition plan SHA stays `{EXPECTED_PLAN_SHA}`. Runtime SHA `{digest}`. Original Edge implementation and all wire/worker dependencies are unchanged. No new Edge bundle needed. Verify the existing deployed files against the following SHA values; no automatic SSH or deployment is performed.

```text
'''+''.join(f'{h}  {n}\n' for n,h in edges.items())+f'''{EXPECTED_PLAN_SHA}  E_MAX_72.json
```

## [Edge Server · Terminal] after approval
Reuse existing `scripts/timely_capacity_campaign/block_b_split/edge_v2/` only when it matches these SHA values. The launcher verifies dependency hashes. Start a NEW35-session server; never resume/append the aborted Edge run.

```bash
cd ~/research/thor-mec-inference
./venv/bin/python -B scripts/timely_capacity_campaign/block_b_split/edge_v2/edge_v2.py \\
  --plan scripts/timely_capacity_campaign/block_b_split/edge_v2/E_MAX_72.json \\
  --engine server/models/rtdetr_warehouse_v1.0.2.fp16.b1.engine \\
  --cache results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz \\
  --output results/timely_capacity_campaign/block_b_split/edge_E_MAX_72_v2_1_primary01 \\
  --approve-plan-sha256 {EXPECTED_PLAN_SHA}
```

## [Thor · Terminal] after approval and Edge LISTENING
```bash
cd /home/ainet/research/thor-mec-rate-dvfs-gate
python3 -B scripts/timely_capacity_campaign/block_b_split/v2_1/run_21.py campaign \\
  --approve-runtime-sha256 {digest}
```

Thor output: `results/timely_capacity_campaign/block_b_split/v2_1/E_MAX_72/TCCBV2_*/`.
Exactly original35 rows, starting at run1. Original per-run IDs retained under new namespace. A new frequency preflight occurs only during approved future campaign. Existing eight-run Edge preflight evidence is reused; no new preflight network campaign is added.

Read-only preparation check:
```bash
python3 -B scripts/timely_capacity_campaign/block_b_split/v2_1/run_21.py check
```
Post-run log-only analysis:
```bash
python3 -B scripts/timely_capacity_campaign/block_b_split/v2_1/analysis_21.py \\
  --output results/timely_capacity_campaign/block_b_split/v2_1/E_MAX_72/analysis01
```
Manually return Edge raw results into NEW `v2_1/received_edge_E_MAX_72_v2_1_primary01/`. Never merge with old V2 or Thor run trees. No automatic retry/commit/push.
'''
    text(OUT/'DEPLOYMENT_V2_1.md',deployment)
    print('RUNTIME_SHA',digest);print(json.dumps(new,indent=2))

if __name__=='__main__':main()
