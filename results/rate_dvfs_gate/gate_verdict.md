# Rate/DVFS Gate V2 verdict

Final: **ADMISSION_GATE_FAIL**

Prior runs are historical, untouched and excluded. V2 P02 exclusion_reason=OLD_PROTOCOL_ABORT_ON_SOURCE_LAG. Original plans/code/root reports are preserved in pre_backlog_amendment_snapshot.tar.gz.

| Gate | Verdict |
|---|---|
| PIPELINE_AUDIT | PASS |
| ADMISSION_GATE | FAIL |
| FREQUENCY_CAPACITY_GATE | PASS |
| ENERGY_OPPORTUNITY_GATE | PASS |

B(t)=logical admitted count minus inference completion count. Logical source and admission use the 30-FPS frame index, independent of decoder progress. Admission→completion includes every unfinished stage. Source/decode/ready lag is diagnostic only, not an abort or invalidation. Primary stability uses only g_B<=0.5 frames/s in the final active 30 s, with no cap/drop and valid integrity.

Observed r_star (FPS/stream): {'LOW': 21, 'MID': 27, 'HIGH': 30}. None means no stable tested point; no extrapolation below the grid.

Condition means below use integrity-valid repetitions; at least two required, all valid repeats must agree on stability. Median power is the median of per-run active average power. OC3 does not exclude a valid repetition.

| K | MHz | r | completed FPS | min stream FPS | g_B | state | avg GPU W | J/frame | clean/protected | frontend-limited | valid/attempted |
|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---|
| 6 | 1575 | 30 | 179.972 | 29.983 | 0.003 | QUEUE_STABLE | 46.017 | 0.256 | 0/3 | 0 | 3/3 |
| 6 | 945 | 30 | 164.617 | 27.428 | 15.265 | UNSTABLE | 33.682 | unavailable | 3/0 | 0 | 3/3 |
| 6 | 1260 | 30 | 179.961 | 29.983 | -0.005 | QUEUE_STABLE | 41.894 | 0.233 | 3/0 | 0 | 3/3 |
| 7 | 1575 | 21 | 146.950 | 20.983 | 0.003 | QUEUE_STABLE | 38.595 | 0.263 | 0/3 | 0 | 3/3 |
| 7 | 1575 | 24 | 167.950 | 23.983 | -0.001 | QUEUE_STABLE | 43.688 | 0.260 | 0/3 | 0 | 3/3 |
| 7 | 1575 | 27 | 188.950 | 26.983 | 0.000 | QUEUE_STABLE | 48.397 | 0.256 | 0/3 | 0 | 3/3 |
| 7 | 1575 | 30 | 209.922 | 29.983 | 0.003 | QUEUE_STABLE | 52.707 | 0.251 | 0/3 | 0 | 3/3 |
| 7 | 945 | 21 | 146.878 | 20.978 | 0.004 | QUEUE_STABLE | 30.721 | 0.209 | 3/0 | 0 | 3/3 |
| 7 | 945 | 24 | 162.578 | 22.811 | 5.395 | UNSTABLE | 32.085 | unavailable | 3/0 | 3 | 3/3 |
| 7 | 945 | 27 | 164.150 | 23.139 | 24.623 | UNSTABLE | 32.871 | unavailable | 3/0 | 3 | 3/3 |
| 7 | 945 | 30 | 164.189 | 23.328 | 45.866 | UNSTABLE | 32.816 | unavailable | 3/0 | 3 | 3/3 |
| 7 | 1260 | 21 | 146.944 | 20.983 | 0.002 | QUEUE_STABLE | 35.313 | 0.240 | 3/0 | 0 | 3/3 |
| 7 | 1260 | 24 | 167.939 | 23.983 | 0.003 | QUEUE_STABLE | 39.451 | 0.235 | 3/0 | 0 | 3/3 |
| 7 | 1260 | 27 | 188.922 | 26.983 | 0.001 | QUEUE_STABLE | 43.281 | 0.229 | 3/0 | 0 | 3/3 |
| 7 | 1260 | 30 | 203.539 | 28.989 | 6.209 | UNSTABLE | 46.208 | unavailable | 3/0 | 2 | 3/3 |

ADMISSION_GATE witnesses:
- None.

FREQUENCY_CAPACITY_GATE witnesses:
- {"r_star": {"LOW": 21, "MID": 27, "HIGH": 30}, "HIGH_minus_LOW": 9}

ENERGY_OPPORTUNITY_GATE witnesses:
- {"K": 7, "r": 21, "lower": "LOW", "higher": "HIGH", "throughput_difference_fraction": 0.0004914748024649395, "median_power_ratio": 0.7848567540311606, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 21, "lower": "LOW", "higher": "MID", "throughput_difference_fraction": 0.0004536862003780461, "median_power_ratio": 0.8679896229220656, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 27, "lower": "MID", "higher": "HIGH", "throughput_difference_fraction": 0.000147011261062564, "median_power_ratio": 0.8901682249555852, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}

All same-service energy comparisons (including nonqualifying pairs):
- {"K": 6, "r": 30, "lower": "MID", "higher": "HIGH", "throughput_difference_fraction": 6.173792251895636e-05, "median_power_ratio": 0.9107273427366017, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 21, "lower": "LOW", "higher": "HIGH", "throughput_difference_fraction": 0.0004914748024649395, "median_power_ratio": 0.7848567540311606, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 21, "lower": "LOW", "higher": "MID", "throughput_difference_fraction": 0.0004536862003780461, "median_power_ratio": 0.8679896229220656, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 21, "lower": "MID", "higher": "HIGH", "throughput_difference_fraction": 3.7805754035794336e-05, "median_power_ratio": 0.904223660403865, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 24, "lower": "MID", "higher": "HIGH", "throughput_difference_fraction": 6.615725579691296e-05, "median_power_ratio": 0.9003575803224585, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}
- {"K": 7, "r": 27, "lower": "MID", "higher": "HIGH", "throughput_difference_fraction": 0.000147011261062564, "median_power_ratio": 0.8901682249555852, "matched_repeats": [1, 2, 3], "consistent": true, "energy_per_frame_same_direction": true}

Invalid V2 runs (preserved; no retries):
- None.

Planned campaign observed: primary 36/36; K6 sanity 9/9.
Integrity-valid campaign runs: 45; PROTECTION_LIMITED valid runs: 15.
Power scope: measured GPU rail VDD_GPU. Energy is active-interval only; J/frame only for stable runs. Actual frequency means exclude recorded idle zeros; non-target clocks are retained, not invalidated due to OC3.
No energy fitting/controller or additional workloads. MAXN fixed; default GPC range restored after each run. See per-run manifests for exact restoration and errors.

Interpretation: these are complete Local SYSTEM capacities. FRONTEND_LIMITED conditions are SYSTEM_CAPACITY_LIMITED_BY_FRONTEND, not GPU-only capacity measurements. A frequency-dependent stable boundary supports SYSTEM_CAPACITY_GPU_SENSITIVE without locating its bottleneck solely inside TensorRT.

Admission failure detail (unchanged 95% criterion):
- LOW: best stable 146.877778 / maximum observed 164.188889 FPS = 89.4566%. Below 95%; the observed stabilization sacrifices too much throughput for this Gate.
- MID: best stable 188.922222 / maximum observed 203.538889 FPS = 92.8187%. Below 95%; the observed stabilization sacrifices too much throughput for this Gate.
- HIGH: best stable 209.922222 / maximum observed 209.922222 FPS = 100.0000%. No unstable higher-admission condition exists in the tested HIGH grid, so HIGH supplies no admission-stabilization transition.

K6 energy interpretation: MID versus HIGH preserves service but its median-power reduction is 8.9273%, below the required 10%. It supports an observed saving, but is not an ENERGY_OPPORTUNITY_GATE PASS witness. The qualifying witnesses come from K7; energy/frame decreases in all matched qualifying repeats.

Completion and preservation verification:
- Single synthetic lag fixture PASS; both amended smokes exit 0/integrity VALID, drain B=0 and frequency restore PASS. Smoke B actually observed frontend lag without abort.
- All 45 planned runs finished active 60 s and drained; 550800 logical source frames and 482760 admitted/completed frames across the campaign. All 47 new children including smoke exited 0; no retry/replacement runs.
- PIPELINE_SEMANTICS=PASS, PROCESS_LIFECYCLE=PASS; concurrency peak exactly C in every run (K7:4, K6:2). All canonical raw summaries replay identically.
- Every run uses amended plan SHA256 412198d20ec2b83a1778da3a2db420b8f0162085e8987e8bd4daee75e3db004c and unchanged frozen source hashes. MAXN before/after all runs; current GPC range min315/max1575 MHz restored.
- All 50 files of prior V1/V2/recovery runs remain byte-identical. Pre-amendment V2 text remains a verbatim prefix and its original hash is verified against the preserved archive. Historical P02 is excluded by OLD_PROTOCOL_ABORT_ON_SOURCE_LAG. No historical evidence was deleted.

## Additional descriptive capacity–power characterization and frontend sensitivity

Analysis only, using the 45 completed amended primary/sanity runs. No GPU execution, frequency change, additional measurement, new threshold, fit, interpolation, extrapolation or new Gate criterion. The entire preceding historical report is preserved verbatim. Historical verdict remains PIPELINE_AUDIT=PASS, ADMISSION_GATE=FAIL, FREQUENCY_CAPACITY_GATE=PASS, ENERGY_OPPORTUNITY_GATE=PASS; final ADMISSION_GATE_FAIL remains unchanged.

Analysis recorded at 2026-09-19T13:37:50.901900+00:00. Frozen plan SHA256: `412198d20ec2b83a1778da3a2db420b8f0162085e8987e8bd4daee75e3db004c`. SHA256 of the report prefix before this addendum: `d4036c57f1049b467befeb35379506756c2501664d2c16672030de5a254b2431`.

Method and provenance: select exactly the 45 IDs in the amended plan order (36 K7/C4 and 9 K6/C2). Replay each per_frame.csv.gz and power_trace.csv.gz with the unchanged frozen summarize() function in scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py. All raw-derived fields matched all 45 stored summaries; condition means matched operating_map.csv. All 45 runs have finalized integrity VALID and child returncode 0. Smoke and historical runs are excluded. No run, plan, source code or canonical CSV was rewritten.

Aggregate exactly as in the primary analysis: group by K/C/frequency/admission; use arithmetic means of the three valid repetitions. Stability must agree in all three. The minimum-stream FPS column is the mean of each run’s minimum R_k; energy/frame is the mean of per-run active energy/completions, only for stable runs. Power is mean active VDD_GPU rail power. Maxima below are maxima over condition means, not selected best individual repetitions. OC3 counts are summed and occurrence denominators are explicit.

**SYSTEM_LEVEL_PRIMARY and CLEAN_SUBSET_SENSITIVITY**

Primary B(t)=logical admissions minus completions includes unfinished work in every local stage. FRONTEND_LIMITED conditions therefore remain legitimate Local system behavior in SYSTEM_LEVEL_PRIMARY. Their diagnostic label does not identify a GPU-only capacity or invalidate the measurements. SYSTEM_LEVEL_PRIMARY ADMISSION_GATE remains FAIL.

For the separate sensitivity, exclude an entire K7 condition if any of its repetitions is FRONTEND_LIMITED, matching the existing condition-level annotation. This is not a run-by-run selection: 1260 MHz/r30 is excluded including its one NORMAL repetition because the other two are FRONTEND_LIMITED. “Clean” here means frontend NORMAL, not hardware CLEAN; all PROTECTION_LIMITED HIGH conditions are retained. Thus 4/12 K7 conditions (12/36 runs, 11 of them individually frontend-limited) are excluded; 8/12 conditions (24 runs) remain.

| MHz | Included r | Excluded r | Stable/unstable conditions remaining | Best stable/subset max throughput | CLEAN_SUBSET_ADMISSION |
|---:|---|---|---:|---:|---|
| 945 | 21 | 24, 27, 30 | 1/0 | 100.00% | INCONCLUSIVE |
| 1260 | 21, 24, 27 | 30 | 3/0 | 100.00% | INCONCLUSIVE |
| 1575 | 21, 24, 27, 30 | None | 4/0 | 100.00% | INCONCLUSIVE |

Overall CLEAN_SUBSET_ADMISSION=INCONCLUSIVE: no unstable condition remains at any frequency, so the required unstable-to-stable comparison cannot be evaluated. The numerical subset ratios of 100% are not PASS evidence. The sensitivity does not replace the primary sample or verdict.

**K7/C4 discrete capacity–power characterization (SYSTEM_LEVEL_PRIMARY)**

r_stable_max is the largest observed stable offered admission FPS/stream. r_sat_obs is the maximum observed unstable aggregate completion FPS divided by 7. It is an average per-stream achieved rate, not every stream’s rate, and differs physically from offered admission. If r_sat_obs>=r_stable_max, [r_stable_max,r_sat_obs] is only a descriptive observed knee region between those two quantities: not an exact knee, true capacity interval, or theoretical bound. If the order is reversed, report saturation_below_stable_boundary without sorting endpoints; that may indicate overload throughput collapse. No reversed ordering occurred here.

| frequency_MHz | max_stable_admission_fps_per_stream | aggregate_completed_fps_at_max_stable | min_per_stream_completed_fps_at_max_stable | avg_VDD_GPU_power_W_at_max_stable | energy_per_frame_at_max_stable (J) | max_unstable_completed_fps | max_unstable_completed_fps_per_stream | observed_knee_characterization | frontend_limited_conditions | OC3_occurrence (K7 all r) | interpretation |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| 945 | 21 | 146.877778 | 20.977778 | 30.720596 | 0.209158 | 164.188889 | 23.455556 | [21, 23.455556] (descriptive only) | r=24 (3/3 runs); r=27 (3/3 runs); r=30 (3/3 runs) | 0/12 PROTECTION_LIMITED; delta sum=0 | Local system observation; unstable maximum at r=30 includes frontend limitation |
| 1260 | 27 | 188.922222 | 26.983333 | 43.280537 | 0.229092 | 203.538889 | 29.076984 | [27, 29.076984] (descriptive only) | r=30 (2/3 runs) | 0/12 PROTECTION_LIMITED; delta sum=0 | Local system observation; unstable maximum at r=30 includes frontend limitation |
| 1575 | 30 | 209.922222 | 29.983333 | 52.706838 | 0.251078 | N/A | N/A | UPPER_KNEE_NOT_OBSERVED_WITHIN_TESTED_RANGE | None | 12/12 PROTECTION_LIMITED; delta sum=241 | Stable through tested maximum r30; no unstable observation; no capacity estimate above 30 |

At 1575 MHz, r_stable_max=30 and r_sat_obs=N/A; knee_status=UPPER_KNEE_NOT_OBSERVED_WITHIN_TESTED_RANGE. No throughput/capacity above 30 FPS/stream is inferred. At 945 MHz the observed stable r21 and unstable r24 are adjacent tested offered-rate points; at 1260 MHz these are r27 and r30. These sampled transitions locate a change within the tested 3-FPS/stream grid steps descriptively; they do not interpolate an exact boundary. The mixed offered/achieved knee regions above are not substituted for these offered-rate grid observations.

All maximum-stable conditions are frontend NORMAL. The unstable maximum at 945 MHz is r30 with 3/3 frontend-limited repetitions, and at 1260 MHz is r30 with 2/3 frontend-limited repetitions; both remain in the system-level characterization. HIGH K7 has 12/12 PROTECTION_LIMITED repetitions (OC3 delta sum 241); none is hidden or removed. At the maximum-stable HIGH r30 point the OC3 sum is 69 across 3/3 protected repetitions.

**Capacity and power trade-off**

The measured maximum-stable operating points show a larger tested sustainable processing-rate region with increasing frequency, accompanied by higher VDD_GPU power. These operating points have different offered demand (21, 27, 30 FPS/stream), so the following joint differences are not a frequency-only power model or an equal-load energy comparison.
- 945→1260 MHz: maximum-stable observed completion +42.044444 FPS (28.6255%), VDD_GPU power +12.559942 W (40.8844%).
- 1260→1575 MHz: maximum-stable observed completion +21.000000 FPS (11.1157%), VDD_GPU power +9.426300 W (21.7795%).

**K6/C2/r30: representative over-provisioning observation**

Both compared conditions are stable and frontend NORMAL in all three repetitions. Demand is fixed at 180 FPS; all 10800 admitted frames per run completed with drain. Active throughput differs slightly from exact demand because primary accounting excludes completions after the 60-s boundary.

| MHz | Active completed FPS | Mean per-stream FPS | Demand fulfilled in active interval | Mean VDD_GPU W | Median per-run average W | Mean J/frame | g_B | OC3 counts by repeat | Protected runs |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1260 | 179.961111 | 29.993519 | 99.978395% | 41.893624 | 41.928145 | 0.232793 | -0.005302 | [0, 0, 0] | 0/3 |
| 1575 | 179.972222 | 29.995370 | 99.984568% | 46.017408 | 46.038088 | 0.255692 | +0.003197 | [73, 50, 59] | 3/3 |

1575 versus 1260 MHz adds 0.011111 FPS (0.006174% relative to MID), but adds 4.123784 W (9.8435% relative to MID). Choosing MID reduces mean power by 8.9614% relative to HIGH and median per-run power by 8.9273%. OC3 changes from 0 events in 0/3 protected runs at MID to 182 events in 3/3 protected runs at HIGH. This does not establish that OC3 caused any specific throughput effect.

Maximum frequency is not always the best operating point for the measured service/power/protection trade-off: HIGH provides almost no additional completed service at this fixed demand while costing more power and repeatedly activating protection. Within the three tested K6 states, MID is the lowest frequency that sustained the offered demand; this is not a claim of a minimum over all supported frequencies. The observation motivates seeking a minimum sufficient compute-supply state for a workload, not an algorithm or optimality claim. K6 alone still does not satisfy the predeclared 10% median-power saving criterion; the historical energy gate passes using K7 witnesses.

**K7/C4/r21: supporting same-service energy example**

Both conditions are stable and frontend NORMAL. LOW: 146.877778 FPS, 30.720596 W, 0.209158 J/frame. HIGH: 146.950000 FPS, 38.595300 W, 0.262642 J/frame. Throughput differs by 0.049147% relative to HIGH; LOW saves 20.4033% mean power and 21.5143% median per-run power. This remains supporting energy-opportunity evidence; K6 MID/HIGH is the representative over-provisioning case.

**Admission effect versus the historical Gate**

Admission affected backlog stability, but the pre-registered admission gate failed to retain at least 95% of the observed maximum throughput at the sampled admission grid. This is not evidence that the admission mechanism had no effect.
- 945 MHz: stable offered r=[21]; unstable r=[24, 27, 30]. Best stable/maximum observed throughput=146.877778/164.188889=89.4566%. The 95% retention requirement is unmet.
- 1260 MHz: stable offered r=[21, 24, 27]; unstable r=[30]. Best stable/maximum observed throughput=188.922222/203.538889=92.8187%. The 95% retention requirement is unmet.
- 1575 MHz: stable offered r=[21, 24, 27, 30]; unstable r=none. Best stable/maximum observed throughput=209.922222/209.922222=100.0000%. No unstable-to-stable transition was observed; the 100% ratio alone is not PASS evidence.

These measurements show frequency-dependent Local system sustainable processing regions. At low demand, raising frequency need not materially improve completion rate and can add power cost; at higher demand it can expand the sustainable region. Required compute supply therefore depends on workload demand within the measured grid. Admission changes backlog stability while its historical Gate remains FAIL. HIGH protection activity remains part of the measured behavior. None of these observations is a fitted capacity law, new optimization result, or theoretical guarantee.

The measured local system exhibits frequency-dependent sustainable processing regions: higher GPU supply expands the supported processing-rate region, while excessive supply can increase power and protection activity without improving service when workload demand is already satisfied.

Preservation: this addendum is the only result-file change. Existing run artifacts, raw traces, frozen plans, aggregate_summary.csv, operating_map.csv and source files retain their prior bytes. No additional result files were needed.
