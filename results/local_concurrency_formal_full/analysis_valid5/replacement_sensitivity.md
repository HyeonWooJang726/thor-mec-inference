# K2/C1 replacement sensitivity — secondary only

| Metric | Primary valid5 mean | Original valid4 mean | Original4 + invalid-exit run04 mean |
|---|---|---|---|
| queue_mean_ms | 3.072819 | 3.071957 | 3.063498 |
| service_mean_ms | 5.975020 | 5.985916 | 5.989965 |
| deadline_miss_percent | 0.322222 | 0.319444 | 0.316667 |
| local_p95_ms | 23.629296 | 23.688164 | 23.693220 |
| time_weighted_mean_A | 0.358501 | 0.359155 | 0.359398 |

The invalid-exit run04 remains FAIL and is excluded from all primary analysis. The optional final column uses its retained raw/summary values only as an explicitly abnormal-exit secondary check, not as a valid replicate. No original artifact was modified. Primary versus original valid4 changes queue mean by +0.000863 ms, service by -0.010896 ms, DMR by +0.002778 pp, local run-P95 mean by -0.058868 ms and mean A by -0.000654. This does not materially change the K2/C1 characterization relative to the multi-ms C1→2 queue/service response or the unresolved low-C DMR ranking.

Replacement handling does not materially alter the K2/C1 characterization. This is a descriptive assessment, not a formal equivalence test. It remains a later acquisition, never a Round4 pair. Full n, sample SD, min and max are retained in replacement_sensitivity.csv.

