# Two Local/concurrency paper figures

## Audit and cohort selection

Figure 1 reads `results/local_canonical_c2/per_run_summary.csv`, the formal plan and PASS integrity report, and independently replays every selected raw `k*/run*/per_frame.csv`. B=1, C=2, K=1–7; five runs per K, 60 seconds, full-source natural EOS, phase-aligned 30 FPS, 1800 frames/stream; 35 runs / 252,000 frames.

Figure 2 uses only `results/local_inference_concurrency/c2_vs_c4_fullsource_validation/`: its per_run_summary.csv, run_plan.json, fullsource_integrity_report.json and c*/k*/run*/per_frame.csv. C={2,4}, K={5,6,7}, three runs per cell; 18 runs / 194,400 frames. The same engine, input mapping, full-source workload, transfers, timing and termination definitions apply within this campaign; C changes only the concurrency resource count. Its two gate runs are excluded. This is matched targeted validation, not the canonical 35-run dataset. Canonical C2 and targeted C2 are not pooled.

Other coverage, excluded from these figures: formal C1/C2 control (K5–7, n=5; separate campaign); full-source C3/C5/C6 sanity (K5–7, n=1); C2/C4/C7 bounded 30-second screening (K5–7, n=2); engine-only C1–7 trtexec (n=5, no application deadlines). The completed bounded campaign is at `application_c247_screening_v2/bounded_contract_campaign/`; the parent root is a blocked NOT_RUN record. Original screening is incomplete (6 valid, 1 failed, 11 not run), so planned CSV rows must not be treated as observations. Smoke, stress and termination gates are excluded. No single matched full-source repeated C1–7 cohort exists; C7 is only a shorter bounded application reference. No missing combination is estimated or interpolated. Full audited coverage and original plan fields are in artifact_coverage_audit.json.

## Metrics and uncertainty

Candidate deadline: exactly 1/30 second (33.333333… ms), using `(c_ns-a_ns)*30 > 1000000000`. It is a cadence-based candidate, not an application SLA. Queue waiting is application-level inference-ready waiting `s-r`; active service is excluded. Inference service is `c-s`, including host-side execution/submission, transfers and stream-local completion, not pure GPU kernel time. Integer raw timestamps are the source of truth.

Each run's miss percentage and arithmetic per-frame means are recomputed independently and agree with its source summary within absolute 1e-10 / relative 1e-12 tolerance. Group points are arithmetic means of five (Figure 1) or three (Figure 2) run statistics. Error bars are sample SD (ddof=1), not SEM or confidence intervals. No pooling or exclusions; individual run values, min/max and SD are retained in the two CSVs. Figure 1's log axis shows arithmetic mean±SD in milliseconds, without a log-space aggregation. Figure 2's descriptive SD whisker can extend above 100%; it is not a probability interval and is not clipped.

## Figure 1 caption

**Deadline knee and queueing growth.** Canonical static Local runtime B=1, C=2. Left: candidate deadline misses as load increases. Right: application inference queue wait and host-visible inference service, on a logarithmic duration axis. Points and error bars show mean and sample SD across five 60-second full-source runs. Neutral shading marks K5–K6. Queue waiting grows at the same load transition as deadline degradation; this observational decomposition does not by itself prove exclusive causation. Service duration is not monotonic across all K.

K5→K6: miss 2.3511%→32.1852%; queue 5.9887→9.7306 ms; service 7.7117→8.5367 ms. Absolute queue increase 3.7419 ms exceeds service increase 0.8249 ms. K7 miss reaches 77.1492% with 115.0636 ms mean queue wait.

## Figure 2 caption

**Concurrency trade-off.** Only the matched 60-second full-source C={2,4} targeted campaign is shown. Left: candidate deadline misses at K5/K6/K7; stars mark the lowest observed mean among these two configurations for each workload. Connecting segments are guides between measured settings, not measurements of intermediate C. Right: at K6, higher concurrency reduces waiting while increasing host-visible inference service duration. Points and error bars summarize three runs per cell. No statistical-significance or globally best-concurrency claim is made; engine throughput screening and application QoS are separate evidence.

| K | C2 miss (%) | C4 miss (%) |
|---|---:|---:|
| 5 | 1.6111 | 4.9148 |
| 6 | 32.2901 | 33.7006 |
| 7 | 84.5079 | 47.3836 |

K6 queue: 9.3662→5.1513 ms. Service: 8.5566→14.2606 ms. This is consistent with increased per-request contention under concurrent execution; pure GPU contention and physical kernel overlap were not directly isolated/measured. Lower observed miss occurs at C2 for K5/K6 and C4 for K7; neither tested configuration dominates all three workloads.

## Reproduction and preservation

`python3 -B scripts/concurrency/plot_local_paper_summary.py --output <new-empty-directory>`

The new entrypoint reuses the historical canonical source's DejaVu Sans rcParams, metric colors, markers and errorbar style without importing/executing or changing that source. It writes PNG (300 dpi) and vector PDF; all existing figures and raw artifacts remain untouched. No benchmark, commit or push. See artifact_integrity_report.json for the independent pre/post file checks performed for this task.
