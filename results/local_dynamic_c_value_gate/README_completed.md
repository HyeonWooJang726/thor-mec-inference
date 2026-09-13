# Completed Dynamic-C value-gate artifacts

Final results: [recovery final report](recovery_001/recovery_final_report.md), [generated analysis](recovery_001/analysis_report.md), [paired comparisons](recovery_001/paired_comparison.csv).

The original campaign_status.json remains HALTED and the original FIXED_C4 smoke row remains FAIL because summary generation failed after child exit 0 and 780 completed frames. Recovery validated reuse of that smoke, acquired the one remaining lookup smoke, then completed all 30 primary acquisitions (351,000 requests). Total actual GPU acquisitions: 32; automatic retries: 0. Verdict: NO_OBSERVED_ADVANTAGE_IN_TESTED_TRACES.

Original frozen acquisition code is under _code/. Recovery-only postprocessing/bookkeeping copies are under recovery_001/_code/. Runtime/engine/workload definitions were unchanged. Recovery incident, patch, CPU replay and freeze evidence are preserved. CPU synthetic fixtures and local raw files remain local and are not part of primary statistics or this compact commit.

Per-run commands, actual exits, resource metadata, termination, integrity and summaries are included. Raw per_frame.csv, events.csv, logs, engines and videos are local-only. Compact environment exports retain recorded settings/sensors and source hashes while omitting host process command lines and environment variable dumps.

Static Formal figures and previous figure relocation are outside this commit. Their working-tree changes were left untouched. The state_history_analysis directory, if later created, is a separate uncommitted secondary analysis requiring user review.
