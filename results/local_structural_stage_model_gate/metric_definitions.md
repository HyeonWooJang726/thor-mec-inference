# Audited metric and feature definitions

Sources: `results/local_concurrency_formal_full/_campaign/profile_fullsource.py`, `scripts/local/local_latency_breakdown_metrics.py`, Formal `analysis_valid5/metric_definitions.md`, valid5 membership CSV and frozen code hashes. Raw records are cross-checked against per_frame.csv.

a = t0 + floor(frame_id*1e9/30), logical arrival. r is the timestamp immediately after state-lock-protected unbounded ready-queue put following preprocessing. s is start accounting under the same lock immediately before inference; c is the timestamp immediately after infer returns with host outputs, before later completion-counter publication. W=s-r; S=c-s is system-level request service, not pure GPU kernel time.

Strict deadline crossing is 30*(x-a)>1e9 for x=r,s,c. Store b30=1e9-30*(r-a), an integer in units of 1/30 ns. Eligible iff b30>=0. Q label iff 30*W>b30, S label iff 30*W<=b30 and 30*(W+S)>b30; otherwise O. No rounded absolute deadline. For integer W,S, W+S<=floor(b30/30) is mathematically equivalent to the rational comparison; the floor is a CDF query conversion, not a truncated deadline definition. Reporting budget in ms is b30/30e6.

Q is recorded inference_queue_depth_before_enqueue, before target inclusion. Independent endpoint/event sweeps check it. A_ready counts s_j<r_i and c_j>=r_i; A_start counts s_j<s_i and c_j>=s_i, excluding target. Ambiguous cross-event timestamp ties cause a stop. Pre-start A is used ONLY as a training transition outcome/service conditioning variable and held-out assumption-audit variable, never as the target prediction input. Actual test W,S likewise only evaluate labels/assumptions.

A is application in-flight interval state, not kernel concurrency or GPU utilization. Completion publication/receipt timestamps are unavailable: this is ideal zero-publication-delay event-time observability, not a measured online observer implementation. No future completion duration enters the before-state: only whether an endpoint has already occurred. Static invariants A_ready<=C and A_start<C apply here, not a general Dynamic-C invariant.

Ready-on-time training includes queue-late service observations to avoid conditioning the service CDF on a favorable outcome. PRE_READY_LATE means already late on this observed path, not a policy-invariant lower bound. Five slots represent repeated same-video acquisitions and system variability; replacement is not temporal Round4. Dynamic data are unused.
