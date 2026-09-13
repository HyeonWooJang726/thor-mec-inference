Nonnegative symlog axes start at zero; any below-zero portion of mean ± SD is outside the display. SD bars describe variation, not feasible-value or confidence bounds.

## figure01_dmr

DMR vs C; all frames including startup and drain. Points: means of five run DMRs; error bars: run-level sample SD. K2/C1 includes the post-campaign replacement. Low-K panel is an axis/detail view, not data exclusion.

## figure02_queue

Queue vs C. Points are five-run means; error bars are run-level sample SD. Percentile panels show mean of run-level P95 values (or P99), not pooled percentiles. Queue/local axes use symlog with 1 ms linear threshold for display only.

## figure03_service

Service vs C. Points are five-run means; error bars are run-level sample SD. Percentile panels show mean of run-level P95 values (or P99), not pooled percentiles. Service is host-observed request service, not isolated kernels.

## figure09_local_tails

Local_Tails vs C. Points are five-run means; error bars are run-level sample SD. Percentile panels show mean of run-level P95 values (or P99), not pooled percentiles. Queue/local axes use symlog with 1 ms linear threshold for display only.

## figure04_mean_A

Five-run mean A with run-level sample SD, window [t0,t0+60s). A counts host-observed in-flight requests; not GPU utilization or kernel parallelism. Mean A shares an interval-area accounting identity with service duration.

## figure05_cap_and_waiting

Cap saturation and exact cap-saturated-with-waiting state fractions over [t0,t0+60s). Means ± run-level sample SD. The right axis uses a 0.1 percentage-point symlog display threshold. A=C with Q=0 is not queued admission blocking. Neither metric is device utilization.

## figure06_mean_decomposition

Stacked equal-run mean components; total error bars are sample SD of actual run local means. Dotted line: nominal 33.333… ms deadline. Component P95s are not added. K7 uses symlog to retain C1 and all other cells; nonlinear bar heights are not proportional shares.

## figure07_completed_vs_offered

Completed FPS means ± run-level sample SD. Matching dashed lines are offered 30K FPS. Slight excess over offered rate follows the denominator definition, not throughput beyond source pacing. Near-offered FPS can coexist with high DMR.

## figure08_static_regret

Post-hoc gaps between five-run mean DMR and the minimum selected from the same C grid. This descriptive heatmap has no uncertainty interval for the selected minimum. It is not an online-policy evaluation or achievable Dynamic-C gain.
