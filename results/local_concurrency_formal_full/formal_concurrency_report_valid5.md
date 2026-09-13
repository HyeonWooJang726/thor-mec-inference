# Full Formal Local Static-Concurrency — primary valid-five dataset

[PRE-EXISTING REPLACEMENT CHECK]

Existing measurement artifact: NO. Existing measurement process: NO. Duplicate execution prevented: YES.

[PRE-FLIGHT]

HEAD: c8352245fa8be6aefff6d7ba91c29c669bb19ea7; origin/main: c8352245fa8be6aefff6d7ba91c29c669bb19ea7.
Frozen source/profile/engine SHA256: MATCH. MAXN, clock-unlocked DVFS, B=1, FP16 engine, 640×640, TensorRT 10.16.2.10, CUDA and Python: MATCH.
Input video paths and ffprobe identity: MATCH. Historical video content SHA256: UNKNOWN because it was not recorded; current SHA256 is retained in preflight.json.

The frozen CLI restricts identifiers/output paths to the original campaign. identity_adapter.py calls its unchanged parser on the recorded successful command, changes only the returned run_id and output_dir, then executes the unchanged frozen main(). No inference, preprocessing, timing, pacing, EOS, context, stream, or buffer code was changed.

[ORIGINAL FAILED RUN]

Global index 220; K=2, C=1; original Round 4/repeat 4/run04. 3600/3600 frames. Permanent FAIL: RuntimeError: child exit code -11. It is excluded from primary statistics, even though frame validation passed.

[REPLACEMENT]

Artifact: results/local_concurrency_formal_full/replacements/c1/k2/replacement01

Acquisition phase: POST_CAMPAIGN_REPLACEMENT. Start: 2026-09-12T23:42:25.431088+00:00. End: 2026-09-12T23:43:28.119491+00:00.
Actual child exit code: 0. K=2, C=1, completed/expected=3600/3600; 1800 per stream; natural EOS, formal integrity, independent validation and queue accounting: PASS.
Waiting after drain=0; active after drain=0; observed max A=1. Timestamp/decomposition errors=0 ns. All four workers joined; both pipelines NULL; no watchdog/runtime errors.

[ORIGINAL CAMPAIGN ACCOUNTING]

COMPLETED; attempted=280, PASS=279, FAIL=1, ABORTED=0. Original campaign_status.json is unchanged.

[REPLACEMENT ACCOUNTING]

attempted=1; PASS=1; FAIL=0; automatic retries=0.

[PRIMARY VALID DATASET]

56 conditions × 5 valid measurements = 280. Total completed primary frames: 2,016,000.
K2/C1: run01, run02, run03, replacement01 (statistical slot 4), run05. The other 55 conditions retain their original five PASS measurements and their aggregates are numerically identical.

[DRIFT HANDLING]

Replacement included as original Round 4 sample: NO. Its actual_round_id, round_id, repeat_id, and global_run_index are null. statistical_slot=4 is only a primary aggregation slot, not a temporal label.
campaign_drift_summary.csv and the original temporal/paired-round analyses are preserved. This replacement is not used to repair a missing Round 4 drift observation.

[STATISTICAL INTERPRETATION]

Each run receives equal weight. Each metric reports mean, median, sample SD (ddof=1), min, max and all five individual statistical-slot values. These are repetitions of the same video content measuring system variability, not independent workloads.
K2/C1 includes one later acquisition; its time separation is a limitation, not disguised as within-campaign randomization. No outlier filtering, synthetic values, refit, sensitivity analysis including failed run04, or new sweep was performed.
Legacy validation strings “LOCAL CONCURRENCY PILOT / NON-FORMAL” and “Single pilot run per K,C; no final formal conclusion” are stale validator labels. Frozen/raw artifacts are not relabeled; Formal wrapper metadata remains authoritative for the acquisition configuration.

[K2/C1 FIVE VALID MEASUREMENTS]

| Measurement | Phase | DMR % | Queue mean ms | Service mean ms | Local p95 ms | FPS |
|---|---|---:|---:|---:|---:|---:|
| run01 | ORIGINAL_CAMPAIGN | 0.250000 | 3.047796 | 5.975964 | 23.820137 | 60.007396 |
| run02 | ORIGINAL_CAMPAIGN | 0.305556 | 3.080453 | 5.990672 | 23.715575 | 60.010534 |
| run03 | ORIGINAL_CAMPAIGN | 0.333333 | 3.050433 | 5.982374 | 23.625732 | 60.012101 |
| replacement01 | POST_CAMPAIGN_REPLACEMENT | 0.333333 | 3.076270 | 5.931435 | 23.393824 | 60.006939 |
| run05 | ORIGINAL_CAMPAIGN | 0.388889 | 3.109145 | 5.994654 | 23.591211 | 60.009322 |

[K2/C1 AGGREGATE]

| Metric | Mean | Median | Sample SD | Min | Max |
|---|---:|---:|---:|---:|---:|
| start_lag_mean_ms | 0.489645 | 0.490344 | 0.062320 | 0.416581 | 0.577616 |
| start_lag_median_ms | 0.323976 | 0.321618 | 0.021736 | 0.296554 | 0.345849 |
| start_lag_p95_ms | 0.876015 | 0.839086 | 0.092788 | 0.814084 | 1.036772 |
| front_end_mean_ms | 10.020937 | 9.992064 | 0.139990 | 9.865519 | 10.248070 |
| front_end_median_ms | 9.964282 | 9.998619 | 0.261284 | 9.638560 | 10.340186 |
| front_end_p95_ms | 10.530333 | 10.556797 | 0.083930 | 10.412760 | 10.635320 |
| queue_mean_ms | 3.072819 | 3.076270 | 0.025085 | 3.047796 | 3.109145 |
| queue_median_ms | 3.946113 | 3.964819 | 0.096855 | 3.813875 | 4.070977 |
| queue_p95_ms | 6.502493 | 6.515427 | 0.050161 | 6.444805 | 6.561507 |
| queue_p99_ms | 6.888273 | 6.935159 | 0.148734 | 6.735690 | 7.087817 |
| service_mean_ms | 5.975020 | 5.982374 | 0.025422 | 5.931435 | 5.994654 |
| service_median_ms | 5.951375 | 5.935773 | 0.068785 | 5.871614 | 6.026224 |
| service_p95_ms | 6.664650 | 6.702016 | 0.093016 | 6.560305 | 6.772942 |
| service_p99_ms | 6.961574 | 6.989272 | 0.177019 | 6.755500 | 7.214329 |
| local_mean_ms | 19.558421 | 19.546934 | 0.078767 | 19.476024 | 19.688411 |
| local_median_ms | 19.530943 | 19.639914 | 0.291243 | 19.073894 | 19.819907 |
| local_p95_ms | 23.629296 | 23.625732 | 0.158725 | 23.393824 | 23.820137 |
| local_p99_ms | 24.402787 | 24.544676 | 0.271742 | 24.050887 | 24.685223 |
| deadline_miss_percent | 0.322222 | 0.333333 | 0.050461 | 0.250000 | 0.388889 |
| completed_FPS | 60.009258 | 60.009322 | 0.002154 | 60.006939 | 60.012101 |
| observed_max_A | 1.000000 | 1.000000 | 0.000000 | 1.000000 | 1.000000 |
| time_weighted_mean_A | 0.358501 | 0.358942 | 0.001525 | 0.355886 | 0.359679 |
| fraction_time_A_equals_C | 0.358501 | 0.358942 | 0.001525 | 0.355886 | 0.359679 |
| peak_waiting_queue | 6.600000 | 7.000000 | 0.894427 | 5.000000 | 7.000000 |
| time_weighted_waiting_queue | 0.184635 | 0.184813 | 0.001532 | 0.183065 | 0.186861 |
| waiting_carryover_percent | 0.155556 | 0.166667 | 0.046481 | 0.111111 | 0.222222 |
| active_carryover_percent | 0.177778 | 0.166667 | 0.024845 | 0.166667 | 0.222222 |
| source_duration | 60.000000 | 60.000000 | 0.000000 | 60.000000 | 60.000000 |
| drain_duration | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| run_wall_time | 62.950048 | 63.014879 | 0.146286 | 62.688396 | 63.018994 |

[FILES]

formal_per_run_summary_valid5.csv; formal_kc_aggregate_valid5.csv; valid5_integrity.json; replacements/c1/k2/replacement01/; replacements/_control/.

[VERDICT]

VALID_REPLACEMENT

[COMMIT/PUSH]

NO
