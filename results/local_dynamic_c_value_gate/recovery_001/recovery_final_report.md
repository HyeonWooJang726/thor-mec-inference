# Dynamic-C recovery 001: final recovery and experimental outcome

**Continuation COMPLETED; primary 30/30 PASS, 351,000 requests. Predeclared verdict: NO_OBSERVED_ADVANTAGE_IN_TESTED_TRACES.**

## Four research answers
1. Trace A: lookup DMR increased by 1.0530 pp versus C2 and 0.6068 pp versus C4. Trace B: lookup reduced DMR by 10.4410 pp versus C2 but increased it by 1.2923 pp versus C4.
2. Positive fixed-minus-lookup paired differences occurred in 1/5, 1/5, 5/5 and 2/5 rounds for A/C2, A/C4, B/C2 and B/C4 respectively. Neither trace had lookup mean DMR below both fixed baselines.
3. Additional lookup misses were observed in some transition arrival windows, including B [30,31) s versus C4 (+3.5238 pp). These are policy/window comparisons, not isolated causal cap-switching costs. Changed workload, carried backlog and latency components coexist.
4. Defer treating this current-K lookup or Dynamic-C as an established core performance contribution. The limited evidence does not refute other Dynamic-C policies. No further GPU work was launched. Comparisons are only against the two predeclared fixed baselines C=2 and C=4.

## Historical incident and recovery timeline
1. Original FIXED_C4 smoke started 2026-09-13T08:26:40.350064+00:00.
2. Actual GPU child completed normally: exit 0; 780/780 requests; finished 2026-09-13T08:26:46.858201+00:00.
3. The original analyzer then raised `TypeError: dict() got multiple values for keyword argument 'expected_frames'` at summary construction.
4. Original campaign row became FAIL and original campaign became HALTED at 2026-09-13T08:26:47.210224+00:00. Those records remain unchanged.
5. Recovery reproduced the exact error using original per-frame/event input, with original writes prohibited; see original_error_traceback.txt.
6. Added a recovery-only postprocessor copy. Canonical expected count comes from the frozen Trace; row, manifest, runtime metadata and termination counts must agree. The value is emitted once. No original source was modified.
7. Full actual-smoke CPU replay passed summary, windows, transitions, CSV/JSON, validator, success/failure bookkeeping and report inputs. CPU-only fixtures exercised all policies, both traces and durations, mismatch errors, atomic/non-preemptive admission, delayed producer and complete 30-row report generation. Synthetic fixtures are explicitly excluded from research data.
8. Original FIXED_C4 was declared VALIDATED_REUSE as integration evidence only; historical campaign FAIL was not converted to PASS.
9. Remaining lookup smoke ran once: actual child exit 0, 780/780, LIVE_END_TO_END_PASS.
10. Original 30 primary acquisitions then ran in the unchanged order. All passed. No retries, replacements or additional sweep.

## Freeze and preservation
Original GPU/runtime/preprocessing/core/engine/source/config/plan hashes match. Recovery postprocessing and bookkeeping code was frozen before the live lookup smoke and stayed unchanged through all primary acquisitions. Per-run guards rechecked hashes and environment; pre_primary_freeze_audit.json records the post-smoke audit.
Original protected files checked: 9773; SHA256 mismatches: 0. This includes the entire existing Formal tree, figures, original Dynamic-C incident/raw/source and unrelated script paths. Git status is unchanged from recovery start; no staging, commit or push.
Original analyzer SHA256: 695ef12520a6878ce6b1dc22b876368a70ca6ad4f4f379aaff928ab3bec9dbb4
Recovery analyzer SHA256: af7315b83b9d355141baaf76ca71e1110bbd9989d6d75132c80f0eff9179a771

## Primary results
Run is the repeated unit; n=5 per trace/policy; ± is sample SD (ddof=1). P95 values below are means of run-level P95 values, not pooled percentiles. Startup and all late completions are included.
| Trace | Policy | n | DMR (%) | Local run-P95 (ms) | Drain mean (s) | Integrity |
|---|---|---:|---:|---:|---:|---|
| A | FIXED_C2 | 5 | 40.2120 ± 0.4229 | 45.6086 ± 0.9052 | 0.0162 | PASS |
| A | FIXED_C4 | 5 | 40.6581 ± 0.2905 | 45.0535 ± 0.3194 | 0.0101 | PASS |
| A | K_LOOKUP_C2_C4 | 5 | 41.2650 ± 0.3534 | 45.7280 ± 0.3110 | 0.0087 | PASS |
| B | FIXED_C2 | 5 | 53.8427 ± 2.9443 | 313.6468 ± 66.9396 | 0.0076 | PASS |
| B | FIXED_C4 | 5 | 42.1094 ± 0.7330 | 54.8091 ± 16.0881 | 0.0065 | PASS |
| B | K_LOOKUP_C2_C4 | 5 | 43.4017 ± 2.5215 | 51.2985 ± 6.4866 | 0.0090 | PASS |

Δ = fixed DMR − lookup DMR. Positive values favor lookup. Same-round pairing aligns execution blocks, not identical runtime state.
| Trace | Comparator | Mean Δ ± SD (pp) | Positive rounds | Relative reduction (%) | Mean ≥1 pp | All 5 paired differences (pp) |
|---|---|---:|---:|---:|---|---|
| A | FIXED_C2 | -1.0530 ± 0.7343 | 1/5 | -2.6186 | False | -1.7265, -1.4786, -0.6667, -1.4444, 0.0513 |
| A | FIXED_C4 | -0.6068 ± 0.4579 | 1/5 | -1.4925 | False | -1.0769, -0.9658, 0.0684, -0.6325, -0.4274 |
| B | FIXED_C2 | 10.4410 ± 2.5710 | 5/5 | 19.3917 | True | 6.9573, 12.0598, 12.8291, 8.4701, 11.8889 |
| B | FIXED_C4 | -1.2923 ± 2.7903 | 2/5 | -3.0689 | False | -0.2821, -1.5128, 0.7350, -6.0171, 0.6154 |

## Transition behavior
Primary lookup had 15 C2→C4 increases and 15 C4→C2 decreases. All 15 decreases had both service A and online admission counter greater than the new cap at application. Running requests continued; no extra admission while counter≥new C. No early cap application or admission/cap ordering violations were detected.
For decreases, mean delays after actual apply were: service A≤C 5.311 ms; service A<C 7.845 ms; online counter≤C 5.331 ms; online counter<C 7.863 ms; first new admission 10.238 ms (range 1.650–12.128 ms). These are separate events, not a single settling time. For increases, first new admission averaged 11.763 ms (range 10.121–14.098 ms); a free cap does not imply a ready request is available.
The lookup smoke also exercised C4→C2 with active counter 3 at application and no forbidden admission. Actual completion and completion publication are distinct; the controller never uses offline completion labels.
Transition arrival windows are the predeclared [15,16), [30,31), [45,46) s. In B [30,31), lookup had +5.9048 pp misses versus C2 and +3.5238 pp versus C4. In A [15,16) and [45,46), lookup had +2.4762/+2.7619 pp versus C2. Not every window worsened: B [15,16) improved 44.1111 pp versus C2. See window_paired_comparison.csv for every comparison. Tiny printed negative zero values are floating point roundoff, not evidence of extra misses.

## Latency, startup, backlog and environment
Trace A mean queue times (C2/C4/lookup) were 11.117/6.349/9.491 ms and service times 8.613/14.693/12.111 ms. Trace B queue means were 71.832/9.724/10.646 ms and service means 8.823/14.707/12.258 ms. These system-level responses do not identify GPU kernel contention or prove a unique cause of DMR differences.
Trace B C2 showed a large initial generated backlog and delayed clearance through its first K7 phase in the recorded state samples. Mean local run-P95 was 313.647 ms versus 54.809 ms (C4) and 51.298 ms (lookup). This coexists with the C2 disadvantage on Trace B. The 60-s result does not establish long-term queue stability.
Startup [0,1) s mean DMR was 100% for every trace/policy except Trace A C4 (98.222%). These samples were retained. Mean front-end time was 12.741–13.380 ms across the six conditions and start lag 1.188–1.731 ms. These components are material to end-to-end latency; queue+service alone is not local latency.
Completed FPS means were 194.947–194.979, versus 195 offered requests/s over the complete trace. All planned requests drained; mean post-60-s drain was 0.0065–0.0162 s. Due-but-not-generated peak was 7 in each run; this state was retained separately from generated backlog.
Between-acquisition snapshots consistently reported MAXN, TensorRT 10.16.2.10, DVFS unlocked and clock min<max. Recorded readable thermal sensors spanned 43.468–77.781 °C; one sensor was unavailable and was not imputed. No competing GPU experiment was detected by the frozen process guard. These snapshots do not establish within-phase thermal/clock causation or exclude all background activity.
All three policies used common P=4 contexts/streams/private buffers/workers. Original static Formal allocated resources according to C; it is contextual evidence only. The original static S(C) score is a descriptive selection calculation, not a prediction of this measured dynamic trace. No new performance-path change was introduced during recovery.

## Engineering verdict and next step
**NO_OBSERVED_ADVANTAGE_IN_TESTED_TRACES.** Every validity and planned repetition requirement passed, but neither trace had lookup mean DMR below both fixed baselines. In particular Δ4 was negative on both traces. Thus the predeclared promising gate (both Δ≥0.5 pp, each positive in ≥4/5 rounds, on both traces) was not met.
Absolute DMR remains high (roughly 40–54%); reduced DMR against one comparator would not demonstrate deadline satisfaction. This result warrants deferring a claim that the current-K lookup or Dynamic-C is the established main performance contribution. It does not reject all possible Dynamic-C policies. Any next queue/deadline-aware controller work requires a separately scoped decision; no follow-up experiment was executed.

## Acquisition and file accounting
Continuation: 2026-09-13T08:53:24.035508+00:00 to 2026-09-13T09:25:29.466594+00:00; persistent detached session PID 159761. The original historical campaign remains HALTED. Continuation COMPLETED does not overwrite its history.
Original GPU acquisitions: 1 FIXED_C4 smoke. Additional: 1 lookup smoke + 30 primary. Total: 32, all actual child exits 0. Primary measured requests: 351,000; smoke requests: 1,560; physical total: 352,560. Original campaign still contains one postprocessing FAIL incident; it is not hidden as a GPU failure or erased. Automatic retries: 0.
The acquisition count in integrity.json describes the continuation only (one new smoke). smoke_reuse_decision.json and final_validation.json add the original reused smoke to the integration/acquisition accounting.
The unchanged generated analysis_report.md inherits the old generic preservation paragraph: relocation manifests it mentions live in the parent experiment directory, not recovery_001. Figure relocation happened before this recovery; no static figures were moved or changed here.
Artifacts: recovery_plan.md; root_cause.json; original_error_traceback.txt; code_patch.diff; code_hashes_before_after.json; recovery_freeze.json; cpu_replay_validation.json; smoke_reuse_decision.json; continuation_manifest.json; continuation_status.json; pre_primary_freeze_audit.json; final_validation.json.
Primary raw input paths: ../primary_01 through ../primary_30. Remaining smoke raw: ../smoke_lookup. Original smoke raw: ../smoke_fixed_c4 (unchanged). Derived primary per-run/window/transition/policy/paired CSVs and generated report are in this directory. Synthetic CPU fixtures under cpu_tests/ are never performance measurements.
Figures: figures/figure01_policy_DMR.{png,pdf}; figures/figure02_state_deadlines.{png,pdf}. PNG and PDF renderings visually checked: no clipped labels or overlapping legend/data. Figure 2 uses one-second state samples; its sampled cap step must not be used to infer exact cap-update latency. Exact logical/notification/apply times are preserved in events and transition CSV.
No commit or push. Existing unrelated changes and prior figure relocation working-tree status remain untouched.
