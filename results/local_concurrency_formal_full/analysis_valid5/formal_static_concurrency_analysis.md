# 1. Dataset Integrity



Primary integrity PASS: 56 K,C conditions, exactly five valid measurements each, 280 primary runs and 2,016,000 primary frames. Original campaign remains 279 PASS/1 FAIL (global index 220, K2/C1/run04, exit −11); replacement01 is a later PASS. Physical acquisitions retain 281 runs and 2,019,600 completed frames. No duplicates, missing required metric, identity mismatch or selective run exclusion. Other than the predefined invalid process exit, every valid run remains included.

Canonical primary metrics were checked against formal_kc_aggregate_valid5.csv. New cap-with-waiting state fractions use a narrow timestamp sweep, not regeneration of all original latency metrics. 265 per-frame files were read for required state intersections and/or selective diagnostics; 15 zero-cap cases need no raw read. Detailed deadline diagnostics cover 22 specified conditions × all five runs (110 runs), recorded in raw_selection_policy.json. The original failed run is read only for optional secondary sensitivity.



# 2. Metric Definitions



See metric_definitions.md for source paths and exact boundaries. Deadline: (c−a)*30 > 1,000,000,000, exactly 1/30 s after logical scheduled arrival. FPS: completed frames divided by (last c−t0), not 60 seconds or process wall time. Queue=s−r, service=c−s, local=c−a; mean local adds start lag (b−a), front-end (r−b), queue and service. Mean decomposition holds for all runs.

Each table value is an equal-run mean ± sample SD (n=5), unless explicitly identified otherwise. Run-level P95/P99 columns are means of five run-level percentiles, not pooled percentiles. Component percentiles are not added. Error bars in figures use run-level SD, not frame-level replication.



# 3. Concurrency Definition



C is the application cap on in-flight frame-level requests, not video count, batch size, CUDA core/thread count, auxiliary streams or kernel-level parallelism. A(t) counts started requests not yet completed. 0≤A≤C is the invariant of these static-C runs only. A future non-preemptive decrease may temporarily produce A>C_new while existing requests finish.

A=C is cap saturation. The separately reconstructed A=C AND Q>0 fraction identifies saturation coincident with canonical ready waiting; A=C with Q=0 is not queued blocking. Neither quantity is GPU utilization. GPU kernels, SM occupancy, bandwidth and resource contention were not directly profiled. Mean A also shares an interval-area identity with service duration, so their correlation alone is not independent causal evidence.



# 4. Overall Results



The Formal data support workload-dependent static responses and motivate controlled adaptation research. They do not demonstrate an online Dynamic-C gain. The strongest evidence is not a post-hoc minimum alone: C2→4 worsens DMR at K6 in every round and improves it at K7 in every round. Low-load DMR differences often reflect rare initial frames; high-load misses persist through the measurement window.

Important contrary evidence: service does not monotonically rise at every high-C step; K4 C4→5 DMR rises despite a lower mean service, and K7 C7→8 service and DMR both fall slightly. Historical K5/C8’s 56.333% DMR is not reproduced: Formal gives 19.698±4.161%. Primary claims use Formal only; see historical_secondary_comparison.md.



# 5. Workload-Dependent Behavior



## K1



low load; occupancy/throughput plateau across the tested grid; selected-condition misses are startup-localized.



Mean A is 0.339–0.350 over C1..8 and FPS stays about 30.006. The 0.133–0.300% DMR variation is small in absolute terms; all misses in selected C4 and C8 runs occur in the first logical second. Their local P95s remain around 23.2–23.5 ms. This does not support a sustained high-C service penalty at K1. No clear winner between C4 and C3.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.167 ± 0.039 | 0.148 ± 0.032 | 0.236 ± 0.004 | 11.434 ± 0.206 | 13.289 ± 0.296 | 23.392 ± 0.164 | 23.691 ± 0.149 | 30.006 ± 0.001 |
| 2 | 0.167 ± 0.000 | 0.187 ± 0.015 | 0.241 ± 0.006 | 11.352 ± 0.141 | 13.231 ± 0.191 | 23.376 ± 0.256 | 23.731 ± 0.222 | 30.006 ± 0.001 |
| 3 | 0.156 ± 0.025 | 0.119 ± 0.029 | 0.233 ± 0.010 | 11.569 ± 0.457 | 13.291 ± 0.130 | 23.412 ± 0.205 | 23.823 ± 0.477 | 30.006 ± 0.000 |
| 4 | 0.133 ± 0.030 | 0.126 ± 0.025 | 0.233 ± 0.006 | 11.384 ± 0.286 | 13.244 ± 0.263 | 23.368 ± 0.315 | 23.692 ± 0.204 | 30.006 ± 0.000 |
| 5 | 0.200 ± 0.050 | 0.133 ± 0.014 | 0.233 ± 0.004 | 11.381 ± 0.225 | 13.373 ± 0.234 | 23.495 ± 0.218 | 23.821 ± 0.202 | 30.006 ± 0.001 |
| 6 | 0.300 ± 0.030 | 0.134 ± 0.016 | 0.231 ± 0.006 | 11.674 ± 0.529 | 13.414 ± 0.328 | 23.484 ± 0.349 | 23.800 ± 0.472 | 30.006 ± 0.001 |
| 7 | 0.289 ± 0.025 | 0.115 ± 0.038 | 0.228 ± 0.014 | 11.305 ± 0.114 | 13.268 ± 0.254 | 23.312 ± 0.268 | 23.700 ± 0.242 | 30.006 ± 0.001 |
| 8 | 0.278 ± 0.039 | 0.122 ± 0.015 | 0.229 ± 0.004 | 11.407 ± 0.366 | 13.185 ± 0.350 | 23.185 ± 0.333 | 23.595 ± 0.256 | 30.006 ± 0.000 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.343 ± 0.006 | 34.301 ± 0.618 | 0.050 ± 0.019 | 1.400 ± 0.548 | 0.004 ± 0.001 | 0.044 ± 0.025 | 0.111 ± 0.039 | 0.000 ± 0.000 |
| 2 | 2–2 | 0.341 ± 0.004 | 0.056 ± 0.006 | 0.016 ± 0.010 | 1.000 ± 0.000 | 0.006 ± 0.000 | 0.011 ± 0.025 | 0.078 ± 0.030 | 0.000 ± 0.000 |
| 3 | 2–3 | 0.347 ± 0.014 | 0.020 ± 0.015 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.004 ± 0.001 | 0.000 ± 0.000 | 0.100 ± 0.025 | 0.000 ± 0.000 |
| 4 | 2–3 | 0.342 ± 0.009 | 0.000 ± 0.000 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.004 ± 0.001 | 0.000 ± 0.000 | 0.078 ± 0.030 | 0.000 ± 0.000 |
| 5 | 2–4 | 0.341 ± 0.007 | 0.000 ± 0.000 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.004 ± 0.000 | 0.000 ± 0.000 | 0.122 ± 0.025 | 0.000 ± 0.000 |
| 6 | 4–6 | 0.350 ± 0.016 | 0.001 ± 0.003 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.004 ± 0.000 | 0.011 ± 0.025 | 0.133 ± 0.030 | 0.000 ± 0.000 |
| 7 | 4–6 | 0.339 ± 0.003 | 0.000 ± 0.000 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.003 ± 0.001 | 0.011 ± 0.025 | 0.111 ± 0.000 | 0.000 ± 0.000 |
| 8 | 4–6 | 0.342 ± 0.011 | 0.000 ± 0.000 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.004 ± 0.000 | 0.011 ± 0.025 | 0.122 ± 0.025 | 0.000 ± 0.000 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 0.311 ± 0.035 | 9.684 ± 0.055 | 21.576 ± 0.172 |
| 2 | 0.303 ± 0.036 | 9.634 ± 0.035 | 21.476 ± 0.159 |
| 3 | 0.295 ± 0.058 | 9.666 ± 0.034 | 21.649 ± 0.434 |
| 4 | 0.313 ± 0.035 | 9.655 ± 0.079 | 21.479 ± 0.346 |
| 5 | 0.305 ± 0.068 | 9.634 ± 0.093 | 21.453 ± 0.146 |
| 6 | 0.393 ± 0.042 | 9.651 ± 0.031 | 21.852 ± 0.510 |
| 7 | 0.393 ± 0.038 | 9.658 ± 0.035 | 21.472 ± 0.151 |
| 8 | 0.380 ± 0.030 | 9.636 ± 0.025 | 21.545 ± 0.395 |



Descriptive mean-A diminishing-response band C1..8: 0.339–0.350. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



## K2



low/moderate load; C1→2 changes ready waiting/service, then mean A plateaus; selected-condition misses are startup-localized.



C1→2 removes 2.892 ms mean ready waiting but increases mean service by 5.025 ms (both 4/4 original pairs). Local mean increases 19.558→21.671 ms while mean run-level local P95 decreases 23.629→23.088 ms: mean and tail need not move together. C>=2 mean A is 0.660–0.677. C2/C3/C4 tie in mean DMR. Selected C2/C8 misses are all in the first second; high-C DMR is not evidence of sustained ready backlog.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.322 ± 0.050 | 3.073 ± 0.025 | 6.502 ± 0.050 | 5.975 ± 0.025 | 6.665 ± 0.093 | 23.629 ± 0.159 | 24.403 ± 0.272 | 60.009 ± 0.002 |
| 2 | 0.294 ± 0.037 | 0.181 ± 0.031 | 0.239 ± 0.003 | 11.000 ± 0.098 | 12.276 ± 0.191 | 23.088 ± 0.218 | 23.789 ± 0.221 | 60.009 ± 0.001 |
| 3 | 0.294 ± 0.037 | 0.148 ± 0.015 | 0.237 ± 0.002 | 11.282 ± 0.091 | 12.616 ± 0.216 | 23.063 ± 0.231 | 23.868 ± 0.367 | 60.009 ± 0.002 |
| 4 | 0.294 ± 0.064 | 0.150 ± 0.022 | 0.237 ± 0.005 | 11.068 ± 0.089 | 12.412 ± 0.258 | 23.065 ± 0.163 | 23.737 ± 0.252 | 60.009 ± 0.002 |
| 5 | 0.389 ± 0.020 | 0.140 ± 0.015 | 0.234 ± 0.002 | 11.288 ± 0.084 | 12.530 ± 0.205 | 23.055 ± 0.184 | 23.911 ± 0.466 | 60.009 ± 0.001 |
| 6 | 0.567 ± 0.058 | 0.127 ± 0.014 | 0.238 ± 0.004 | 11.195 ± 0.048 | 12.383 ± 0.193 | 23.109 ± 0.142 | 23.868 ± 0.263 | 60.010 ± 0.001 |
| 7 | 0.589 ± 0.060 | 0.113 ± 0.008 | 0.237 ± 0.004 | 11.088 ± 0.145 | 12.167 ± 0.148 | 22.850 ± 0.184 | 23.670 ± 0.196 | 60.010 ± 0.001 |
| 8 | 0.572 ± 0.064 | 0.102 ± 0.012 | 0.226 ± 0.003 | 11.118 ± 0.069 | 12.258 ± 0.249 | 22.898 ± 0.252 | 23.809 ± 0.572 | 60.010 ± 0.002 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.359 ± 0.002 | 35.850 ± 0.153 | 17.290 ± 0.138 | 6.600 ± 0.894 | 0.185 ± 0.002 | 0.156 ± 0.046 | 0.178 ± 0.025 | 0.000 ± 0.000 |
| 2 | 2–2 | 0.660 ± 0.006 | 31.108 ± 0.782 | 0.096 ± 0.018 | 5.000 ± 0.707 | 0.011 ± 0.002 | 0.078 ± 0.030 | 0.167 ± 0.000 | 0.000 ± 0.000 |
| 3 | 3–3 | 0.677 ± 0.005 | 0.082 ± 0.016 | 0.070 ± 0.014 | 3.800 ± 0.447 | 0.009 ± 0.001 | 0.078 ± 0.050 | 0.156 ± 0.025 | 0.000 ± 0.000 |
| 4 | 4–4 | 0.664 ± 0.005 | 0.054 ± 0.012 | 0.041 ± 0.013 | 2.800 ± 0.447 | 0.009 ± 0.001 | 0.022 ± 0.030 | 0.133 ± 0.050 | 0.000 ± 0.000 |
| 5 | 5–5 | 0.677 ± 0.005 | 0.073 ± 0.005 | 0.068 ± 0.004 | 2.600 ± 0.894 | 0.008 ± 0.001 | 0.078 ± 0.030 | 0.233 ± 0.025 | 0.000 ± 0.000 |
| 6 | 6–6 | 0.672 ± 0.003 | 0.060 ± 0.019 | 0.046 ± 0.023 | 2.400 ± 0.894 | 0.008 ± 0.001 | 0.033 ± 0.030 | 0.222 ± 0.039 | 0.000 ± 0.000 |
| 7 | 7–7 | 0.665 ± 0.009 | 0.026 ± 0.010 | 0.000 ± 0.000 | 2.000 ± 0.000 | 0.007 ± 0.000 | 0.033 ± 0.030 | 0.233 ± 0.061 | 0.000 ± 0.000 |
| 8 | 7–8 | 0.667 ± 0.004 | 0.023 ± 0.031 | 0.019 ± 0.026 | 2.200 ± 0.447 | 0.006 ± 0.001 | 0.033 ± 0.030 | 0.244 ± 0.084 | 0.000 ± 0.000 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 0.490 ± 0.062 | 10.021 ± 0.140 | 19.558 ± 0.079 |
| 2 | 0.489 ± 0.050 | 10.002 ± 0.133 | 21.671 ± 0.179 |
| 3 | 0.515 ± 0.057 | 9.885 ± 0.029 | 21.831 ± 0.097 |
| 4 | 0.488 ± 0.035 | 9.957 ± 0.131 | 21.664 ± 0.116 |
| 5 | 0.569 ± 0.033 | 9.907 ± 0.092 | 21.904 ± 0.139 |
| 6 | 0.973 ± 0.142 | 10.007 ± 0.108 | 22.302 ± 0.258 |
| 7 | 1.033 ± 0.128 | 9.927 ± 0.089 | 22.160 ± 0.219 |
| 8 | 0.973 ± 0.107 | 9.921 ± 0.047 | 22.114 ± 0.071 |



Descriptive mean-A diminishing-response band C2..8: 0.660–0.677. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



## K3



moderate load; queue response through C3; low DMR with high-C tail changes, no sustained ready backlog during this window.



C1→3 reduces queue 4.319→0.255 ms and increases service 4.746→11.555 ms. Mean A reaches about 1.04 at C3 and stays in 1.040–1.090 thereafter. C2 has the lowest mean DMR (0.463%) but its 0.052 pp gap to C4 is smaller than run variability. High C does not uniformly improve deadlines or tails.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.622 ± 0.050 | 4.319 ± 0.662 | 8.764 ± 0.508 | 4.746 ± 0.010 | 5.024 ± 0.015 | 25.017 ± 0.543 | 25.929 ± 0.833 | 90.006 ± 0.005 |
| 2 | 0.463 ± 0.086 | 2.591 ± 0.072 | 7.852 ± 0.104 | 7.140 ± 0.021 | 8.897 ± 0.049 | 23.629 ± 0.075 | 24.326 ± 0.247 | 90.013 ± 0.003 |
| 3 | 0.530 ± 0.053 | 0.255 ± 0.058 | 0.230 ± 0.004 | 11.555 ± 0.204 | 12.831 ± 0.184 | 23.674 ± 0.131 | 24.745 ± 0.218 | 90.009 ± 0.003 |
| 4 | 0.515 ± 0.044 | 0.231 ± 0.016 | 0.237 ± 0.002 | 11.969 ± 0.032 | 13.334 ± 0.047 | 23.851 ± 0.065 | 24.970 ± 0.416 | 90.013 ± 0.002 |
| 5 | 0.563 ± 0.092 | 0.185 ± 0.014 | 0.248 ± 0.004 | 11.893 ± 0.179 | 13.271 ± 0.081 | 24.004 ± 0.212 | 25.140 ± 0.714 | 90.008 ± 0.004 |
| 6 | 0.878 ± 0.043 | 0.143 ± 0.005 | 0.232 ± 0.004 | 11.801 ± 0.084 | 13.064 ± 0.101 | 23.898 ± 0.137 | 25.404 ± 0.330 | 90.009 ± 0.003 |
| 7 | 0.926 ± 0.045 | 0.140 ± 0.012 | 0.261 ± 0.010 | 12.116 ± 0.061 | 13.404 ± 0.045 | 23.993 ± 0.129 | 25.685 ± 0.411 | 90.011 ± 0.003 |
| 8 | 0.930 ± 0.056 | 0.142 ± 0.019 | 0.269 ± 0.016 | 12.049 ± 0.118 | 13.333 ± 0.051 | 23.932 ± 0.074 | 26.167 ± 0.886 | 90.011 ± 0.002 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.427 ± 0.001 | 42.711 ± 0.087 | 25.641 ± 2.003 | 15.800 ± 2.775 | 0.390 ± 0.060 | 0.344 ± 0.072 | 0.400 ± 0.046 | 0.000 ± 0.001 |
| 2 | 2–2 | 0.643 ± 0.002 | 24.856 ± 0.074 | 21.122 ± 0.291 | 11.600 ± 2.074 | 0.234 ± 0.007 | 0.244 ± 0.063 | 0.267 ± 0.046 | 0.000 ± 0.000 |
| 3 | 3–3 | 1.040 ± 0.018 | 29.464 ± 1.143 | 0.236 ± 0.039 | 10.400 ± 1.517 | 0.023 ± 0.005 | 0.256 ± 0.063 | 0.311 ± 0.050 | 0.000 ± 0.000 |
| 4 | 4–4 | 1.077 ± 0.003 | 0.216 ± 0.014 | 0.197 ± 0.018 | 9.800 ± 0.837 | 0.021 ± 0.001 | 0.222 ± 0.039 | 0.289 ± 0.046 | 0.000 ± 0.000 |
| 5 | 5–5 | 1.070 ± 0.016 | 0.164 ± 0.021 | 0.139 ± 0.019 | 8.400 ± 0.548 | 0.017 ± 0.001 | 0.144 ± 0.030 | 0.289 ± 0.025 | 0.000 ± 0.000 |
| 6 | 6–6 | 1.062 ± 0.008 | 0.123 ± 0.012 | 0.104 ± 0.018 | 7.400 ± 1.342 | 0.013 ± 0.000 | 0.122 ± 0.025 | 0.433 ± 0.025 | 0.000 ± 0.000 |
| 7 | 7–7 | 1.090 ± 0.006 | 0.094 ± 0.014 | 0.074 ± 0.018 | 5.400 ± 1.342 | 0.013 ± 0.001 | 0.089 ± 0.030 | 0.411 ± 0.030 | 0.000 ± 0.000 |
| 8 | 8–8 | 1.084 ± 0.011 | 0.086 ± 0.029 | 0.069 ± 0.020 | 5.200 ± 1.789 | 0.013 ± 0.002 | 0.067 ± 0.025 | 0.456 ± 0.061 | 0.000 ± 0.000 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 0.766 ± 0.094 | 10.521 ± 0.683 | 20.352 ± 0.161 |
| 2 | 0.654 ± 0.064 | 10.165 ± 0.039 | 20.551 ± 0.120 |
| 3 | 0.738 ± 0.035 | 10.170 ± 0.068 | 22.718 ± 0.209 |
| 4 | 0.743 ± 0.057 | 10.164 ± 0.043 | 23.107 ± 0.071 |
| 5 | 0.858 ± 0.180 | 10.191 ± 0.102 | 23.127 ± 0.123 |
| 6 | 1.626 ± 0.119 | 10.245 ± 0.070 | 23.815 ± 0.184 |
| 7 | 1.742 ± 0.131 | 10.206 ± 0.069 | 24.203 ± 0.165 |
| 8 | 1.726 ± 0.138 | 10.238 ± 0.053 | 24.156 ± 0.191 |



Descriptive mean-A diminishing-response band C3..8: 1.040–1.090. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



## K4



moderate load with tail-sensitive boundary; C>=5 affects rare long tails, most sampled-condition misses occur in first second.



C1→4 reduces queue 6.885→0.287 ms and increases service 4.729→15.680 ms. At C4→5 queue still decreases in all five rounds and DMR rises in all five, but mean service actually falls 0.661 ms with mixed directions. Start lag rises 0.708→2.217 ms and front-end 10.518→11.361 ms. Mean run-level local P99 jumps 30.170→86.598 ms; 94.3% of C5 misses occur in the first second. This is a counterexample to attributing every DMR rise to service inflation.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.875 ± 0.119 | 6.885 ± 0.134 | 13.036 ± 0.163 | 4.729 ± 0.017 | 5.040 ± 0.027 | 29.434 ± 0.126 | 31.165 ± 0.908 | 119.999 ± 0.003 |
| 2 | 0.667 ± 0.084 | 3.751 ± 0.570 | 8.265 ± 0.307 | 8.034 ± 0.140 | 9.106 ± 0.031 | 27.969 ± 0.673 | 29.102 ± 0.956 | 120.003 ± 0.007 |
| 3 | 0.667 ± 0.104 | 2.819 ± 0.075 | 11.242 ± 0.138 | 10.520 ± 0.018 | 13.436 ± 0.025 | 28.026 ± 0.053 | 29.190 ± 0.194 | 120.010 ± 0.005 |
| 4 | 0.561 ± 0.105 | 0.287 ± 0.052 | 0.255 ± 0.005 | 15.680 ± 0.174 | 17.639 ± 0.148 | 29.042 ± 0.171 | 30.170 ± 0.044 | 120.002 ± 0.006 |
| 5 | 1.264 ± 0.185 | 0.251 ± 0.038 | 0.299 ± 0.022 | 15.019 ± 1.760 | 17.903 ± 0.598 | 30.187 ± 1.011 | 86.598 ± 31.348 | 120.012 ± 0.001 |
| 6 | 1.303 ± 0.248 | 0.271 ± 0.034 | 0.499 ± 0.047 | 15.809 ± 1.149 | 18.187 ± 0.329 | 29.958 ± 0.683 | 108.732 ± 50.551 | 120.008 ± 0.006 |
| 7 | 1.289 ± 0.058 | 0.232 ± 0.022 | 0.557 ± 0.031 | 15.628 ± 0.736 | 18.109 ± 0.138 | 29.883 ± 0.810 | 116.895 ± 14.260 | 120.007 ± 0.003 |
| 8 | 1.342 ± 0.130 | 0.200 ± 0.029 | 0.339 ± 0.043 | 15.899 ± 0.097 | 17.920 ± 0.054 | 29.310 ± 0.080 | 128.560 ± 37.470 | 120.003 ± 0.005 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.568 ± 0.002 | 56.750 ± 0.203 | 41.113 ± 0.369 | 23.600 ± 4.037 | 0.828 ± 0.016 | 0.667 ± 0.088 | 0.711 ± 0.127 | 0.001 ± 0.001 |
| 2 | 2–2 | 0.964 ± 0.017 | 45.016 ± 1.696 | 23.591 ± 1.355 | 19.000 ± 2.236 | 0.451 ± 0.069 | 0.433 ± 0.046 | 0.467 ± 0.050 | 0.001 ± 0.002 |
| 3 | 3–3 | 1.262 ± 0.002 | 34.278 ± 0.164 | 29.558 ± 0.318 | 16.600 ± 1.949 | 0.339 ± 0.009 | 0.433 ± 0.061 | 0.444 ± 0.068 | 0.000 ± 0.000 |
| 4 | 4–4 | 1.882 ± 0.021 | 39.098 ± 0.880 | 0.294 ± 0.056 | 13.600 ± 1.517 | 0.035 ± 0.006 | 0.322 ± 0.046 | 0.389 ± 0.056 | 0.001 ± 0.001 |
| 5 | 5–5 | 1.802 ± 0.211 | 0.278 ± 0.045 | 0.250 ± 0.049 | 11.600 ± 1.517 | 0.030 ± 0.005 | 0.267 ± 0.072 | 0.833 ± 0.317 | 0.000 ± 0.000 |
| 6 | 6–6 | 1.897 ± 0.138 | 0.274 ± 0.039 | 0.249 ± 0.045 | 12.800 ± 1.095 | 0.033 ± 0.004 | 0.289 ± 0.046 | 0.811 ± 0.210 | 0.000 ± 0.000 |
| 7 | 7–7 | 1.875 ± 0.088 | 0.227 ± 0.032 | 0.202 ± 0.025 | 11.200 ± 1.483 | 0.028 ± 0.003 | 0.244 ± 0.030 | 0.778 ± 0.056 | 0.000 ± 0.000 |
| 8 | 8–8 | 1.908 ± 0.012 | 0.201 ± 0.025 | 0.178 ± 0.032 | 12.000 ± 1.732 | 0.024 ± 0.003 | 0.200 ± 0.084 | 0.778 ± 0.079 | 0.000 ± 0.000 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 0.804 ± 0.108 | 10.479 ± 0.103 | 22.897 ± 0.235 |
| 2 | 0.823 ± 0.102 | 10.789 ± 0.745 | 23.397 ± 0.230 |
| 3 | 0.777 ± 0.075 | 10.466 ± 0.041 | 24.582 ± 0.113 |
| 4 | 0.708 ± 0.122 | 10.518 ± 0.049 | 27.194 ± 0.099 |
| 5 | 2.217 ± 0.310 | 11.361 ± 0.903 | 28.848 ± 1.036 |
| 6 | 2.432 ± 0.666 | 11.082 ± 0.662 | 29.594 ± 0.298 |
| 7 | 2.443 ± 0.156 | 11.094 ± 0.561 | 29.397 ± 0.172 |
| 8 | 2.614 ± 0.485 | 10.808 ± 0.063 | 29.521 ± 0.537 |



Descriptive mean-A diminishing-response band C4..8: 1.802–1.908. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



## K5



deadline-sensitive boundary; C choices span ~2–20% DMR despite near-offered completion rate.



A deadline-sensitive regime appears despite approximately 150 completed FPS throughout. C1→2 DMR drops 13.189→2.147%; C2→5 queue falls 6.317→0.482 ms while service rises 7.708→19.694 ms and DMR rises to 13.773%. At C5→6 service adds 0.295 ms in 5/5 rounds after most queue relief. C5..8 mean A occupies a narrow 2.944–2.998 band, but start lag and DMR have not equivalently plateaued. C2 is mean-minimizing, yet C3 variability makes a precise single-winner claim cautious.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 13.189 ± 3.286 | 10.024 ± 0.342 | 17.023 ± 0.205 | 4.782 ± 0.059 | 5.291 ± 0.226 | 34.911 ± 0.414 | 132.621 ± 20.751 | 149.984 ± 0.006 |
| 2 | 2.147 ± 1.676 | 6.317 ± 0.355 | 14.809 ± 0.742 | 7.708 ± 0.024 | 9.074 ± 0.040 | 32.358 ± 0.581 | 58.049 ± 17.709 | 149.992 ± 0.006 |
| 3 | 3.696 ± 3.773 | 4.523 ± 0.499 | 11.785 ± 0.400 | 10.929 ± 0.052 | 13.893 ± 0.056 | 33.406 ± 1.913 | 36.901 ± 1.730 | 149.994 ± 0.008 |
| 4 | 6.504 ± 3.867 | 2.764 ± 0.384 | 13.739 ± 0.994 | 13.969 ± 0.239 | 18.119 ± 0.276 | 34.776 ± 2.445 | 39.561 ± 2.834 | 149.997 ± 0.007 |
| 5 | 13.773 ± 2.558 | 0.482 ± 0.112 | 0.684 ± 0.042 | 19.694 ± 0.134 | 22.840 ± 0.314 | 35.707 ± 0.275 | 194.963 ± 40.142 | 149.995 ± 0.005 |
| 6 | 17.769 ± 2.221 | 0.388 ± 0.079 | 0.772 ± 0.032 | 19.989 ± 0.078 | 23.471 ± 0.226 | 36.214 ± 0.241 | 245.459 ± 17.023 | 149.995 ± 0.006 |
| 7 | 17.204 ± 2.945 | 0.305 ± 0.046 | 0.781 ± 0.014 | 19.932 ± 0.151 | 23.358 ± 0.382 | 36.187 ± 0.306 | 243.668 ± 11.594 | 149.989 ± 0.009 |
| 8 | 19.698 ± 4.161 | 0.307 ± 0.052 | 0.797 ± 0.010 | 19.630 ± 0.860 | 23.709 ± 0.418 | 36.766 ± 1.122 | 258.445 ± 26.358 | 149.991 ± 0.008 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.717 ± 0.009 | 71.724 ± 0.882 | 55.075 ± 0.445 | 36.200 ± 3.194 | 1.508 ± 0.052 | 1.711 ± 0.133 | 58.156 ± 16.563 | 0.006 ± 0.002 |
| 2 | 2–2 | 1.156 ± 0.004 | 50.779 ± 0.153 | 44.819 ± 1.415 | 29.600 ± 2.608 | 0.950 ± 0.053 | 0.833 ± 0.142 | 6.000 ± 8.049 | 0.003 ± 0.003 |
| 3 | 3–3 | 1.639 ± 0.008 | 38.620 ± 0.611 | 32.406 ± 2.125 | 25.000 ± 4.000 | 0.680 ± 0.075 | 0.656 ± 0.072 | 9.222 ± 11.883 | 0.003 ± 0.002 |
| 4 | 4–4 | 2.095 ± 0.036 | 41.425 ± 3.080 | 32.208 ± 6.031 | 23.600 ± 2.074 | 0.416 ± 0.058 | 0.822 ± 0.339 | 25.667 ± 15.009 | 0.002 ± 0.002 |
| 5 | 5–5 | 2.954 ± 0.020 | 46.986 ± 0.672 | 0.471 ± 0.053 | 20.400 ± 3.209 | 0.073 ± 0.017 | 0.511 ± 0.072 | 25.644 ± 4.805 | 0.002 ± 0.002 |
| 6 | 6–6 | 2.998 ± 0.012 | 0.439 ± 0.125 | 0.372 ± 0.109 | 17.200 ± 2.683 | 0.059 ± 0.012 | 0.411 ± 0.093 | 31.000 ± 3.018 | 0.002 ± 0.002 |
| 7 | 7–7 | 2.990 ± 0.023 | 0.299 ± 0.069 | 0.264 ± 0.074 | 15.200 ± 1.095 | 0.046 ± 0.007 | 0.344 ± 0.091 | 30.167 ± 5.142 | 0.004 ± 0.004 |
| 8 | 8–8 | 2.944 ± 0.129 | 0.307 ± 0.072 | 0.273 ± 0.078 | 13.200 ± 1.924 | 0.046 ± 0.008 | 0.333 ± 0.111 | 32.989 ± 5.996 | 0.004 ± 0.003 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 0.943 ± 0.091 | 10.827 ± 0.064 | 26.576 ± 0.349 |
| 2 | 0.933 ± 0.080 | 11.204 ± 0.601 | 26.162 ± 0.444 |
| 3 | 0.839 ± 0.036 | 11.358 ± 0.831 | 27.648 ± 0.396 |
| 4 | 0.875 ± 0.092 | 11.962 ± 0.968 | 29.570 ± 0.628 |
| 5 | 3.109 ± 0.703 | 11.485 ± 0.092 | 34.770 ± 0.691 |
| 6 | 4.129 ± 0.342 | 11.600 ± 0.076 | 36.106 ± 0.390 |
| 7 | 4.145 ± 0.255 | 11.641 ± 0.069 | 36.023 ± 0.388 |
| 8 | 4.399 ± 0.545 | 11.924 ± 0.596 | 36.260 ± 0.521 |



Descriptive mean-A diminishing-response band C5..8: 2.944–2.998. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



## K6



deadline overload; C1 has persistent ready backlog and large run variability; higher C restores near-offered rate but does not ensure deadlines.



All configurations have substantial deadline misses (32.296–89.550%). C1 has mean queue 82.236±62.341 ms and waiting carryover 95.244%; its run DMR spans 36.139–100%. C2→6 reduces queue 9.428→0.379 ms, increases service 8.543→23.942 ms and DMR 32.296→86.831%. Start lag also increases 0.946→8.695 ms. C6..8 mean A is 4.309–4.372; C6→7 service still grows consistently, but C7→8 does not show consistent mean-service inflation. C2 and C4 are distinct low-C basins, with C2 lower in all five DMR pairs.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 63.202 ± 27.132 | 82.236 ± 62.341 | 173.769 ± 50.429 | 5.288 ± 0.114 | 7.944 ± 1.025 | 194.385 ± 49.800 | 259.132 ± 10.428 | 179.904 ± 0.137 |
| 2 | 32.296 ± 0.359 | 9.428 ± 0.560 | 16.200 ± 0.095 | 8.543 ± 0.025 | 9.799 ± 0.023 | 37.978 ± 0.113 | 152.905 ± 24.526 | 179.966 ± 0.012 |
| 3 | 37.793 ± 1.034 | 6.455 ± 0.294 | 12.447 ± 0.105 | 12.106 ± 0.081 | 14.236 ± 0.055 | 38.289 ± 0.123 | 118.139 ± 30.140 | 179.983 ± 0.013 |
| 4 | 34.098 ± 1.071 | 5.213 ± 0.687 | 15.394 ± 0.394 | 14.336 ± 0.142 | 18.500 ± 0.342 | 39.306 ± 1.209 | 110.926 ± 22.095 | 179.978 ± 0.013 |
| 5 | 43.902 ± 1.390 | 2.893 ± 0.114 | 17.068 ± 0.183 | 18.296 ± 0.052 | 24.004 ± 0.122 | 40.456 ± 0.235 | 347.860 ± 28.230 | 179.981 ± 0.010 |
| 6 | 86.831 ± 1.942 | 0.379 ± 0.059 | 0.931 ± 0.044 | 23.942 ± 0.230 | 27.141 ± 0.137 | 40.623 ± 0.368 | 391.415 ± 27.153 | 179.969 ± 0.010 |
| 7 | 89.550 ± 0.940 | 0.464 ± 0.097 | 0.920 ± 0.038 | 24.294 ± 0.132 | 27.383 ± 0.105 | 40.935 ± 0.242 | 404.423 ± 10.396 | 179.978 ± 0.006 |
| 8 | 89.026 ± 0.773 | 0.362 ± 0.073 | 0.897 ± 0.030 | 24.292 ± 0.133 | 27.352 ± 0.073 | 40.798 ± 0.280 | 403.071 ± 24.408 | 179.974 ± 0.006 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.951 ± 0.020 | 95.133 ± 1.990 | 83.797 ± 10.346 | 49.600 ± 4.506 | 14.841 ± 11.243 | 95.244 ± 3.957 | 98.022 ± 0.845 | 0.032 ± 0.046 |
| 2 | 2–2 | 1.537 ± 0.005 | 73.315 ± 0.465 | 51.067 ± 0.136 | 39.400 ± 6.504 | 1.702 ± 0.102 | 2.167 ± 0.212 | 99.344 ± 0.445 | 0.011 ± 0.004 |
| 3 | 3–3 | 2.179 ± 0.014 | 63.378 ± 0.870 | 37.223 ± 0.315 | 33.600 ± 6.107 | 1.165 ± 0.054 | 1.433 ± 0.224 | 99.689 ± 0.063 | 0.006 ± 0.004 |
| 4 | 4–4 | 2.580 ± 0.026 | 46.584 ± 0.950 | 42.260 ± 1.869 | 27.400 ± 10.738 | 0.941 ± 0.124 | 1.478 ± 0.692 | 99.700 ± 0.063 | 0.007 ± 0.004 |
| 5 | 5–5 | 3.293 ± 0.009 | 53.188 ± 0.358 | 43.702 ± 0.497 | 18.000 ± 3.082 | 0.524 ± 0.021 | 7.289 ± 0.698 | 99.244 ± 0.160 | 0.006 ± 0.003 |
| 6 | 6–6 | 4.309 ± 0.041 | 52.985 ± 1.886 | 0.535 ± 0.100 | 15.200 ± 2.168 | 0.069 ± 0.011 | 0.678 ± 0.256 | 99.222 ± 0.056 | 0.010 ± 0.003 |
| 7 | 7–7 | 4.372 ± 0.024 | 0.686 ± 0.117 | 0.536 ± 0.081 | 20.400 ± 4.980 | 0.084 ± 0.018 | 0.711 ± 0.082 | 99.200 ± 0.084 | 0.007 ± 0.002 |
| 8 | 8–8 | 4.372 ± 0.024 | 0.441 ± 0.084 | 0.376 ± 0.074 | 17.000 ± 3.391 | 0.066 ± 0.013 | 0.567 ± 0.173 | 99.122 ± 0.133 | 0.009 ± 0.002 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 1.072 ± 0.062 | 12.446 ± 0.990 | 101.041 ± 63.422 |
| 2 | 0.946 ± 0.101 | 11.643 ± 0.160 | 30.560 ± 0.686 |
| 3 | 0.954 ± 0.185 | 11.755 ± 0.086 | 31.270 ± 0.440 |
| 4 | 1.188 ± 0.287 | 12.269 ± 0.786 | 33.005 ± 0.673 |
| 5 | 7.217 ± 0.749 | 12.561 ± 0.116 | 40.967 ± 0.975 |
| 6 | 8.695 ± 0.935 | 12.528 ± 0.117 | 45.544 ± 1.193 |
| 7 | 9.159 ± 0.424 | 12.604 ± 0.084 | 46.521 ± 0.502 |
| 8 | 9.114 ± 0.880 | 12.534 ± 0.127 | 46.302 ± 0.926 |



Descriptive mean-A diminishing-response band C6..8: 4.309–4.372. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



## K7



severe deadline overload; C1 also exhibits throughput/backlog overload; C>=2 nearly tracks offered rate yet DMR remains high.



C1 is throughput/backlog overload: 184.053 completed FPS against 210 offered, mean queue 5188.484 ms and mean drain 8.459 s. C2..8 nearly recover offered throughput, but even C4 mean DMR is 47.390%. C4→7 reduces queue 11.356→0.780 ms while service grows 15.237→28.019 ms and DMR 47.390→97.262%. Start lag simultaneously rises 2.245→27.266 ms. C7→8 mean A declines 5.883→5.823 and service 28.019→27.735 ms; DMR improves modestly in every round, while local tail variability remains substantial. C8 is an endpoint, not a measured hardware limit.



| C | DMR % | Queue mean ms | Queue run-P95 mean ms | Service mean ms | Service run-P95 mean ms | Local run-P95 mean ms | Local run-P99 mean ms | Completed FPS |
|---|---|---|---|---|---|---|---|---|
| 1 | 100.000 ± 0.000 | 5188.484 ± 188.740 | 8569.906 ± 256.705 | 5.372 ± 0.021 | 8.536 ± 0.097 | 8588.296 ± 256.737 | 8680.472 ± 256.825 | 184.053 ± 0.696 |
| 2 | 82.779 ± 15.272 | 115.256 ± 32.369 | 230.566 ± 8.594 | 9.133 ± 0.262 | 12.596 ± 0.787 | 256.713 ± 6.776 | 278.644 ± 10.181 | 209.853 ± 0.177 |
| 3 | 58.875 ± 5.491 | 21.407 ± 12.334 | 90.396 ± 38.478 | 12.325 ± 0.267 | 15.918 ± 0.880 | 123.412 ± 39.487 | 211.587 ± 23.020 | 209.944 ± 0.025 |
| 4 | 47.390 ± 0.841 | 11.356 ± 2.393 | 37.261 ± 23.140 | 15.237 ± 0.088 | 19.037 ± 0.125 | 70.901 ± 26.692 | 258.157 ± 48.821 | 209.967 ± 0.016 |
| 5 | 68.668 ± 2.037 | 5.647 ± 0.226 | 18.887 ± 0.279 | 18.312 ± 0.147 | 25.071 ± 0.217 | 194.777 ± 64.416 | 440.880 ± 55.083 | 209.968 ± 0.006 |
| 6 | 93.133 ± 0.997 | 3.099 ± 0.295 | 20.792 ± 0.726 | 22.664 ± 0.115 | 28.404 ± 0.175 | 337.501 ± 18.992 | 563.214 ± 17.570 | 209.961 ± 0.014 |
| 7 | 97.262 ± 0.251 | 0.780 ± 0.128 | 1.299 ± 0.070 | 28.019 ± 0.082 | 32.709 ± 0.088 | 329.273 ± 32.278 | 546.894 ± 32.451 | 209.958 ± 0.013 |
| 8 | 96.611 ± 0.586 | 0.487 ± 0.144 | 1.175 ± 0.065 | 27.735 ± 0.291 | 32.597 ± 0.233 | 352.354 ± 36.738 | 571.828 ± 30.678 | 209.949 ± 0.016 |



| C | Observed max A range | Mean A | A=C time % | A=C & Q>0 time % | Peak Q | Time-weighted Q | Waiting carryover % | Active carryover % | Drain s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1–1 | 0.991 ± 0.001 | 99.142 ± 0.050 | 99.127 ± 0.049 | 1826.800 ± 53.681 | 966.754 ± 32.253 | 99.711 ± 0.046 | 99.211 ± 0.173 | 8.459 ± 0.259 |
| 2 | 2–2 | 1.917 ± 0.054 | 92.822 ± 4.651 | 90.872 ± 6.346 | 57.800 ± 2.387 | 24.265 ± 6.816 | 98.533 ± 1.038 | 99.756 ± 0.030 | 0.042 ± 0.051 |
| 3 | 3–3 | 2.588 ± 0.056 | 78.161 ± 2.648 | 70.257 ± 3.597 | 48.000 ± 6.083 | 4.508 ± 2.597 | 71.267 ± 7.757 | 99.756 ± 0.063 | 0.016 ± 0.007 |
| 4 | 4–4 | 3.199 ± 0.018 | 53.923 ± 0.655 | 47.457 ± 0.802 | 44.600 ± 11.459 | 2.394 ± 0.506 | 6.822 ± 1.241 | 99.644 ± 0.084 | 0.010 ± 0.005 |
| 5 | 5–5 | 3.845 ± 0.031 | 58.328 ± 0.785 | 51.054 ± 0.832 | 34.200 ± 5.805 | 1.194 ± 0.049 | 32.578 ± 3.926 | 99.311 ± 0.108 | 0.009 ± 0.002 |
| 6 | 6–6 | 4.759 ± 0.024 | 62.678 ± 1.133 | 49.827 ± 2.870 | 24.800 ± 10.895 | 0.657 ± 0.063 | 54.933 ± 5.006 | 99.111 ± 0.056 | 0.011 ± 0.004 |
| 7 | 7–7 | 5.883 ± 0.017 | 59.987 ± 0.819 | 1.580 ± 0.356 | 27.800 ± 4.919 | 0.165 ± 0.027 | 1.622 ± 0.376 | 99.122 ± 0.082 | 0.012 ± 0.004 |
| 8 | 8–8 | 5.823 ± 0.061 | 1.290 ± 0.504 | 0.836 ± 0.355 | 17.200 ± 6.017 | 0.103 ± 0.031 | 1.289 ± 0.460 | 99.089 ± 0.063 | 0.015 ± 0.005 |



| C | Start-lag mean ms | Front-end mean ms | Local mean ms |
|---|---|---|---|
| 1 | 1.129 ± 0.184 | 13.505 ± 0.105 | 5208.491 ± 188.753 |
| 2 | 1.203 ± 0.145 | 13.710 ± 0.525 | 139.302 ± 33.201 |
| 3 | 1.118 ± 0.095 | 13.490 ± 0.834 | 48.341 ± 12.897 |
| 4 | 2.245 ± 0.602 | 13.121 ± 0.142 | 41.959 ± 2.667 |
| 5 | 16.189 ± 3.607 | 14.364 ± 0.220 | 54.511 ± 3.974 |
| 6 | 28.065 ± 1.326 | 14.829 ± 0.522 | 68.656 ± 1.491 |
| 7 | 27.266 ± 3.378 | 14.710 ± 0.141 | 70.776 ± 3.621 |
| 8 | 29.991 ± 3.428 | 14.896 ± 0.261 | 73.108 ± 3.654 |



Descriptive mean-A diminishing-response band C7..8: 5.823–5.883. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.



# 6. Queue and Service Behavior



Below, H1 asks whether a queue-reduction interval exists, H2 whether service inflation co-occurs locally, and H3 whether further service growth remains after queue relief diminishes. These local tests are separate from the research-level H1–H7 in section 14. “CONFIRMED” is descriptive repeat evidence, not a statistical significance statement.



| K | Local H1 | Local H2 | Local H3 | Early queue Δ / paired direction | Early service Δ / paired direction |
|---|---|---|---|---|---|
| 1 | CONFIRMED | NOT_CONFIRMED | NOT_CONFIRMED | 2->3: -0.0676 (5/5 down, 0/5 up) | +0.2174 (2/5 down, 3/5 up) |
| 2 | CONFIRMED | CONFIRMED | CONFIRMED | 1->2: -2.8916 (4/4 down, 0/4 up) | +5.0246 (0/4 down, 4/4 up) |
| 3 | CONFIRMED | CONFIRMED | CONFIRMED | 1->2: -1.7280 (5/5 down, 0/5 up) | +2.3947 (0/5 down, 5/5 up) |
| 4 | CONFIRMED | CONFIRMED | NOT_CONFIRMED | 3->4: -2.5321 (5/5 down, 0/5 up) | +5.1604 (0/5 down, 5/5 up) |
| 5 | CONFIRMED | CONFIRMED | CONFIRMED | 1->2: -3.7072 (5/5 down, 0/5 up) | +2.9257 (0/5 down, 5/5 up) |
| 6 | CONFIRMED | CONFIRMED | CONFIRMED | 1->2: -72.8080 (5/5 down, 0/5 up) | +3.2548 (0/5 down, 5/5 up) |
| 7 | CONFIRMED | CONFIRMED | PARTIALLY_CONFIRMED | 1->2: -5073.2284 (5/5 down, 0/5 up) | +3.7609 (0/5 down, 5/5 up) |



K1’s repeat-consistent C2→3 queue decrease is only 0.068 ms and does not establish a sustained service trade-off. Late examples: K3 C3→4 queue −0.024 ms versus service +0.414 ms (5/5 service increases); K5 C5→6 queue −0.094 ms versus service +0.295 ms (5/5 service increases). K6 C6→7 has no further queue reduction (+0.084 ms) yet service +0.352 ms in 5/5. K4 high-C service directions are mixed. K7 C6→7 still increases service strongly, but after C7 the C8 step reduces mean service in 4/5; local H3 is only partially confirmed.



# 7. Deadline Performance



| K | Mean-curve shape | Qualification |
|---|---|---|
| 1 | irregular | Very low absolute DMR; minimum C4 not separated from C3; selected C4/C8 misses entirely in first second. Not a sustained U-shaped service regime. |
| 2 | irregular | C2/C3/C4 mean tie; C1-to-C2 DMR direction splits 2/4 each way, followed by repeat-consistent high-C tail increase. Low-C minimum is unresolved. |
| 3 | interior minimum / U-shaped | Broad interior low-C basin at C2 with local reversals; C1→2 DMR falls 5/5 and C2→8 rises in all original pairs. C2 versus C4 not a clear winner. |
| 4 | interior minimum / U-shaped | Shallow interior mean minimum C4, then a high-C tail step; C4→5 DMR rises 5/5 although mean service falls. Not a strictly monotone arm. |
| 5 | interior minimum / U-shaped | C1→2 DMR falls 5/5, C2→3 rises 5/5; later small reversals and large run variability. C2’s gap to C3 is smaller than C3 run SD. |
| 6 | irregular | Two low-C troughs: C2→3 rises 5/5, C3→4 falls 5/5, then large high-C penalty. Interior global mean minimum C2; not a simple U. |
| 7 | interior minimum / U-shaped | DMR falls through C4 and rises strongly C4→7; C7→8 falls modestly in 5/5. Interior minimum is robust in these repeats, arms are not strictly monotone. |



Shapes are descriptive, not an automatic threshold-based plateau/equivalence test. Several curves have an interior basin plus smaller reversals; no claim of a strictly smooth U is made. K6 is explicitly irregular because its C2→3 rise and C3→4 fall both repeat in 5/5 rounds.

Queue-down/DMR-up intervals are preserved in adjacent_c_deltas.csv. Strong examples: K5 C2→3, K6 C2→3 and C5→6, K7 C4→5 and C5→6 each have queue decrease and DMR increase in all five original-round pairs. K4 C4→5 also has both signs in 5/5, despite mean service falling. These changes are accompanied by start-lag/front-end/tail changes and are not assigned to a single cause.



# 8. Actual In-Flight Concurrency and Admission Saturation



K1/C1: cap saturation 34.301% versus cap-with-waiting 0.050%. K2/C2: 31.108% versus 0.096%. K7/C7: 59.987% versus 1.580%. Conflating cap saturation with waiting would materially mischaracterize these states.

At K7/C8 the corresponding fractions are 1.290% and 0.836%, yet DMR is 96.611%. Admission-cap relief alone therefore is not a proxy for deadline success. This does not identify GPU-internal bottlenecks.



# 9. Latency Decomposition



At K7 C4→8, queue mean falls 11.356→0.487 ms, while start lag rises 2.245→29.991 ms, front-end 13.121→14.896 ms, service 15.237→27.735 ms and local mean 41.959→73.108 ms. Mean run-level local P95 rises 70.901→352.354 ms. Thus queue/service alone omit an important pre-ready contribution. At K6 C2→8, start lag increases 0.946→9.114 ms while service increases 8.543→24.292 ms and queue falls 9.428→0.362 ms.

Selected deadline-conditioned results are in deadline_frame_components.csv. Each conditional mean is calculated within a run, then compared with equal weight across runs; aggregate frame counts describe the traces, not independent statistical samples. At K7/C8, missed-frame mean components averaged across runs are start lag 31.036, front-end 15.055, queue 0.499, service 28.121 ms. At K7/C4 they are 4.079, 14.667, 23.523, 14.363 ms. Multiple components differ; no kernel-contention cause is established.

Temporal exceedance is essential: all 12 K1/C4 misses and 25 K1/C8 misses across five runs occur in the first logical second; likewise all 53 K2/C2 and 103 K2/C8 misses. At K4/C5 94.29% occur in that second. In contrast, only 1.73% of K7/C8 misses occur there, so its high DMR is not a startup-only phenomenon. These diagnostics do not remove any startup sample or recompute a “steady-state primary” result. High-C start-lag tails are observed, but their underlying cause is not proven.



# 10. Static-C Descriptive Analysis



| K | Best-observed C | Mean DMR % ± SD | Second C | Gap pp | Pairs favoring first | Interpretation |
|---|---|---|---|---|---|---|
| 1 | 4 | 0.1333 ± 0.0304 | 3 | 0.0222 | 3/5 | no clear single winner |
| 2 | 2,3,4 | 0.2944 ± 0.0373 | 3 | 0.0000 | 2/5 | no clear single winner |
| 3 | 2 | 0.4630 ± 0.0859 | 4 | 0.0519 | 4/5 | no clear single winner |
| 4 | 4 | 0.5611 ± 0.1051 | 2 | 0.1056 | 4/5 | no clear single winner |
| 5 | 2 | 2.1467 ± 1.6760 | 3 | 1.5489 | 5/5 | no clear single winner |
| 6 | 2 | 32.2963 ± 0.3590 | 4 | 1.8019 | 5/5 | consistent separation in these repeats |
| 7 | 4 | 47.3905 ± 0.8411 | 3 | 11.4841 | 5/5 | consistent separation in these repeats |



“Best-observed static C within the measured C=1..8 grid” is selected using this same dataset. The regret table quantifies the gap to that configuration in hindsight; it is not an online-policy score. K1–K5 have no clear single winner under the conservative descriptive gap/direction flag; K5 nevertheless favors C2 over C3 in all five pairs, with large variation in effect size.

Exploratory equal-K mean DMR is minimized at C4: 12.7853%. The hindsight per-K minima average 11.8979%, a descriptive gap of 0.8874 pp. Equal K weights are not deployment frequencies and this gap is not a predicted Dynamic-C benefit. A fixed C4 is a sensible comparator for future tests, not a universally dominant configuration or an established adequate setting for an unspecified SLA.



# 11. Run-to-Run / Round-Paired Consistency



Adjacent tables retain every original-round difference, including explicit MISSING_ORIGINAL_FAIL entries at K2/C1→2 Round4 for each metric. That comparison has four pairs; all others have five. Replacement appears in primary means only. Queue and service effects are highly consistent in the main low-to-mid C transitions at K2–K7; small high-C steps and low-load DMR are often mixed.

The central non-adjacent contrast is C2→4: K6 DMR +1.8019 pp, paired range +0.8519 to +3.6944, 5/5 increases; K7 −35.3889 pp, paired range −52.1508 to −11.7222, 5/5 decreases. This supports workload dependence without needing a selected best-C claim.

Variability is retained: K5/C3 DMR=[2.9222,10.3778,1.5889,1.7222,1.8667]%; K6/C1=[63.9537,100,77.9907,36.1389,37.9259]%; K7/C2=[100,79.4603,84.0159,91.1667,59.2540]%. These are valid runs, not grounds for exclusion. kc_full_summary.csv includes sample SD, min/max, CV (undefined at zero mean) and all five values. Near-zero DMR CV is unstable and is not used to rank configurations.



# 12. Temporal Drift



| Round | Service cell-centered ms | DMR cell-centered pp |
|---|---|---|
| 1 | +0.01518 | +0.70652 |
| 2 | -0.06348 | +0.77917 |
| 3 | +0.02370 | +0.16531 |
| 4 | +0.01563 | -0.58042 |
| 5 | +0.00896 | -1.07057 |



The balanced 55-cell original-only panel shows no sustained service drift but visible DMR round bias concentrated in sensitive conditions. Meaningful system-wide drift attribution is UNCLEAR; balance reduces temporal confounding but does not prove its absence. See round_drift_analysis.md for slopes, per-cell contributions and the original 279-row reference. No drift correction or replacement insertion is performed.



# 13. Replacement Sensitivity



| Metric | Primary valid5 mean | Original valid4 mean | Original4 + invalid-exit run04 mean |
|---|---|---|---|
| queue_mean_ms | 3.072819 | 3.071957 | 3.063498 |
| service_mean_ms | 5.975020 | 5.985916 | 5.989965 |
| deadline_miss_percent | 0.322222 | 0.319444 | 0.316667 |
| local_p95_ms | 23.629296 | 23.688164 | 23.693220 |
| time_weighted_mean_A | 0.358501 | 0.359155 | 0.359398 |



Primary valid5 versus original valid4 changes K2/C1 DMR by +0.002778 pp and mean run-level local P95 by −0.058868 ms. The secondary invalid-exit comparison is similarly close. Replacement handling does not materially alter the K2/C1 characterization; it is not a formal equivalence test. The failed run remains excluded from primary and round analyses.



# 14. Research Hypotheses



| Hypothesis | Verdict | Numerical / repeated evidence |
|---|---|---|
| H1 | CONFIRMED | Queue response differs with K: K1 C1→2 +0.0389 ms (4/5 up), K2 −2.8916 ms (4/4 down), K7 −5073.2284 ms (5/5 down). |
| H2 | CONFIRMED | Service increases at some higher C: K5 C4→5 +5.7248 ms and K7 C6→7 +5.3554 ms, both 5/5 up. It does not rise at every adjacent step. |
| H3 | CONFIRMED | Same region: K5 C4→5 queue −2.2821 ms and service +5.7248 ms, both consistent in 5/5; K7 C4→5 queue −5.7090 and service +3.0746 ms, 5/5. |
| H4 | CONFIRMED | Non-monotonic DMR accompanies component changes: K5 C1→2 −11.0422 pp then C2→3 +1.5489 pp, each 5/5; K7 C3→4 −11.4841 then C4→5 +21.2778 pp, each 5/5. No causal attribution to queue/service alone. |
| H5 | CONFIRMED | C2→4 DMR rises +1.8019 pp at K6 (5/5), but falls −35.3889 pp at K7 (5/5). |
| H6 | NOT_CONFIRMED | No single fixed C dominates every K in measured DMR. C4 has the lowest exploratory equal-K mean, but C2 is lower at K6 in every round. Adequacy to an unspecified deployment/SLA is not established. |
| H7 | CONFIRMED | Opposite repeat-consistent static preferences and distinct queue/service/blocked-state regimes motivate testing adaptation. Static data do not measure achievable online improvement or transition cost. |



# 15. Implications for Dynamic-C Control



SUPPORTED as research motivation: configuration effects depend on workload, repeat-consistent static preferences conflict, and low ready waiting can coexist with poor deadline performance. A future policy must consider more than ready-queue length or cap occupancy. The data do not establish its state estimator, decision rule, switch timing, achievable miss reduction or cost. Residual predictors, shadow replay and online scheduling are outside this analysis.

Static endpoints do not reveal how already-running requests respond when C changes. Non-preemptive decreases can leave A>C_new temporarily. A transition may incur service/queue/start-lag transients that erase a hindsight static gap. Those must be measured before any superiority claim.



# 16. Next Transition Experiments



| K | Workload | C_low ↔ C_high | Static DMR % | Static queue ms | Static service ms |
|---|---|---|---|---|---|
| 2 | low/moderate | 1 ↔ 2 | 0.322 ↔ 0.294 | 3.073 ↔ 0.181 | 5.975 ↔ 11.000 |
| 5 | boundary | 2 ↔ 5 | 2.147 ↔ 13.773 | 6.317 ↔ 0.482 | 7.708 ↔ 19.694 |
| 6 | deadline overload bridge | 2 ↔ 6 | 32.296 ↔ 86.831 | 9.428 ↔ 0.379 | 8.543 ↔ 23.942 |
| 7 | high/severe deadline overload | 4 ↔ 7 | 47.390 ↔ 97.262 | 11.356 ↔ 0.780 | 15.237 ↔ 28.019 |



These eight directional candidates are proposals only, not executed. K2 spans a real queue/service change before its occupancy plateau; K5 spans the sensitive deadline boundary; K7 spans sharply different service/start-lag/deadline behavior; K6 isolates a large high-C deadline penalty while throughput remains near offered. Measure already-running inference service response, ready-queue response, pre-ready latency, transient deadline misses, and non-preemptive decrease. Preserve both directions; do not fabricate completion times from static traces.



# 17. Limitations



- Same video content repeated; run is the experimental unit, not frames or independent workload samples.

- One Jetson AGX Thor platform and RT-DETR Warehouse workload; MAXN with natural/unlocked DVFS, not fixed device frequency.

- C=1..8 is the tested range, not hardware maximum; C and A are application-level in-flight quantities.

- A<=C is a static-C invariant only; a future non-preemptive decrease can temporarily give A>C.

- A=C alone does not prove queued admission blocking; the new metric requires simultaneous Q>0 and uses host accounting boundaries, not measured observer publication delays.

- A(t) is not kernel-level parallelism or utilization; GPU internal kernel/resource contention was not directly profiled.

- Mean A and service share an interval-area identity; association alone does not establish a direction of causation.

- Run-level P95/P99 averaging is not pooled percentile calculation; component P95s are not additive.

- 60-second offered window with startup and drain retained; no theoretical queue-stability proof or stationarity claim.

- Replacement is post-campaign; original K2/C1 Round4 remains missing in temporal/paired analysis.

- Five repeats can expose variability but cannot exclude temporal confounding. Some means/tails are highly variable; no valid outlier was removed.

- Historical video content hashes were not recorded for the replacement audit; path and ffprobe identity matched, historical content-hash continuity remains UNKNOWN.

- Best-observed C and regret are post-hoc descriptive quantities with selection bias; equal-K weighting is not a deployment distribution.

- Dynamic-C gain, transition cost and online decision accuracy are not demonstrated by static characterization.

- The retained stale pilot/non-formal validator strings are documented legacy labels; raw/frozen artifacts were not rewritten.



**Final verdict: FORMAL_CHARACTERIZATION_SUPPORTS_DYNAMIC_C_MOTIVATION**



This verdict motivates controlled transition research only. No new GPU measurement, replacement, Dynamic-C/Edge run, source modification, commit or push was performed.
