# Rate / GPC frequency Gate

V2 stop: **SMOKE_PROCESS_EXIT_FAILURE**, PIPELINE_AUDIT_FAIL. No V2 primary or
K6 sanity run started, and no retry occurred. OC3 is not the stop reason.

Both V2 smoke measurement replays have correct frame/queue/rate/concurrency
accounting. However, SMOKE01 exited nonzero after saving a pre-exit VALID summary.
Its original supervisor failed to persist the numeric exit code and to reflect
it in that summary. Exact signal/cause is unknown. V2 aggregate annotations mark
it INVALID; original five run files remain untouched. SMOKE02 exited successfully.
See EXPERIMENT_PLAN_V2.md first section for evidence and the immutable outcome
annotation, and gate_verdict.md for Gate statuses.

The supervisor is now corrected to finalize future newly executed runs only
after observing the child exit code. An offline regression passed for a simulated
nonzero exit after a pre-exit VALID summary. No GPU rerun validates the correction.
V2 remains a blocked preparation plan, not a final frozen primary plan. Primary
execution is guarded by final freeze and confirmed successful smoke process exits.
No speculative teardown workaround, threshold change, extra K, or recovery run.

V2 protocol implementation: decode → deterministic admission → admitted-only
preprocess → unchanged shared ready queue → independent TensorRT B1 workers.
Q uses ready r to service start s. OC3 annotates CLEAN/PROTECTION_LIMITED and does
not abort/invalidate; actual limited clocks are retained. Ordinary invalid primary
runs continue without retries. The required smoke/pipeline gate remains mandatory.

V1 plan and all V1 run artifacts are unchanged. V1 P01 is excluded from V2 only
as PROTOCOL_V1_ABORT_ON_OC3. Historical source/root reports are losslessly archived
in protocol_v1_snapshot.tar.gz; exact V2 smoke source/preparation reports in
protocol_v2_smoke_snapshot.tar.gz. Both archives avoid adding loose intermediate
CSV/code copies. New aggregate CSVs index V1 exclusions and V2 outcomes; replay
never overwrites run artifacts. Existing canonical code/evidence is unchanged.

GPU default range restored to 315–1575 MHz; governor unchanged. No package,
nvpmodel, CPU/NVD/EMC, fan or network setting changes. No controller/model fitting.
