# Regression result

PASS: 51 tests, 0 failures (27 existing Local/concurrency, 7 preserved previous EOS evidence tests, 17 new bounded/full-source lifecycle tests). See regression.log and regression_result.json.

The existing formal-orchestrator unit fixture patches OUTPUT, but a function default argument captures the populated real output root. The test harness rebinds this default in memory to the fixture's temporary OUTPUT; production files and protected results are untouched. This known fixture isolation issue is not reported as a runtime fix.

New tests cover exact bounded completion without bus EOS, incomplete samples/completions, waiting/active backlog, join failure, GStreamer ERROR, watchdog, independent true/false EOS observation with no mutation, full-source EOS requirement, pipeline shutdown failure, worker exception, abnormal loop return, duplicate IDs, delayed source completion/join, and reversed completion ordering. CPU fixtures are correctness tests, never performance measurements.

Performance freeze audit PASS: pipeline/arrival/inference/statistics AST equivalence; full front-end acquisition-loop AST equivalence; TensorRT/resource validator byte equivalence; EOS state only assigned by actual message handler. Classified performance-path changes: 0.
