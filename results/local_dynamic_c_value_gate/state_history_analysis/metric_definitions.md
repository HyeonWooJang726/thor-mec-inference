# Metric and reconstruction definitions

Inputs: only the 30 PASS primary acquisitions enumerated in `../recovery_001/continuation_manifest.json` / continuation_status.json, with 11,700 requests each. Smoke and CPU synthetic fixtures are excluded. Existing source definitions were read in `_code/core.py`, `_code/runtime.py`, `_code/analyze.py` and recovery postprocessing. Input SHA256s are in input_hashes.json. No GPU work, controller, predictor or performance source modification.

- Logical arrival: `a=t0+floor(global_tick*1e9/30)` ns. Deadline is the exact rational `d=a+1e9/30`, not a rounded integer-ns deadline. Miss iff `(c-a)*30 > 1e9`.
- b: front-end start before pull-sample. r: completion of ready enqueue. s: end of admission bookkeeping immediately before inference. c: immediately after the frozen infer call returns, before completion publication. Queue=s−r; service=c−s; start lag=b−a; front end=r−b; local=c−a. Service is system-level, not pure kernel latency.
- Phase cohorts use global ticks: [0,450), [450,900), [900,1350), [1350,1800). Each K6 phase has 2,700 arrivals and each K7 phase 3,150. Later completion retains the original cohort. DMR=100*miss_count/cohort_count. Per-cohort means/P95/P99 include every request. No exclusions.
- Startup [0,1), transitions [15,16), [30,31), [45,46), and phase remainders [1,15), [16,30), [31,45), [46,60) remain separate secondary windows. They do not replace the 60-s result.
- Phase `calendar_completed_fps`: actual completions in calendar [phase_start,phase_end) divided by 15 seconds. It can contain earlier cohorts and excludes completions after the window. This is deliberately not called per-cohort throughput. Full-run FPS remains 11700 / ((last_c−t0)/1e9); drain=max(0,last_c−t0−60s).

## Exact event-state sampling

For a boundary b, `LEFT_LIMIT` uses starts/arrivals strictly `<b` and completions not strictly `<b` (so completion exactly at b still belongs to the state immediately before b). At requested post-boundary times, `RIGHT_CONTINUOUS` uses starts/arrivals `<=t` and completions `>t`. Counts are reconstructed directly from raw interval endpoints; no uniform grid is substituted for actual events. The latest published event and cap-apply event on the same side determine online counter/observed K/applied C. Sequence IDs preserve same-ns publication ordering. Slack quantiles are recomputed at the exact requested time, not held stale from the last event.

- A_service: requests with s<=t<c (with strict-side adjustment at b−). This can exceed a reduced C; C bounds admission, not already-running requests.
- Ready queue: r<=t<s. This is distinct from the published admission reservation counter.
- **Logical unfinished backlog** (the primary B6 definition): arrivals already due minus actual completions, i.e. a<=t<c. It includes due-but-not-generated requests.
- **Generated unfinished**: actual_generation<=t<c. This matches the generated-backlog concept in the original experiment. Due-not-generated is a<=t<actual_generation. Verified identity: logical unfinished = generated unfinished + due-not-generated.
- Online active counter releases at completion publication, not c. Actual reconstructed A and online counter must not be interchanged. Actual c-based state reconstruction is offline evidence; online observer/publication latency is not newly measured by this analysis.
- Slack numerator `1e9 + 30*(a−t)` is exact integer arithmetic in units of one-thirtieth ns. Divide by 30,000,000 for ms. Late/expired means numerator<=0; urgent(5/10 ms) means 0<numerator<=5/10*30,000,000. Quantiles use linear NumPy percentiles. Empty unfinished/ready sets have NA quantiles and NA late fractions, not synthetic zero slack; counts are zero.
- At these tick-aligned boundaries, the immediately preceding arrival has deadline b−2/3 ns because arrival timestamps are floored. Thus slack=−0.0000006666667 ms and late fraction=100% can occur with only a few just-expired in-flight requests. **This is not equivalent to tens/hundreds of milliseconds of accumulated deadline debt.** Interpret count, Q and slack magnitude together.
- Mean state occupancy within a phase is exact interval area/window duration. Peaks are evaluated at actual state change timestamps, not one-second samples. `trace_order_analysis.csv` additionally preserves one-second state samples for readable evolution; these are not used to claim exact settling times.

## Pairing, uncertainty and provenance

All paired deltas in this Phase B are **lookup minus fixed**, so positive DMR delta means lookup is worse. This is the opposite sign of Phase A's improvement Δ=fixed−lookup and is stated in column/report labels. Whole-run DMR contributions are exact miss-count differences times 100/11700; arithmetic attribution is not causal attribution.

Experimental unit is acquisition/run, not frame. Per trace/policy/phase n=5; sample SD uses ddof=1. Run-level P95 averaging is not pooled P95; component P95s are not additive. Same-round pairing aligns blocks across separate processes, not frame-level counterfactual outcomes. Figure 2 first averages same-direction boundaries within each acquisition, then reports mean/SD across 10 acquisitions (five per trace), avoiding transition pseudo-replication.

Same-K comparisons are descriptive history contrasts; phase source sample ranges and cold-start/initialization differ. Automated aliasing candidates are screening rows, not confirmed useful-control states; review qualification is recorded separately. No substantial-effect threshold, controller threshold, learned model, significance test or causal identification was fitted.
