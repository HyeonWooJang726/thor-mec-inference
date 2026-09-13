"""Record validated recovery provenance and immutable continuation plan before GPU."""
from pathlib import Path
import sys,json,hashlib,difflib,subprocess
HERE=Path(__file__).resolve().parents[1];OLD=HERE.parent
sys.path.append(str(OLD/'_code'))
from core import save,utc
from environment import sha,verify
verify();validation=json.loads((HERE/'cpu_replay_validation.json').read_text());assert validation['validation']=='PASS'
plan=json.loads((OLD/'frozen_plan.json').read_text());historical=json.loads((OLD/'campaign_status.json').read_text())
assert historical['campaign_status']=='HALTED' and historical['rows'][0]['status']=='FAIL'
assert all(not (OLD/r['acquisition_id']).exists() for r in plan['acquisitions'][1:])
oldhashes=json.loads((HERE/'preservation_before.json').read_text());mismatches=[p for p,h in oldhashes.items() if not Path(p).exists() or sha(p)!=h];assert not mismatches,mismatches
save(HERE/'preservation_pre_launch.json',dict(files=len(oldhashes),hash_mismatches=mismatches,original_status='HALTED',original_smoke_status='FAIL'))
reuse=dict(reuse_decision='VALIDATED_REUSE',time=utc(),historical_status='FAIL',historical_campaign_status='HALTED',acquisition_validity_after_forensic_review='VALID',reused_as_smoke='YES',primary_sample=False,original_child_exit=0,completed_frames=780,original_artifact=str(OLD/'smoke_fixed_c4'),replay=str(validation['real_replay']),criteria={k:True for k in ['A_raw_integrity','B_exit_zero','C_post_acquisition_failure_only','D_measurement_critical_unchanged','E_full_CPU_replay','F_success_failure_bookkeeping','G_FIXED_C4_full_path']},reason='Acquisition completed normally. Original analyzer duplicate keyword reproduced on real raw input; minimal postprocessing copy passes full replay and deterministic fixtures. No GPU/runtime source changed. No first-smoke rerun.')
save(HERE/'smoke_reuse_decision.json',reuse)
manifest=dict(recovery_id='local_dynamic_c_value_gate_recovery_001',original_campaign_id=historical['campaign_id'],original_campaign_status='HALTED',original_smoke_status='FAIL',original_smoke_reused='VALIDATED_REUSE',original_executed_GPU_acquisitions=1,remaining_acquisitions=plan['acquisitions'][1:],additional_smoke=1,primary=30,primary_expected_frames=351000,total_GPU_limit_including_original=32,original_plan_path=str(OLD/'frozen_plan.json'),original_plan_sha256=sha(OLD/'frozen_plan.json'),execution_order_sha256=sha(OLD/'execution_order.csv'),policies=plan['policies'],gate=plan['gate'],cooldown_s=plan['cooldown_s'],warmup_inferences=plan['warmup_inferences'],parent_timeout_s=plan['parent_timeout_s'],runtime_watchdog_s=plan['runtime_watchdog_s'])
save(HERE/'continuation_manifest.json',manifest)
save(HERE/'continuation_status.json',dict(campaign_id=manifest['recovery_id'],campaign_status='READY',created_at=utc(),historical_campaign_status='HALTED',reused_original_smoke='VALIDATED_REUSE',rows=[dict(r,status='UNATTEMPTED') for r in manifest['remaining_acquisitions']]))
(HERE/'recovery_plan.md').write_text('''# Recovery 001 — frozen continuation, no redesign

Original campaign and original smoke campaign row remain HALTED / FAIL. This recovery does not amend that history.

1. The original FIXED_C4 GPU acquisition completed with actual exit 0 and 780/780 frames.
2. The original summary failed after acquisition because `expected_frames` occurred in both `**row` and an explicit keyword.
3. Reproduced the exact failing analyzer path on original raw CSV/events with writes prohibited.
4. Original source is preserved. A recovery-only analyzer copy validates trace/row/runtime metadata/manifest/termination expected counts, selects the trace count as the canonical value, and writes it once.
5. Original raw replay, all policy/trace/duration CPU fixtures, invalid expected-count fixtures, failure validator, success/failure/HALT bookkeeping and full 30-row report path passed without GPU. Synthetic fixtures are regression evidence only, never measured data.
6. Reuse original FIXED_C4 as integration evidence only. Execute original frozen runtime at its original path for the previously unattempted lookup smoke, then precisely the existing 30-row primary order.
7. All new GPU raw directories are previously unused original manifest acquisition paths under the experiment root. Recovery state, report and ledger are here. Historical status/log/raw/forensic records are not written.
8. Hold original campaign lock without truncation and a separate recovery lock. Persistent child processes use dedicated sessions, actual wait/exit accounting, 420-s parent timeout, no retry. Any failure HALTs. Primary requires lookup LIVE_END_TO_END_PASS and repeated freeze/environment audit.

Unchanged: P=4; policies C2/C4/current-K lookup; Trace A/B; 30 FPS exact integer arrivals; B=1; engine; source mapping; preprocessing; a/b/r/s/c; FIFO and admission; cap update; 60-s primary; deadline 1/30 s; windows; sequence/seed; engineering thresholds; warm-up 0 and deliberate cooldown 0 inherited from original plan. No power/clock/dependency changes.

Original runtime/core and imported measurement-critical sources remain byte-identical. The postprocessing/report copies only change canonical expected-count validation and recovery output/input routing. New bookkeeping/launcher manage recovery state only. Freeze is checked before/after each acquisition and before primary. No code change is permitted after the freeze.

Engineering gate remains both traces Δ2 and Δ4 ≥0.5 pp, each positive in at least 4/5 rounds. Comparison is only against predeclared C2 and C4; no claim about all possible fixed caps. Original first smoke and new smoke are excluded from primary performance analysis.

No commit/push; no Formal or figure changes.
''')
changes=[];patch=''
for orig,new in [('analyze.py','recovery_analysis.py'),('report.py','recovery_report.py'),('driver.py','continuation.py'),('launch.py','launch_recovery.py')]:
 a=OLD/'_code'/orig;b=HERE/'_code'/new
 changes.append(dict(original_path=str(a),recovery_path=str(b),before_sha256=sha(a),after_sha256=sha(b),original_modified=False,scope='postprocessing/report/bookkeeping only'))
 patch+=''.join(difflib.unified_diff(a.read_text().splitlines(True),b.read_text().splitlines(True),fromfile=str(a),tofile=str(b)))
(HERE/'code_patch.diff').write_text(patch)
critical={p:h for p,h in json.loads((OLD/'frozen_hashes.json').read_text()).items() if not p.endswith(('/analyze.py','/report.py','/driver.py','/launch.py','/prepare.py','/test_cpu.py'))}
save(HERE/'code_hashes_before_after.json',dict(measurement_critical_changed=False,measurement_critical={p:dict(before=h,after=sha(p),MATCH=h==sha(p)) for p,h in critical.items()},postprocessing_copies=changes,new_bookkeeping=str(HERE/'_code/bookkeeping.py')))
# Compile without pycache or modifying source; fixtures already executed live shared functions.
for p in (HERE/'_code').glob('*.py'):compile(p.read_text(),str(p),'exec')
pins=[*(HERE/'_code').glob('*.py'),HERE/'continuation_manifest.json',HERE/'smoke_reuse_decision.json',HERE/'cpu_replay_validation.json',OLD/'campaign_status.json',OLD/'frozen_plan.json',OLD/'execution_order.csv',OLD/'input_manifest.json',OLD/'postmortem/smoke_forensic_validation.json']
save(HERE/'recovery_freeze.json',dict(frozen_at=utc(),CPU_validation='PASS',GPU_acquisitions_after_original=0,hashes={str(p):sha(p) for p in pins}))
print('VALIDATED_REUSE; freeze complete; remaining 1 smoke + 30 primary; original files unchanged:',len(oldhashes))
