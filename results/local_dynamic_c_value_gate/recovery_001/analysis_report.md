# Limited Local Dynamic-C value gate

Verdict: **NO_OBSERVED_ADVANTAGE_IN_TESTED_TRACES**. Campaign: COMPLETED.

This is a limited pilot in two measured traces, not a final controller or general proof of Dynamic-C superiority. Positive Δ=fixed−lookup means fewer misses under lookup. The engineering gate is predeclared 0.5 pp and ≥4/5 improving rounds for both contrasts in both traces; 1 pp and relative reduction are secondary only.

| Trace | Policy | n | DMR mean ± sample SD (%) | Local run-P95 mean ± sample SD (ms) | Drain mean (s) | Integrity |
|---|---|---:|---:|---:|---:|---|
| A | FIXED_C2 | 5 | 40.2120 ± 0.4229 | 45.6086 ± 0.9052 | 0.0162 | PASS |
| A | FIXED_C4 | 5 | 40.6581 ± 0.2905 | 45.0535 ± 0.3194 | 0.0101 | PASS |
| A | K_LOOKUP_C2_C4 | 5 | 41.2650 ± 0.3534 | 45.7280 ± 0.3110 | 0.0087 | PASS |
| B | FIXED_C2 | 5 | 53.8427 ± 2.9443 | 313.6468 ± 66.9396 | 0.0076 | PASS |
| B | FIXED_C4 | 5 | 42.1094 ± 0.7330 | 54.8091 ± 16.0881 | 0.0065 | PASS |
| B | K_LOOKUP_C2_C4 | 5 | 43.4017 ± 2.5215 | 51.2985 ± 6.4866 | 0.0090 | PASS |

| Trace | Fixed comparator | Δ mean ± SD (pp) | Improving rounds | Relative reduction (%) | Mean ≥1 pp |
|---|---|---:|---:|---:|---|
| A | FIXED_C2 | -1.0530 ± 0.7343 | 1/5 | -2.6186 | False |
| A | FIXED_C4 | -0.6068 ± 0.4579 | 1/5 | -1.4925 | False |
| B | FIXED_C2 | 10.4410 ± 2.5710 | 5/5 | 19.3917 | True |
| B | FIXED_C4 | -1.2923 ± 2.7903 | 2/5 | -3.0689 | False |

## Transition windows
1 s is a predeclared reporting window, not measured settling time. Negative fixed−lookup differences below mean additional lookup misses in that arrival window; they are not isolated causal switching costs. Workload changes, carried backlog, service and front-end/start-lag response can coexist. Cohorts retain their logical arrival phase/deadline. Original static metrics are not substituted as dynamic comparators.
- A phase 1 vs FIXED_C2: Δ=-2.4762 pp, positive 1/5.
- A phase 2 vs FIXED_C2: Δ=-0.5556 pp, positive 1/5.
- A phase 3 vs FIXED_C2: Δ=-2.7619 pp, positive 0/5.
- A phase 1 vs FIXED_C4: Δ=0.4762 pp, positive 2/5.
- A phase 2 vs FIXED_C4: Δ=-0.0000 pp, positive 2/5.
- A phase 3 vs FIXED_C4: Δ=-0.4762 pp, positive 3/5.
- B phase 1 vs FIXED_C2: Δ=44.1111 pp, positive 4/5.
- B phase 2 vs FIXED_C2: Δ=-5.9048 pp, positive 0/5.
- B phase 3 vs FIXED_C2: Δ=-0.5556 pp, positive 2/5.
- B phase 1 vs FIXED_C4: Δ=0.1111 pp, positive 2/5.
- B phase 2 vs FIXED_C4: Δ=-3.5238 pp, positive 2/5.
- B phase 3 vs FIXED_C4: Δ=-0.0000 pp, positive 2/5.

## Measurement and limitations
All policies use one shared engine, P=4 independent execution contexts/streams/buffers and four owning workers; Formal used a context/worker count equal to C. Frozen TensorRT infer, preprocessing and input pipeline code are reused unchanged. New cap admission and event logging are identical across all three policies. Warm-up=0 and deliberate cooldown=0 inherit Formal; startup frames are retained. Internal watchdog=300 s from trace setup; parent timeout=420 s from process start. All scheduled samples must complete; actual natural EOS is recorded separately from trace-budget termination.
A_service is reconstructed from [s,c), online active counter decrements at completion publication. Actual c is never available to the controller before that notification. Dynamic non-preemptive cap decreases can produce A>C; no new admission occurs while the counter is ≥C. Cap equality alone is not waiting or GPU utilization. Occupancy denominators are the offered [t0,t0+60s) window. Backlog includes every generated but uncompleted request; due-but-not-generated is separate. Transition CSV retains active/request cohort distinctions and separate times for A≤C, A<C and first new admission; it also retains counter-based versions.
Run is the repeated unit; same video content is reused. Mean run-P95s are not pooled P95s; component P95s are not additive. Same-round pairing matches execution blocks, not identical process state. Equal-time K6/K7 windows have 6:7 frame weighting. Static S(C) is a descriptive baseline-selection score, not a forecast or performance bound. Only tested fixed baselines {C2,C4} are compared. High absolute DMR is reported even if improvement exists; neither stream capacity nor long-term queue stability is established.
Environment snapshots before/after each acquisition preserve temperatures, clock ranges/current frequencies and host process lists. These between-run readings do not identify causal thermal/clock effects inside a phase; no new hot-path profiler was used. No future trace information enters Controller.notify(current_K).

## Next-stage interpretation
If PROMISING, retain current-K lookup as a baseline and consider a simple queue/deadline-slack controller next. Otherwise defer assuming Dynamic-C is the core contribution; limited weak results do not refute every Dynamic-C policy. Local/Edge placement, joint C_L/C_E and complex methods are outside this experiment. No follow-up experiment is launched.

## Acquisition accounting
{"smoke": {"PASS": 1, "FAIL": 0, "ABORTED": 0, "UNATTEMPTED": 0}, "primary": {"PASS": 30, "FAIL": 0, "ABORTED": 0, "UNATTEMPTED": 0}}
Primary valid frames: 351000 / 351000. Smoke is never included in primary.

## Preservation
Figure relocation manifest/reference audit are in this root. The 28 static figure/caption files moved to analysis_valid5/figures/supporting_static with unchanged SHA256. Representative figures retain revision_002 main and revision_001 heatmap. Frozen Formal/raw/campaign and unrelated scripts are untouched. No automatic commit/push.

## Figures
Figure 1: DMR means and run-level sample SD (n=5). Figure 2: same-time state samples and 1-second arrival-bin DMR, means over five runs; boundaries are at 15/30/45 s. Backlog is generated requests minus actual completions. A and cap are application states, not GPU utilization.
