# Source synchronization audit

Classification: **TRACK_FINAL_STUDY_SOURCE/DOCUMENT**. Scope: existing source code, frozen plans/manifests, and measured raw artifacts only. No new workload, runtime/device import, network action, Git command or index change.

**SOURCE_PHASE_SYNCHRONIZED = YES** for the five evaluated campaign families inspected here. **DATASET_CAPTURE_SYNCHRONIZED = UNVERIFIED**. Common logical source phase is established by scheduler code and recorded schedules; exact simultaneous physical release/publication is not established.

## Four separate concepts

| Concept | Finding | What the evidence means |
|---|---|---|
| Original physical dataset capture timing | UNVERIFIED | Plans identify video files and hashes, not shared capture-clock/hardware-trigger evidence. The K8 source list even includes Warehouse_027 cameras 0000–0006 and Warehouse_026 camera 0001. Do not infer simultaneous physical observations from file PTS or replay. |
| Logical replay/source timing | Common epoch, 30 Hz, zero per-stream phase | All active stream IDs share the same planned timestamp for each logical frame index. |
| Actual host release fidelity | Quantified at the recorded pre-publication scheduler observation | The available timestamp precedes queue insertion. It measures source-loop observation lateness and cross-stream observation spread, not exact atomic release. |
| Enqueue/dispatch/GPU timing | Not simultaneous and not required to be | Sequential loop order, OS scheduling, decode, preparation, placement, queueing and transmission can diverge after the common scheduled instant. |

The dataset status is limited to repository plans, input manifests, environment/source documentation and inspected traces. No original camera timestamps, shared-clock mapping or hardware-trigger specification was established. No claim about all multi-camera systems is made. Edge-only E48/Order use cached actual RAW640 payloads indexed by frame modulo cache length, not eight physical cameras capturing live or eight new video decoders; their eight source IDs are replay accounting streams.

## Exact scheduler and field-writing code

Line references below are to the inspected source snapshot; source hashes appear in the input/code inventories.

| Path / function | Relevant lines | Meaning |
|---|---|---|
| scripts/rate_dvfs_gate/run_rate_dvfs_gate.py / run_one → arrivals | 405–423 | Outer frame loop starts at 0; target = manifest active_start + floor(frame_id·1e9/30). One wait per slot, then stream_id in range(k). stream_id does not occur in the target formula. |
| Same / run_one startup | 448–461 | After warmup/pipeline start, one t0 = monotonic_ns()+200000000, shared by all fronts and the arrivals thread. The 200 ms offset is global, not a per-stream phase. |
| Same / front | 385–403 | Front consumes arrival queues. source_pulled_ns is host decoder-pull time; source_timestamp_ns is Gst buffer PTS, not physical capture wall-clock time. |
| results/timely_capacity_campaign/v2_2/validation01/effective_runtime.txt / run_one → arrivals | 266–283; t0 at 317–321 | Frozen effective V2.2 source preserves the common formula/wait and per-stream observation then publication. decorate changes assignment before arrival_queues[sid].put(row). |
| scripts/timely_capacity_campaign/common/v2_2/v22_builder.py / run_source | 49–79 | Preallocated row storage retains logical_arrival_ns=target, admission_timestamp_ns=target, admission_observed_ns=now and the publication point. |
| scripts/timely_capacity_campaign/common/service_phase_b1/b1_common.py / run_source; scripts/timely_capacity_campaign/common/service_phase_v1/build_adapter.py / run_source | source adapters | Worker/accounting/instrumentation adaptation; frozen effective scheduler inspected above is the resulting timing path. |
| scripts/timely_capacity_campaign/local_finalconfig_ksweep01/config.py / run_source, order | 24–60 | Binds strict K-aware placement/summary; K changes stream count. No per-stream timing offset introduced; C_L=3 remains fixed. |
| scripts/timely_capacity_campaign/local_finalconfig_ksweep01/ksweep_schedule.py / decorate | 8–27 | Validates stream IDs and target formula, then all-Local assignment/deadline. |
| scripts/timely_capacity_campaign/block_b_grid02/grid_config.py / local_bit, decorate | 42–45, 77–94 | STAGGERED changes mask index (frame−sid)%30; decorate requires unchanged source due. It changes LOCAL/EDGE destination and Edge request ID only. |
| scripts/timely_capacity_campaign/block_b_confirmation02/grid_config.py / local_bit, decorate | corresponding functions | Same common due invariant; mask phases are destination-placement phases. |
| Grid02/Confirmation02 run_thor.py / Context.bindings | 138–152 | Uses the V2.2 source and binds campaign-specific decorate/summary; no replacement of the source due formula. |
| scripts/timely_capacity_campaign/edge_e48_confirmation01/run_thor.py / run_one | 328–387; t0 345; rows 348–365 | One t0=monotonic_ns()+200000000; frame loop and sleep per slot; sid loop creates due and observation fields; selected rows enter EdgeLink.put, others remain SKIP. |
| scripts/timely_capacity_campaign/edge_order_robustness01/run_thor.py / run_one | 328–390; t0 345; rows 346–368 | Same due formula. selected_order changes host iteration/submission order, not scheduled source time; source_slot=frame. |
| scripts/timely_capacity_campaign/edge_e48_confirmation01/config.py / bit, validate_source_rows | 43–47, 125–184 | Mask-phase shift affects Edge selection, not source due. Fidelity checks universe/mask/logical timestamps/relative order and no planned deferred admission. |
| scripts/timely_capacity_campaign/edge_order_robustness01/config.py / validate_source_rows | 116–164 | Checks source universe, due, mask, request and dispatch order. Does not compute release lateness quantiles. |
| scripts/hybrid_capacity_extension/edge_link.py / EdgeLink.put, sender | 61–71, 88 | payload_ready_ns follows payload SHA computation; socket_submission_ns is later transport dispatch. Neither is the logical source epoch. |
| scripts/expired_work_pruning/pruning_common.py / PruningAccounting.enqueue, begin | 61–79 | r_ns is sampled after Local ready-queue put; s_ns is the later service/expiry decision. |
| scripts/rate_dvfs_gate/run_rate_dvfs_gate.py / save_records | 303–305 | r_ns/s_ns/c_ns map to ready/inference-start/completion CSV fields; enqueue_timestamp_ns also maps from r_ns. |

Production chain: Local K-sweep run_ksweep/config → V2.2 builder → inherited worker; Grid02/Confirmation02 run_thor/grid_config → V2.2 builder + destination decorator; Edge E48/Order run_thor.run_one directly produces the source rows. Their manifest active_start_ns is the per-run epoch used in all recomputations.

No intentional random phase, per-stream startup sleep or source jitter term appears in the inspected scheduler. Sequential decoder pipeline startup does not change source due. Every stream begins at logical frame/slot zero. Nominal period is 1/30 s; nanosecond floor quantization gives intervals of 33,333,333 or 33,333,334 ns. The run's absolute t0 differs across runs, as expected.

## Timestamp semantics and limits

- stream_id: configured replay stream identity; frame_id: per-stream logical source index, starting at zero. In Order, source_slot explicitly duplicates frame_id; elsewhere frame_id is the source-slot key verified from code.
- logical_arrival_ns: scheduled host-monotonic source due, not a measured wakeup.
- admission_timestamp_ns: another copy of that scheduled due, **not actual admission wall time**.
- admission_observed_ns: monotonic sample within the source loop, before row decoration/recording/queue publication (Local/Grid) or selected payload processing/EdgeLink.put (Edge).
- No dedicated timestamp brackets the exact source arrival-queue insertion. Therefore exact actual-publication spread is **UNAVAILABLE**. Reported “release-observation spread” uses admission_observed_ns explicitly as the measured proxy; it does not rename enqueue or dispatch into a source release.
- source_timestamp_ns in full-pipeline traces is decoded video PTS. Equality or regularity of PTS does not prove original camera synchronization.
- b_ns/source_pulled_ns/payload_ready_ns/ready_timestamp_ns/enqueue_timestamp_ns/inference_start_timestamp_ns/socket_submission_ns measure downstream stages. Their differences do not imply intentionally nonzero theta_k.

ALIGNED/STAGGERED correspond to temporally concentrated/dispersed destination assignment. They do **not** change replay source phase. E48 tests select EDGE versus SKIP, whereas Grid02/Confirmation02 select complementary LOCAL versus EDGE. An unselected Edge source row is a logical source event with a scheduler observation, not a transmitted inference request.

## Summary of measured evidence

All **123 measured runs**, **1,317,600 source rows**, **196,200 source slots** were checked. All expected slots were complete. Logical spread max/p50/p95 = **0 ns**; nonzero-spread slots, missing stream-slot pairs, duplicate pairs, extra IDs and formula mismatches = **0**. Four additional campaign warmup sessions were inspected separately, not pooled into measured statistics. All K8 Local repeats were included; the Local family also includes all other K values.

Zero recorded spread checks the recorded logical schedule and agrees with the generating code. It is **not independent proof of simultaneous actual host release**.

| Campaign | Measured runs | Slots | observation spread p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|
| local_finalconfig_ksweep01 | 40 | 72000 | 0.037454 | 0.074797 | 0.088372 | 1.245155 |
| block_b_grid02 | 30 | 54000 | 0.203363 | 2.753825 | 9.294107 | 14.040988 |
| block_b_confirmation02 | 25 | 45000 | 0.569094 | 2.772736 | 8.878780 | 15.781815 |
| edge_e48_confirmation01 | 13 | 11700 | 0.512566 | 3.056999 | 3.078850 | 3.572453 |
| edge_order_robustness01 | 15 | 13500 | 0.040223 | 3.141121 | 3.180846 | 5.308777 |

Local K8 alone (five repeats / 9,000 slots): observation spread p50 **0.068983 ms**, p95 **0.091973 ms**, p99 **0.112364 ms**, max **0.789022 ms**. Its first-slot spreads, R1–R5: **0.088148, 0.103676, 0.101827, 0.093345, 0.106205 ms**.

Across all measured slots, pooled observation spread p50/p95/p99/max = **0.123584 / 2.335341 / 7.411572 / 15.781815 ms**. Across source rows, observation lateness mean/p50/p95/p99/max = **0.444019 / 0.156055 / 1.623262 / 3.638514 / 15.857215 ms**. These pooled descriptive statistics mix different K, placements and campaign conditions; use the per-run tables for comparisons. No new pass threshold is defined.

## schedule_fidelity.json audit

All **30 available files** in the two Edge campaign trees were inspected: E48 **14** (13 measured + 1 warmup), Order **16** (15 measured + 1 warmup); all record PASS, with row/admission totals checked against raw CSV. E48 measured sessions comprise ten E48 repeats plus three frozen E64 stress sessions; these are identified individually below and are not silently relabeled E48. Local K-sweep/Grid02/Confirmation02 have no schedule_fidelity.json; their actual observation fields were analyzed directly.

Producer: each Edge run_thor.run_one calls its config.validate_source_rows and saves schedule_fidelity.json after writing source_frames.csv. Schema: status, errors, source_rows, per_stream_admitted, actual_total_admitted, no_deferred_admission; E48 additionally stores actual_m_n_first_period, planned_m_n_first_period and actual_slot_histogram. These are counts/mask/logical-schedule checks. **There is no mean/p50/p95/p99/max release-lateness field in these JSON files.** no_deferred_admission means no changed *planned* Edge release target/deadline, not zero measured lateness.

Frame-level source_frames.csv supplies the missing observation statistics, including SKIP rows. Thus cross-stream observation spread can be computed; exact source queue-publication spread still cannot. E48/Order medians over all slots include SKIP-only slots and must not be interpreted as medians only over eight-request Edge bursts.

## Within-run stream bias and first-slot evidence

Local/Grid/Confirmation and E48 enumerate source IDs in increasing order: stream 0 has the earliest per-run mean observation and the last active stream the latest (K=1 is trivial). This is a measured host iteration bias, **not a logical source phase**. Order reverses or rotates submission order on admitted slots; across its 15 measured runs, the earliest mean is sid0 in ten and sid7 in five, with the latest reversed. Source due stays equal under all modes.

| Campaign | maximum within-run difference in per-stream mean lateness ms | maximum within-run difference in per-stream p95 lateness ms | first-slot observation spread range ms |
|---|---:|---:|---|
| local_finalconfig_ksweep01 | 0.073413 | 0.116834 | 0.000000–0.130695 |
| block_b_grid02 | 1.084304 | 7.689014 | 0.256223–0.742624 |
| block_b_confirmation02 | 1.251467 | 7.845422 | 0.267269–0.760975 |
| edge_e48_confirmation01 | 0.870654 | 3.059239 | 0.042732–0.959752 |
| edge_order_robustness01 | 0.666586 | 3.128802 | 0.040612–0.043038 |

FIRST_SLOT_LOGICAL_PHASE_EQUAL = **YES** for every inspected run. Each active stream begins at frame_id=0/source slot=0, with scheduled timestamp equal to manifest active_start_ns. Exact per-stream observed timestamp vectors are below. FIRST_SLOT_ACTUAL_RELEASE_SPREAD = **UNAVAILABLE for exact queue publication**; the recorded observation proxy ranges **0–0.959752 ms** over measured runs (0 only possible for single-stream K1 here).

## Cross-experiment conclusion

LOCAL_KSWEEP_SOURCE_PHASE = common_zero_offset.
GRID02_SOURCE_PHASE = common_zero_offset.
CONFIRMATION02_SOURCE_PHASE = common_zero_offset.
EDGE_PLACEMENT_SOURCE_PHASE = common_zero_offset.
CONSISTENT_COMMON_PHASE_SEMANTICS = **YES** within the inspected campaigns.

SOURCE_PHASE_SYNCHRONIZED = **YES**. Code proves the common source epoch and no per-stream offset, and all measured scheduled fields agree with the exact formula. Actual source-observation fidelity is nonzero and campaign dependent, as quantified above. Physical capture synchronization remains UNVERIFIED. No claim of simultaneous GPU execution, hardware-triggered capture, or independence of placement effects from source phases is supported.

Forward primary runtime remains C_L=3 (FORMAL_SELECTION), C_E=2 (PROSPECTIVE_CONSERVATIVE_RUNTIME_CONFIGURATION), B=1. Historical Edge formal verdict remains EDGE_C_REPEAT_AMBIGUOUS and C_E_selected=null. No experiment result is reclassified.

## Paper wording and proposed LaTeX (not applied to the paper)

**Evaluated-workload model:** All active streams in our evaluated workload share a common source phase. At each source slot, one frame from every active stream is assigned the same scheduled source timestamp. Accordingly, we use \(a_{k,n}=t_0+n/F\), with \(\theta_k=0\) for every active stream. This describes the replay schedule, not physical camera capture synchronization or simultaneous host publication, dispatch, or GPU execution.

**System model / introduction motivation:** We focus on common-phase multi-stream arrivals, a relevant operating regime for multi-view systems in which observations from different cameras are temporally aligned. [CITATION NEEDED: synchronized multi-view acquisition / hardware-triggered or clock-synchronized camera systems] This motivation is distinct from the measured fact that our replay scheduler uses a common phase. It does not claim that all multi-camera analytics require exact synchronization.

**Limitations:** With independently phased sources, frame arrivals can be naturally more dispersed, which changes the instantaneous workload pattern and may reduce the burstiness studied here. The magnitude and structure of the temporal-placement effect may therefore differ from those under the evaluated common-phase workload. Temporal concentration is not ruled out with independent phases.

Exact recommended replacement for the source-arrival-model paragraph, plus scope/limitations additions:

```latex
\paragraph{Evaluated source timing.}
We evaluate common-phase multi-stream arrivals:
\[
  a_{k,n}=t_0+\frac{n}{F},\qquad \theta_k=0\quad\forall k.
\]
At each source slot, one frame from every active stream is logically
released with the same scheduled source timestamp. The implementation
uses \(t_0+\lfloor n\,10^9/F\rfloor\) in nanoseconds.
This is a property of the replay scheduler; it does not establish
synchronized physical camera capture or simultaneous host dispatch
or GPU execution. Host-side source-observation lateness is measured
separately.

\paragraph{Scope and motivation.}
We focus on common-phase multi-stream arrivals, a relevant operating
regime for multi-view systems in which observations from different
cameras are temporally aligned.
[CITATION NEEDED: synchronized multi-view acquisition /
hardware-triggered or clock-synchronized camera systems]

\paragraph{Limitations.}
With independently phased sources, frame arrivals can be naturally
more dispersed, which changes the instantaneous workload pattern and
may reduce the burstiness studied here. The magnitude and structure
of the temporal-placement effect may therefore differ from those
under the evaluated common-phase workload.
```

## Preservation and Git scope

No Git command was executed because the task explicitly prohibits any Git command. The requested final git status and git diff --check therefore cannot be represented as executed checks. Read-only Git-index byte hashing is used instead; index SHA-256 remains b375060976d8a548d665ca1ef4b392d9417c23d060466402c42b3de4960e9c4e. Existing staging and 304 review entries remain unchanged. Whitespace checks of edited documents are reported separately, not mislabeled git diff --check.

Only allowed final-study audit/proposal and source-phase index/provenance metadata are changed. No scientific source, frozen plan, preregistration, raw measurement, existing scientific verdict, .gitignore or paper LaTeX is changed. SOURCE_SYNCHRONIZATION_AUDIT.md is the only new file. Manifest/SHA256SUMS updates are working-tree metadata changes to already indexed files and need later review/restaging; they are not new additional-source paths in the 167-command proposal.


## Detailed quantitative appendix

## Quantitative method

Rows are taken only from frozen plan run IDs. Local/Grid/Confirmation use active rows in per_frame.csv.gz; Edge uses all source_frames.csv rows, including SKIP. Warmup sessions are separate diagnostics, never measured samples. Per-frame worker warmup rows are excluded. For each expected (stream_id, frame_id) pair, check exact uniqueness, full stream universe, scheduled formula active_start_ns + frame_id*10**9//30, and admission_timestamp_ns == logical_arrival_ns. admission_observed_ns - logical_arrival_ns is scheduler observation lateness BEFORE actual queue publication; it is the available host release observation, not an exact queue-insertion timestamp. Percentiles use linear interpolation at (N-1)*p. Quantiles are recomputed from raw rows, not inferred from schedule-fidelity PASS. Pooled campaign statistics weight slots equally; K=1 has structurally zero cross-stream spread. All detail is retained per run and per stream.

## local_finalconfig_ksweep01
Canonical root: results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01. Plan SHA-256: 3378b12a1ca430925601558a1f1c413a34c6bf3fb34a76a6ce765136a44252da. Measured runs: 40; separately labeled warmup sessions: 0. All 72000 measured slots complete; logical spread mean/p50/p95/max = 0 ns; nonzero, missing, duplicate, unexpected, early-observation and formula-mismatch counts = 0.
Pooled host observation spread mean/p50/p95/p99/max (ms): 0.037168, 0.037454, 0.074797, 0.088372, 1.245155. Pooled lateness mean/p50/p95/p99/max (ms): 0.122355, 0.103485, 0.223341, 0.685991, 14.752884.
### Per-run observation fidelity

Numbers are milliseconds. Mean range and p95 range compare per-stream metrics within that run. Observation ordering is not GPU ordering.

| Run | Scope | K | slots | spread p50 | spread p95 | spread p99 | spread max | first-slot spread | mean range | p95 range | earliest mean sid | latest mean sid | strictly sid-ascending slots |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LOCALFINALKS01_K1_R1 | MEASURED | 1 | 1800 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 1800 |
| LOCALFINALKS01_K2_R1 | MEASURED | 2 | 1800 | 0.013139 | 0.037779 | 0.039158 | 0.044168 | 0.044168 | 0.018350 | 0.036964 | 0 | 1 | 1800 |
| LOCALFINALKS01_K3_R1 | MEASURED | 3 | 1800 | 0.022189 | 0.045177 | 0.047947 | 0.054445 | 0.050889 | 0.024939 | 0.044488 | 0 | 2 | 1800 |
| LOCALFINALKS01_K4_R1 | MEASURED | 4 | 1800 | 0.033797 | 0.048613 | 0.057408 | 0.069102 | 0.069102 | 0.032624 | 0.045532 | 0 | 3 | 1800 |
| LOCALFINALKS01_K5_R1 | MEASURED | 5 | 1800 | 0.038982 | 0.046113 | 0.051325 | 0.083797 | 0.083797 | 0.038455 | 0.045338 | 0 | 4 | 1800 |
| LOCALFINALKS01_K6_R1 | MEASURED | 6 | 1800 | 0.051028 | 0.064217 | 0.083511 | 0.979728 | 0.095881 | 0.053625 | 0.066504 | 0 | 5 | 1800 |
| LOCALFINALKS01_K7_R1 | MEASURED | 7 | 1800 | 0.061329 | 0.075659 | 0.082569 | 0.113862 | 0.113862 | 0.061419 | 0.073914 | 0 | 6 | 1800 |
| LOCALFINALKS01_K8_R1 | MEASURED | 8 | 1800 | 0.068844 | 0.093271 | 0.125883 | 0.543541 | 0.088148 | 0.070980 | 0.095129 | 0 | 7 | 1800 |
| LOCALFINALKS01_K8_R2 | MEASURED | 8 | 1800 | 0.067945 | 0.090142 | 0.113488 | 0.789022 | 0.103676 | 0.070062 | 0.116834 | 0 | 7 | 1800 |
| LOCALFINALKS01_K7_R2 | MEASURED | 7 | 1800 | 0.061399 | 0.075944 | 0.085274 | 0.168917 | 0.080065 | 0.061382 | 0.069464 | 0 | 6 | 1800 |
| LOCALFINALKS01_K6_R2 | MEASURED | 6 | 1800 | 0.046932 | 0.057697 | 0.064948 | 0.130695 | 0.130695 | 0.046797 | 0.058318 | 0 | 5 | 1800 |
| LOCALFINALKS01_K5_R2 | MEASURED | 5 | 1800 | 0.038842 | 0.047380 | 0.054048 | 0.088870 | 0.088870 | 0.037673 | 0.047599 | 0 | 4 | 1800 |
| LOCALFINALKS01_K4_R2 | MEASURED | 4 | 1800 | 0.033404 | 0.042742 | 0.050333 | 0.060926 | 0.060926 | 0.032171 | 0.042267 | 0 | 3 | 1800 |
| LOCALFINALKS01_K3_R2 | MEASURED | 3 | 1800 | 0.023482 | 0.045103 | 0.047649 | 0.054833 | 0.054833 | 0.024954 | 0.044197 | 0 | 2 | 1800 |
| LOCALFINALKS01_K2_R2 | MEASURED | 2 | 1800 | 0.017963 | 0.037389 | 0.038880 | 0.044279 | 0.044279 | 0.020066 | 0.036272 | 0 | 1 | 1800 |
| LOCALFINALKS01_K1_R2 | MEASURED | 1 | 1800 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 1800 |
| LOCALFINALKS01_K1_R3 | MEASURED | 1 | 1800 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 1800 |
| LOCALFINALKS01_K2_R3 | MEASURED | 2 | 1800 | 0.013024 | 0.026931 | 0.035707 | 0.048790 | 0.039150 | 0.015066 | 0.026753 | 0 | 1 | 1800 |
| LOCALFINALKS01_K3_R3 | MEASURED | 3 | 1800 | 0.017565 | 0.041950 | 0.046914 | 0.095004 | 0.057254 | 0.021861 | 0.024994 | 0 | 2 | 1800 |
| LOCALFINALKS01_K4_R3 | MEASURED | 4 | 1800 | 0.037316 | 0.048809 | 0.051890 | 0.065150 | 0.065086 | 0.037326 | 0.049970 | 0 | 3 | 1800 |
| LOCALFINALKS01_K5_R3 | MEASURED | 5 | 1800 | 0.043695 | 0.050883 | 0.053122 | 0.076624 | 0.076624 | 0.044203 | 0.049242 | 0 | 4 | 1800 |
| LOCALFINALKS01_K6_R3 | MEASURED | 6 | 1800 | 0.049243 | 0.060134 | 0.067031 | 0.085947 | 0.085947 | 0.048698 | 0.059660 | 0 | 5 | 1800 |
| LOCALFINALKS01_K7_R3 | MEASURED | 7 | 1800 | 0.062974 | 0.078458 | 0.084596 | 0.106383 | 0.106383 | 0.063051 | 0.074449 | 0 | 6 | 1800 |
| LOCALFINALKS01_K8_R3 | MEASURED | 8 | 1800 | 0.067451 | 0.091990 | 0.112899 | 0.670451 | 0.101827 | 0.069356 | 0.081520 | 0 | 7 | 1800 |
| LOCALFINALKS01_K8_R4 | MEASURED | 8 | 1800 | 0.068442 | 0.089699 | 0.104829 | 0.622533 | 0.093345 | 0.069254 | 0.082276 | 0 | 7 | 1800 |
| LOCALFINALKS01_K7_R4 | MEASURED | 7 | 1800 | 0.062788 | 0.080971 | 0.093228 | 1.245155 | 0.106993 | 0.065796 | 0.081622 | 0 | 6 | 1800 |
| LOCALFINALKS01_K6_R4 | MEASURED | 6 | 1800 | 0.047821 | 0.058780 | 0.064465 | 0.104456 | 0.076278 | 0.047254 | 0.057584 | 0 | 5 | 1800 |
| LOCALFINALKS01_K5_R4 | MEASURED | 5 | 1800 | 0.040157 | 0.049177 | 0.058038 | 0.071160 | 0.071160 | 0.039059 | 0.047703 | 0 | 4 | 1800 |
| LOCALFINALKS01_K4_R4 | MEASURED | 4 | 1800 | 0.032820 | 0.042500 | 0.048576 | 0.064511 | 0.064511 | 0.031783 | 0.042108 | 0 | 3 | 1800 |
| LOCALFINALKS01_K3_R4 | MEASURED | 3 | 1800 | 0.023163 | 0.041587 | 0.044658 | 0.067121 | 0.060871 | 0.022737 | 0.040901 | 0 | 2 | 1800 |
| LOCALFINALKS01_K2_R4 | MEASURED | 2 | 1800 | 0.012245 | 0.033177 | 0.034444 | 0.038177 | 0.036649 | 0.016955 | 0.031824 | 0 | 1 | 1800 |
| LOCALFINALKS01_K1_R4 | MEASURED | 1 | 1800 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 1800 |
| LOCALFINALKS01_K1_R5 | MEASURED | 1 | 1800 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 1800 |
| LOCALFINALKS01_K2_R5 | MEASURED | 2 | 1800 | 0.011537 | 0.027465 | 0.033240 | 0.044149 | 0.044149 | 0.014322 | 0.028147 | 0 | 1 | 1800 |
| LOCALFINALKS01_K3_R5 | MEASURED | 3 | 1800 | 0.023862 | 0.036438 | 0.044196 | 0.059362 | 0.059362 | 0.024050 | 0.036763 | 0 | 2 | 1800 |
| LOCALFINALKS01_K4_R5 | MEASURED | 4 | 1800 | 0.032532 | 0.041365 | 0.050773 | 0.080473 | 0.080473 | 0.031482 | 0.040442 | 0 | 3 | 1800 |
| LOCALFINALKS01_K5_R5 | MEASURED | 5 | 1800 | 0.043898 | 0.060436 | 0.069251 | 0.208420 | 0.102160 | 0.044827 | 0.056536 | 0 | 4 | 1800 |
| LOCALFINALKS01_K6_R5 | MEASURED | 6 | 1800 | 0.050635 | 0.065012 | 0.072489 | 0.353643 | 0.083798 | 0.050287 | 0.060611 | 0 | 5 | 1800 |
| LOCALFINALKS01_K7_R5 | MEASURED | 7 | 1800 | 0.062742 | 0.078122 | 0.086168 | 0.126316 | 0.103649 | 0.062438 | 0.071287 | 0 | 6 | 1800 |
| LOCALFINALKS01_K8_R5 | MEASURED | 8 | 1800 | 0.071964 | 0.094390 | 0.112567 | 0.716194 | 0.106205 | 0.073413 | 0.089296 | 0 | 7 | 1800 |

### Per-stream host release-observation lateness

| Run | stream_id | frames | mean ms | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| LOCALFINALKS01_K1_R1 | 0 | 1800 | 0.115335 | 0.065491 | 0.235902 | 0.241847 | 0.267605 |
| LOCALFINALKS01_K2_R1 | 0 | 1800 | 0.095814 | 0.066091 | 0.231273 | 0.240024 | 0.260092 |
| LOCALFINALKS01_K2_R1 | 1 | 1800 | 0.114165 | 0.078719 | 0.268237 | 0.277949 | 0.295530 |
| LOCALFINALKS01_K3_R1 | 0 | 1800 | 0.086310 | 0.068268 | 0.231443 | 0.243393 | 0.315023 |
| LOCALFINALKS01_K3_R1 | 1 | 1800 | 0.104092 | 0.083534 | 0.265909 | 0.278284 | 0.327365 |
| LOCALFINALKS01_K3_R1 | 2 | 1800 | 0.111250 | 0.090344 | 0.275931 | 0.288691 | 0.338032 |
| LOCALFINALKS01_K4_R1 | 0 | 1800 | 0.076618 | 0.069609 | 0.093186 | 0.234343 | 0.360387 |
| LOCALFINALKS01_K4_R1 | 1 | 1800 | 0.095656 | 0.089959 | 0.122593 | 0.272757 | 0.374091 |
| LOCALFINALKS01_K4_R1 | 2 | 1800 | 0.102671 | 0.097203 | 0.130707 | 0.282373 | 0.380841 |
| LOCALFINALKS01_K4_R1 | 3 | 1800 | 0.109242 | 0.104003 | 0.138718 | 0.289960 | 0.387905 |
| LOCALFINALKS01_K5_R1 | 0 | 1800 | 0.070747 | 0.069967 | 0.075515 | 0.093356 | 0.367958 |
| LOCALFINALKS01_K5_R1 | 1 | 1800 | 0.089744 | 0.089570 | 0.100006 | 0.115046 | 0.392902 |
| LOCALFINALKS01_K5_R1 | 2 | 1800 | 0.096671 | 0.096551 | 0.107420 | 0.124215 | 0.399662 |
| LOCALFINALKS01_K5_R1 | 3 | 1800 | 0.103112 | 0.103204 | 0.114269 | 0.132388 | 0.405958 |
| LOCALFINALKS01_K5_R1 | 4 | 1800 | 0.109202 | 0.109374 | 0.120853 | 0.139296 | 0.412013 |
| LOCALFINALKS01_K6_R1 | 0 | 1800 | 0.073779 | 0.071732 | 0.081230 | 0.131209 | 0.272634 |
| LOCALFINALKS01_K6_R1 | 1 | 1800 | 0.097523 | 0.095504 | 0.113626 | 0.169149 | 1.024072 |
| LOCALFINALKS01_K6_R1 | 2 | 1800 | 0.106735 | 0.104180 | 0.127027 | 0.195718 | 1.033257 |
| LOCALFINALKS01_K6_R1 | 3 | 1800 | 0.114735 | 0.111017 | 0.134689 | 0.231413 | 1.041322 |
| LOCALFINALKS01_K6_R1 | 4 | 1800 | 0.121079 | 0.117364 | 0.140982 | 0.238185 | 1.049295 |
| LOCALFINALKS01_K6_R1 | 5 | 1800 | 0.127404 | 0.123773 | 0.147735 | 0.245305 | 1.056535 |
| LOCALFINALKS01_K7_R1 | 0 | 1800 | 0.086418 | 0.075458 | 0.093258 | 0.388208 | 1.703316 |
| LOCALFINALKS01_K7_R1 | 1 | 1800 | 0.113101 | 0.102846 | 0.127238 | 0.419134 | 1.732038 |
| LOCALFINALKS01_K7_R1 | 2 | 1800 | 0.120990 | 0.110687 | 0.137043 | 0.426375 | 1.740964 |
| LOCALFINALKS01_K7_R1 | 3 | 1800 | 0.128213 | 0.117807 | 0.144979 | 0.432427 | 1.749270 |
| LOCALFINALKS01_K7_R1 | 4 | 1800 | 0.134956 | 0.124635 | 0.153046 | 0.438004 | 1.756677 |
| LOCALFINALKS01_K7_R1 | 5 | 1800 | 0.141526 | 0.131287 | 0.160186 | 0.443688 | 1.763686 |
| LOCALFINALKS01_K7_R1 | 6 | 1800 | 0.147837 | 0.137523 | 0.167173 | 0.449442 | 1.770205 |
| LOCALFINALKS01_K8_R1 | 0 | 1800 | 0.128057 | 0.077316 | 0.454507 | 1.176292 | 2.545212 |
| LOCALFINALKS01_K8_R1 | 1 | 1800 | 0.155599 | 0.105215 | 0.489868 | 1.210255 | 2.571481 |
| LOCALFINALKS01_K8_R1 | 2 | 1800 | 0.164325 | 0.113645 | 0.511336 | 1.220188 | 2.579731 |
| LOCALFINALKS01_K8_R1 | 3 | 1800 | 0.171752 | 0.121396 | 0.519502 | 1.227972 | 2.587120 |
| LOCALFINALKS01_K8_R1 | 4 | 1800 | 0.178959 | 0.128147 | 0.526687 | 1.235236 | 2.593694 |
| LOCALFINALKS01_K8_R1 | 5 | 1800 | 0.186147 | 0.135084 | 0.534085 | 1.241316 | 2.600814 |
| LOCALFINALKS01_K8_R1 | 6 | 1800 | 0.193009 | 0.141696 | 0.541302 | 1.246199 | 2.607574 |
| LOCALFINALKS01_K8_R1 | 7 | 1800 | 0.199036 | 0.147610 | 0.549636 | 1.251445 | 2.613351 |
| LOCALFINALKS01_K8_R2 | 0 | 1800 | 0.130926 | 0.077197 | 0.417192 | 1.167195 | 2.319747 |
| LOCALFINALKS01_K8_R2 | 1 | 1800 | 0.158452 | 0.105090 | 0.461158 | 1.191749 | 2.359682 |
| LOCALFINALKS01_K8_R2 | 2 | 1800 | 0.166638 | 0.113191 | 0.491617 | 1.199991 | 2.370229 |
| LOCALFINALKS01_K8_R2 | 3 | 1800 | 0.173968 | 0.120565 | 0.498749 | 1.221857 | 2.378747 |
| LOCALFINALKS01_K8_R2 | 4 | 1800 | 0.181263 | 0.127331 | 0.510297 | 1.228937 | 2.385812 |
| LOCALFINALKS01_K8_R2 | 5 | 1800 | 0.187953 | 0.134014 | 0.518881 | 1.236128 | 2.392165 |
| LOCALFINALKS01_K8_R2 | 6 | 1800 | 0.194728 | 0.140782 | 0.527451 | 1.242491 | 2.398443 |
| LOCALFINALKS01_K8_R2 | 7 | 1800 | 0.200988 | 0.146838 | 0.534026 | 1.248991 | 2.403804 |
| LOCALFINALKS01_K7_R2 | 0 | 1800 | 0.096499 | 0.075478 | 0.113028 | 0.708867 | 2.190066 |
| LOCALFINALKS01_K7_R2 | 1 | 1800 | 0.122771 | 0.102141 | 0.143655 | 0.748750 | 2.215066 |
| LOCALFINALKS01_K7_R2 | 2 | 1800 | 0.130873 | 0.110229 | 0.153039 | 0.760312 | 2.225094 |
| LOCALFINALKS01_K7_R2 | 3 | 1800 | 0.138004 | 0.117287 | 0.161825 | 0.768378 | 2.232576 |
| LOCALFINALKS01_K7_R2 | 4 | 1800 | 0.144860 | 0.124174 | 0.169291 | 0.776750 | 2.239631 |
| LOCALFINALKS01_K7_R2 | 5 | 1800 | 0.151484 | 0.130897 | 0.176262 | 0.785720 | 2.246039 |
| LOCALFINALKS01_K7_R2 | 6 | 1800 | 0.157880 | 0.137523 | 0.182493 | 0.794006 | 2.252742 |
| LOCALFINALKS01_K6_R2 | 0 | 1800 | 0.082293 | 0.071097 | 0.080472 | 0.222089 | 14.703569 |
| LOCALFINALKS01_K6_R2 | 1 | 1800 | 0.102773 | 0.092163 | 0.108668 | 0.252557 | 14.726958 |
| LOCALFINALKS01_K6_R2 | 2 | 1800 | 0.110029 | 0.099497 | 0.117253 | 0.262283 | 14.734181 |
| LOCALFINALKS01_K6_R2 | 3 | 1800 | 0.116674 | 0.106230 | 0.125177 | 0.270000 | 14.740727 |
| LOCALFINALKS01_K6_R2 | 4 | 1800 | 0.122915 | 0.112371 | 0.131681 | 0.277242 | 14.746551 |
| LOCALFINALKS01_K6_R2 | 5 | 1800 | 0.129090 | 0.118475 | 0.138790 | 0.284297 | 14.752884 |
| LOCALFINALKS01_K5_R2 | 0 | 1800 | 0.076455 | 0.070515 | 0.077641 | 0.223657 | 0.807665 |
| LOCALFINALKS01_K5_R2 | 1 | 1800 | 0.095044 | 0.090504 | 0.103266 | 0.252974 | 0.832591 |
| LOCALFINALKS01_K5_R2 | 2 | 1800 | 0.101833 | 0.097349 | 0.111194 | 0.261867 | 0.840091 |
| LOCALFINALKS01_K5_R2 | 3 | 1800 | 0.108139 | 0.103780 | 0.118513 | 0.270152 | 0.846860 |
| LOCALFINALKS01_K5_R2 | 4 | 1800 | 0.114129 | 0.109858 | 0.125240 | 0.276718 | 0.853147 |
| LOCALFINALKS01_K4_R2 | 0 | 1800 | 0.074949 | 0.069667 | 0.080296 | 0.227950 | 0.633458 |
| LOCALFINALKS01_K4_R2 | 1 | 1800 | 0.093540 | 0.089611 | 0.107531 | 0.260788 | 0.660098 |
| LOCALFINALKS01_K4_R2 | 2 | 1800 | 0.100660 | 0.096859 | 0.116020 | 0.270818 | 0.668617 |
| LOCALFINALKS01_K4_R2 | 3 | 1800 | 0.107120 | 0.103423 | 0.122563 | 0.277792 | 0.678015 |
| LOCALFINALKS01_K3_R2 | 0 | 1800 | 0.086674 | 0.067904 | 0.231949 | 0.248633 | 0.301854 |
| LOCALFINALKS01_K3_R2 | 1 | 1800 | 0.104614 | 0.084384 | 0.266699 | 0.282343 | 0.317382 |
| LOCALFINALKS01_K3_R2 | 2 | 1800 | 0.111628 | 0.091232 | 0.276147 | 0.291351 | 0.325132 |
| LOCALFINALKS01_K2_R2 | 0 | 1800 | 0.105125 | 0.069390 | 0.233832 | 0.245740 | 0.704031 |
| LOCALFINALKS01_K2_R2 | 1 | 1800 | 0.125192 | 0.087947 | 0.270104 | 0.282144 | 0.735864 |
| LOCALFINALKS01_K1_R2 | 0 | 1800 | 0.118378 | 0.066960 | 0.236673 | 0.243679 | 0.266468 |
| LOCALFINALKS01_K1_R3 | 0 | 1800 | 0.116245 | 0.067692 | 0.237905 | 0.248877 | 0.320113 |
| LOCALFINALKS01_K2_R3 | 0 | 1800 | 0.074330 | 0.066514 | 0.077463 | 0.416859 | 0.675753 |
| LOCALFINALKS01_K2_R3 | 1 | 1800 | 0.089397 | 0.079771 | 0.104217 | 0.441526 | 0.699032 |
| LOCALFINALKS01_K3_R3 | 0 | 1800 | 0.081648 | 0.065603 | 0.152311 | 0.257248 | 3.309115 |
| LOCALFINALKS01_K3_R3 | 1 | 1800 | 0.096937 | 0.077546 | 0.167617 | 0.290611 | 3.345663 |
| LOCALFINALKS01_K3_R3 | 2 | 1800 | 0.103509 | 0.083677 | 0.177305 | 0.299441 | 3.355608 |
| LOCALFINALKS01_K4_R3 | 0 | 1800 | 0.095192 | 0.071880 | 0.226770 | 0.806181 | 0.826633 |
| LOCALFINALKS01_K4_R3 | 1 | 1800 | 0.118244 | 0.095096 | 0.259755 | 0.826647 | 0.855903 |
| LOCALFINALKS01_K4_R3 | 2 | 1800 | 0.125593 | 0.102458 | 0.268969 | 0.833109 | 0.863403 |
| LOCALFINALKS01_K4_R3 | 3 | 1800 | 0.132518 | 0.109480 | 0.276740 | 0.840105 | 0.869774 |
| LOCALFINALKS01_K5_R3 | 0 | 1800 | 0.072517 | 0.071807 | 0.077852 | 0.082735 | 0.248517 |
| LOCALFINALKS01_K5_R3 | 1 | 1800 | 0.095777 | 0.094792 | 0.104372 | 0.111123 | 0.271185 |
| LOCALFINALKS01_K5_R3 | 2 | 1800 | 0.103325 | 0.102336 | 0.112601 | 0.119486 | 0.279380 |
| LOCALFINALKS01_K5_R3 | 3 | 1800 | 0.110154 | 0.109241 | 0.120165 | 0.126451 | 0.286704 |
| LOCALFINALKS01_K5_R3 | 4 | 1800 | 0.116721 | 0.115791 | 0.127094 | 0.133569 | 0.293185 |
| LOCALFINALKS01_K6_R3 | 0 | 1800 | 0.074660 | 0.071249 | 0.079306 | 0.119657 | 1.521409 |
| LOCALFINALKS01_K6_R3 | 1 | 1800 | 0.096695 | 0.094150 | 0.109293 | 0.140312 | 1.550882 |
| LOCALFINALKS01_K6_R3 | 2 | 1800 | 0.104066 | 0.101568 | 0.117689 | 0.146943 | 1.555725 |
| LOCALFINALKS01_K6_R3 | 3 | 1800 | 0.110933 | 0.108494 | 0.125207 | 0.154597 | 1.560567 |
| LOCALFINALKS01_K6_R3 | 4 | 1800 | 0.117117 | 0.114641 | 0.132118 | 0.161566 | 1.564678 |
| LOCALFINALKS01_K6_R3 | 5 | 1800 | 0.123358 | 0.120934 | 0.138966 | 0.168601 | 1.568800 |
| LOCALFINALKS01_K7_R3 | 0 | 1800 | 0.089336 | 0.076305 | 0.098898 | 0.391923 | 1.695738 |
| LOCALFINALKS01_K7_R3 | 1 | 1800 | 0.116525 | 0.104189 | 0.132686 | 0.439035 | 1.732980 |
| LOCALFINALKS01_K7_R3 | 2 | 1800 | 0.124830 | 0.112420 | 0.141372 | 0.449322 | 1.742035 |
| LOCALFINALKS01_K7_R3 | 3 | 1800 | 0.132138 | 0.119664 | 0.150755 | 0.458112 | 1.749822 |
| LOCALFINALKS01_K7_R3 | 4 | 1800 | 0.139222 | 0.126813 | 0.158549 | 0.467883 | 1.757729 |
| LOCALFINALKS01_K7_R3 | 5 | 1800 | 0.145916 | 0.133499 | 0.165915 | 0.476609 | 1.765655 |
| LOCALFINALKS01_K7_R3 | 6 | 1800 | 0.152387 | 0.139771 | 0.173347 | 0.485291 | 1.772277 |
| LOCALFINALKS01_K8_R3 | 0 | 1800 | 0.116570 | 0.077344 | 0.365135 | 0.849674 | 1.914101 |
| LOCALFINALKS01_K8_R3 | 1 | 1800 | 0.142851 | 0.104395 | 0.397110 | 0.924109 | 1.945574 |
| LOCALFINALKS01_K8_R3 | 2 | 1800 | 0.150909 | 0.112507 | 0.406822 | 0.933402 | 1.956315 |
| LOCALFINALKS01_K8_R3 | 3 | 1800 | 0.158164 | 0.119525 | 0.413484 | 0.941597 | 1.963676 |
| LOCALFINALKS01_K8_R3 | 4 | 1800 | 0.165322 | 0.126181 | 0.421176 | 0.948159 | 1.971333 |
| LOCALFINALKS01_K8_R3 | 5 | 1800 | 0.172328 | 0.133029 | 0.429178 | 0.954364 | 1.978733 |
| LOCALFINALKS01_K8_R3 | 6 | 1800 | 0.179635 | 0.139901 | 0.440628 | 0.960749 | 1.985131 |
| LOCALFINALKS01_K8_R3 | 7 | 1800 | 0.185926 | 0.146242 | 0.446656 | 0.966464 | 1.991010 |
| LOCALFINALKS01_K8_R4 | 0 | 1800 | 0.128773 | 0.077227 | 0.515727 | 1.028760 | 2.539719 |
| LOCALFINALKS01_K8_R4 | 1 | 1800 | 0.155863 | 0.105276 | 0.550828 | 1.069493 | 2.566535 |
| LOCALFINALKS01_K8_R4 | 2 | 1800 | 0.163700 | 0.113133 | 0.559758 | 1.078275 | 2.574386 |
| LOCALFINALKS01_K8_R4 | 3 | 1800 | 0.171211 | 0.120429 | 0.570441 | 1.085298 | 2.582136 |
| LOCALFINALKS01_K8_R4 | 4 | 1800 | 0.178100 | 0.127312 | 0.576903 | 1.091009 | 2.589692 |
| LOCALFINALKS01_K8_R4 | 5 | 1800 | 0.184851 | 0.134009 | 0.583844 | 1.096504 | 2.595988 |
| LOCALFINALKS01_K8_R4 | 6 | 1800 | 0.191769 | 0.140846 | 0.591328 | 1.103244 | 2.603498 |
| LOCALFINALKS01_K8_R4 | 7 | 1800 | 0.198027 | 0.147004 | 0.598003 | 1.108792 | 2.609749 |
| LOCALFINALKS01_K7_R4 | 0 | 1800 | 0.085921 | 0.075791 | 0.093536 | 0.445306 | 1.467334 |
| LOCALFINALKS01_K7_R4 | 1 | 1800 | 0.114626 | 0.104435 | 0.131659 | 0.555611 | 1.501400 |
| LOCALFINALKS01_K7_R4 | 2 | 1800 | 0.122984 | 0.112570 | 0.141941 | 0.566144 | 1.510474 |
| LOCALFINALKS01_K7_R4 | 3 | 1800 | 0.131958 | 0.119651 | 0.151511 | 0.639723 | 1.518420 |
| LOCALFINALKS01_K7_R4 | 4 | 1800 | 0.138754 | 0.126444 | 0.159284 | 0.646844 | 1.525197 |
| LOCALFINALKS01_K7_R4 | 5 | 1800 | 0.145221 | 0.132754 | 0.168613 | 0.654706 | 1.533012 |
| LOCALFINALKS01_K7_R4 | 6 | 1800 | 0.151717 | 0.139238 | 0.175157 | 0.662695 | 1.540151 |
| LOCALFINALKS01_K6_R4 | 0 | 1800 | 0.080757 | 0.071328 | 0.087912 | 0.511143 | 0.719966 |
| LOCALFINALKS01_K6_R4 | 1 | 1800 | 0.101801 | 0.093172 | 0.116778 | 0.529568 | 0.745123 |
| LOCALFINALKS01_K6_R4 | 2 | 1800 | 0.108938 | 0.100368 | 0.125085 | 0.536064 | 0.753734 |
| LOCALFINALKS01_K6_R4 | 3 | 1800 | 0.115669 | 0.107130 | 0.131755 | 0.542785 | 0.760309 |
| LOCALFINALKS01_K6_R4 | 4 | 1800 | 0.121852 | 0.113416 | 0.138910 | 0.548761 | 0.766754 |
| LOCALFINALKS01_K6_R4 | 5 | 1800 | 0.128011 | 0.119634 | 0.145496 | 0.554985 | 0.773680 |
| LOCALFINALKS01_K5_R4 | 0 | 1800 | 0.071844 | 0.069928 | 0.076851 | 0.214045 | 0.288734 |
| LOCALFINALKS01_K5_R4 | 1 | 1800 | 0.091311 | 0.090730 | 0.102498 | 0.247935 | 0.304096 |
| LOCALFINALKS01_K5_R4 | 2 | 1800 | 0.098274 | 0.097795 | 0.110339 | 0.256769 | 0.310096 |
| LOCALFINALKS01_K5_R4 | 3 | 1800 | 0.104722 | 0.104363 | 0.117750 | 0.264602 | 0.318299 |
| LOCALFINALKS01_K5_R4 | 4 | 1800 | 0.110904 | 0.110606 | 0.124554 | 0.272205 | 0.324725 |
| LOCALFINALKS01_K4_R4 | 0 | 1800 | 0.085035 | 0.069413 | 0.099192 | 0.644950 | 0.789910 |
| LOCALFINALKS01_K4_R4 | 1 | 1800 | 0.103594 | 0.089446 | 0.124698 | 0.660136 | 0.806911 |
| LOCALFINALKS01_K4_R4 | 2 | 1800 | 0.110495 | 0.096376 | 0.133683 | 0.667392 | 0.814818 |
| LOCALFINALKS01_K4_R4 | 3 | 1800 | 0.116818 | 0.102627 | 0.141300 | 0.672064 | 0.822300 |
| LOCALFINALKS01_K3_R4 | 0 | 1800 | 0.079004 | 0.066877 | 0.210394 | 0.242367 | 0.701988 |
| LOCALFINALKS01_K3_R4 | 1 | 1800 | 0.095251 | 0.083934 | 0.242937 | 0.274807 | 0.714951 |
| LOCALFINALKS01_K3_R4 | 2 | 1800 | 0.101740 | 0.090704 | 0.251295 | 0.284173 | 0.720831 |
| LOCALFINALKS01_K2_R4 | 0 | 1800 | 0.107653 | 0.065656 | 0.224241 | 0.620958 | 0.688482 |
| LOCALFINALKS01_K2_R4 | 1 | 1800 | 0.124609 | 0.077534 | 0.256066 | 0.631442 | 0.710103 |
| LOCALFINALKS01_K1_R4 | 0 | 1800 | 0.112286 | 0.065764 | 0.228851 | 0.250874 | 0.368818 |
| LOCALFINALKS01_K1_R5 | 0 | 1800 | 0.090900 | 0.067399 | 0.229652 | 0.247341 | 0.256907 |
| LOCALFINALKS01_K2_R5 | 0 | 1800 | 0.069762 | 0.064747 | 0.077711 | 0.224451 | 0.635635 |
| LOCALFINALKS01_K2_R5 | 1 | 1800 | 0.084084 | 0.075893 | 0.105858 | 0.257867 | 0.660866 |
| LOCALFINALKS01_K3_R5 | 0 | 1800 | 0.074786 | 0.067807 | 0.081777 | 0.235122 | 0.528888 |
| LOCALFINALKS01_K3_R5 | 1 | 1800 | 0.092057 | 0.085346 | 0.109779 | 0.270239 | 0.550037 |
| LOCALFINALKS01_K3_R5 | 2 | 1800 | 0.098836 | 0.091886 | 0.118540 | 0.279634 | 0.557713 |
| LOCALFINALKS01_K4_R5 | 0 | 1800 | 0.071790 | 0.069639 | 0.078836 | 0.216503 | 0.410380 |
| LOCALFINALKS01_K4_R5 | 1 | 1800 | 0.089928 | 0.089083 | 0.103210 | 0.247908 | 0.427936 |
| LOCALFINALKS01_K4_R5 | 2 | 1800 | 0.096878 | 0.095992 | 0.112130 | 0.257481 | 0.434269 |
| LOCALFINALKS01_K4_R5 | 3 | 1800 | 0.103272 | 0.102257 | 0.119278 | 0.264628 | 0.440616 |
| LOCALFINALKS01_K5_R5 | 0 | 1800 | 0.076005 | 0.070952 | 0.089473 | 0.228001 | 0.763437 |
| LOCALFINALKS01_K5_R5 | 1 | 1800 | 0.099243 | 0.094247 | 0.120136 | 0.261746 | 0.788030 |
| LOCALFINALKS01_K5_R5 | 2 | 1800 | 0.106900 | 0.101661 | 0.129430 | 0.271181 | 0.795151 |
| LOCALFINALKS01_K5_R5 | 3 | 1800 | 0.114098 | 0.108689 | 0.138273 | 0.278762 | 0.802364 |
| LOCALFINALKS01_K5_R5 | 4 | 1800 | 0.120832 | 0.115449 | 0.146008 | 0.286130 | 0.809169 |
| LOCALFINALKS01_K6_R5 | 0 | 1800 | 0.083550 | 0.071543 | 0.089771 | 0.229981 | 11.540335 |
| LOCALFINALKS01_K6_R5 | 1 | 1800 | 0.106522 | 0.095308 | 0.119529 | 0.263224 | 11.557012 |
| LOCALFINALKS01_K6_R5 | 2 | 1800 | 0.113885 | 0.102693 | 0.128223 | 0.272243 | 11.565346 |
| LOCALFINALKS01_K6_R5 | 3 | 1800 | 0.120906 | 0.109654 | 0.136166 | 0.280771 | 11.571735 |
| LOCALFINALKS01_K6_R5 | 4 | 1800 | 0.127425 | 0.116427 | 0.143471 | 0.288377 | 11.577522 |
| LOCALFINALKS01_K6_R5 | 5 | 1800 | 0.133837 | 0.122793 | 0.150383 | 0.295518 | 11.583651 |
| LOCALFINALKS01_K7_R5 | 0 | 1800 | 0.089263 | 0.075934 | 0.105571 | 0.599317 | 1.649398 |
| LOCALFINALKS01_K7_R5 | 1 | 1800 | 0.115937 | 0.103407 | 0.135213 | 0.631572 | 1.678028 |
| LOCALFINALKS01_K7_R5 | 2 | 1800 | 0.124124 | 0.111630 | 0.145310 | 0.641262 | 1.686037 |
| LOCALFINALKS01_K7_R5 | 3 | 1800 | 0.131321 | 0.118925 | 0.154386 | 0.650392 | 1.692566 |
| LOCALFINALKS01_K7_R5 | 4 | 1800 | 0.138323 | 0.125844 | 0.162558 | 0.658576 | 1.700131 |
| LOCALFINALKS01_K7_R5 | 5 | 1800 | 0.144904 | 0.132491 | 0.169535 | 0.666556 | 1.707455 |
| LOCALFINALKS01_K7_R5 | 6 | 1800 | 0.151700 | 0.139333 | 0.176858 | 0.675275 | 1.716409 |
| LOCALFINALKS01_K8_R5 | 0 | 1800 | 0.128218 | 0.078504 | 0.431666 | 1.097682 | 2.585354 |
| LOCALFINALKS01_K8_R5 | 1 | 1800 | 0.156865 | 0.107991 | 0.466160 | 1.132678 | 2.613613 |
| LOCALFINALKS01_K8_R5 | 2 | 1800 | 0.165583 | 0.116579 | 0.476740 | 1.142450 | 2.621687 |
| LOCALFINALKS01_K8_R5 | 3 | 1800 | 0.173579 | 0.124728 | 0.484284 | 1.150302 | 2.628882 |
| LOCALFINALKS01_K8_R5 | 4 | 1800 | 0.181201 | 0.131993 | 0.498173 | 1.157138 | 2.635373 |
| LOCALFINALKS01_K8_R5 | 5 | 1800 | 0.188911 | 0.139155 | 0.508011 | 1.163393 | 2.642873 |
| LOCALFINALKS01_K8_R5 | 6 | 1800 | 0.195484 | 0.145573 | 0.514408 | 1.171561 | 2.650114 |
| LOCALFINALKS01_K8_R5 | 7 | 1800 | 0.201631 | 0.151763 | 0.520961 | 1.178161 | 2.664596 |

### Initial source slot: exact timestamps

Each vector is in stream ID order 0..K-1; every stream has frame_id=0, logical source_slot=0, scheduled timestamp equal to the common t0. The observed vector is the pre-publication scheduler observation, not exact queue insertion. Warmups remain labeled above.

| Run | common scheduled t0 (ns) | admission_observed_ns vector |
|---|---:|---|
| LOCALFINALKS01_K1_R1 | 99238638260944 | [99238638356689] |
| LOCALFINALKS01_K2_R1 | 99312483616369 | [99312483848085, 99312483892253] |
| LOCALFINALKS01_K3_R1 | 99386734274253 | [99386734381603, 99386734419974, 99386734432492] |
| LOCALFINALKS01_K4_R1 | 99461865087776 | [99461865184233, 99461865229659, 99461865243298, 99461865253335] |
| LOCALFINALKS01_K5_R1 | 99537391643790 | [99537391737142, 99537391787420, 99537391802050, 99537391812670, 99537391820939] |
| LOCALFINALKS01_K6_R1 | 99613467906811 | [99613468038015, 99613468086766, 99613468101368, 99613468117979, 99613468126109, 99613468133896] |
| LOCALFINALKS01_K7_R1 | 99690296769417 | [99690296865185, 99690296929862, 99690296947186, 99690296956686, 99690296964492, 99690296971927, 99690296979047] |
| LOCALFINALKS01_K8_R1 | 99767848072915 | [99767848147724, 99767848186631, 99767848199566, 99767848208641, 99767848215807, 99767848223492, 99767848230159, 99767848235872] |
| LOCALFINALKS01_K8_R2 | 99847927050336 | [99847927139458, 99847927187810, 99847927201523, 99847927212782, 99847927220477, 99847927228958, 99847927235717, 99847927243134] |
| LOCALFINALKS01_K7_R2 | 99927764501741 | [99927764585437, 99927764622771, 99927764635410, 99927764644271, 99927764651576, 99927764658863, 99927764665502] |
| LOCALFINALKS01_K6_R2 | 100005471277412 | [100005471408232, 100005471480019, 100005471500482, 100005471516066, 100005471528121, 100005471538927] |
| LOCALFINALKS01_K5_R2 | 100082314679681 | [100082314770860, 100082314825554, 100082314840239, 100082314851156, 100082314859730] |
| LOCALFINALKS01_K4_R2 | 100158564175026 | [100158564262144, 100158564301218, 100158564314616, 100158564323070] |
| LOCALFINALKS01_K3_R2 | 100234093869784 | [100234093949173, 100234093991506, 100234094004006] |
| LOCALFINALKS01_K2_R2 | 100309024231458 | [100309024321864, 100309024366143] |
| LOCALFINALKS01_K1_R2 | 100383307971328 | [100383308192953] |
| LOCALFINALKS01_K1_R3 | 100456956779981 | [100456957019338] |
| LOCALFINALKS01_K2_R3 | 100530613631335 | [100530613707143, 100530613746293] |
| LOCALFINALKS01_K3_R3 | 100604913931430 | [100604914008466, 100604914052126, 100604914065720] |
| LOCALFINALKS01_K4_R3 | 100680058615192 | [100680058700040, 100680058745384, 100680058757376, 100680058765126] |
| LOCALFINALKS01_K5_R3 | 100755616923491 | [100755617012567, 100755617058170, 100755617072208, 100755617081310, 100755617089191] |
| LOCALFINALKS01_K6_R3 | 100832252729478 | [100832252804830, 100832252851247, 100832252865387, 100832252875248, 100832252883008, 100832252890777] |
| LOCALFINALKS01_K7_R3 | 100909086349508 | [100909086445919, 100909086502940, 100909086516986, 100909086527061, 100909086535858, 100909086545228, 100909086552302] |
| LOCALFINALKS01_K8_R3 | 100986919286640 | [100986919360384, 100986919406099, 100986919420182, 100986919430256, 100986919438969, 100986919447980, 100986919455813, 100986919462211] |
| LOCALFINALKS01_K8_R4 | 101066968127337 | [101066968224787, 101066968267946, 101066968281066, 101066968289863, 101066968297400, 101066968304946, 101066968311984, 101066968318132] |
| LOCALFINALKS01_K7_R4 | 101147317239309 | [101147317329273, 101147317380691, 101147317396737, 101147317408506, 101147317418006, 101147317427822, 101147317436266] |
| LOCALFINALKS01_K6_R4 | 101224862908775 | [101224862992151, 101224863033281, 101224863045494, 101224863054457, 101224863061327, 101224863068429] |
| LOCALFINALKS01_K5_R4 | 101301710337606 | [101301710424508, 101301710466556, 101301710479806, 101301710488492, 101301710495668] |
| LOCALFINALKS01_K4_R4 | 101377896103956 | [101377896195874, 101377896238227, 101377896251588, 101377896260385] |
| LOCALFINALKS01_K3_R4 | 101453400093397 | [101453400171115, 101453400219060, 101453400231986] |
| LOCALFINALKS01_K2_R4 | 101528641451510 | [101528641523603, 101528641560252] |
| LOCALFINALKS01_K1_R4 | 101603222169108 | [101603222453366] |
| LOCALFINALKS01_K1_R5 | 101677134082886 | [101677134174365] |
| LOCALFINALKS01_K2_R5 | 101751107465088 | [101751107552062, 101751107596211] |
| LOCALFINALKS01_K3_R5 | 101825670963963 | [101825671057587, 101825671102874, 101825671116949] |
| LOCALFINALKS01_K4_R5 | 101900555016282 | [101900555103714, 101900555161474, 101900555175270, 101900555184187] |
| LOCALFINALKS01_K5_R5 | 101976062029434 | [101976062118455, 101976062187030, 101976062202549, 101976062212707, 101976062220615] |
| LOCALFINALKS01_K6_R5 | 102052218617699 | [102052218715355, 102052218763096, 102052218775874, 102052218784467, 102052218791579, 102052218799153] |
| LOCALFINALKS01_K7_R5 | 102128998056568 | [102128998150756, 102128998203543, 102128998218145, 102128998228414, 102128998237526, 102128998246239, 102128998254405] |
| LOCALFINALKS01_K8_R5 | 102206588270909 | [102206588359542, 102206588408061, 102206588422599, 102206588432821, 102206588441876, 102206588450904, 102206588458580, 102206588465747] |

### Exact inspected files

| Run | raw frame artifact | manifest | schedule fidelity |
|---|---|---|---|
| LOCALFINALKS01_K1_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K2_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K3_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K4_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K5_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K6_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K7_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K8_R1 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K8_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K7_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K6_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K5_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K4_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K3_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K2_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K1_R2 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K1_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K2_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K3_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K4_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K5_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K6_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K7_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K8_R3 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K8_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K7_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K6_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K5_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K4_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K3_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K2_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K1_R4 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K1_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K2_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K3_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K4_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K5_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K6_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K7_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/manifest.json | UNAVAILABLE: no file produced by this path |
| LOCALFINALKS01_K8_R5 | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/manifest.json | UNAVAILABLE: no file produced by this path |

## block_b_grid02
Canonical root: results/timely_capacity_campaign/v2_2/block_b_grid02. Plan SHA-256: ecc6cfc219572ae2754ae3f9f3d8c7e9bcdfed0274c18a951bf459d71a66abe3. Measured runs: 30; separately labeled warmup sessions: 1. All 54000 measured slots complete; logical spread mean/p50/p95/max = 0 ns; nonzero, missing, duplicate, unexpected, early-observation and formula-mismatch counts = 0.
Pooled host observation spread mean/p50/p95/p99/max (ms): 0.829494, 0.203363, 2.753825, 9.294107, 14.040988. Pooled lateness mean/p50/p95/p99/max (ms): 0.530644, 0.178810, 1.677558, 5.259323, 14.126269.
### Per-run observation fidelity

Numbers are milliseconds. Mean range and p95 range compare per-stream metrics within that run. Observation ordering is not GPU ordering.

| Run | Scope | K | slots | spread p50 | spread p95 | spread p99 | spread max | first-slot spread | mean range | p95 range | earliest mean sid | latest mean sid | strictly sid-ascending slots |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BLOCKB02_WARMUP_L200_E40_S | WARMUP diagnostic | 8 | 450 | 1.004075 | 2.128408 | 2.771289 | 2.786099 | 0.373150 | 1.071091 | 2.088440 | 0 | 7 | 450 |
| BLOCKB02_L216_A1 | MEASURED | 8 | 1800 | 0.134511 | 4.331008 | 8.981346 | 12.722396 | 0.648401 | 0.583014 | 4.174542 | 0 | 7 | 1800 |
| BLOCKB02_L216_S1 | MEASURED | 8 | 1800 | 0.493160 | 1.528581 | 1.617839 | 2.070530 | 0.270945 | 0.665941 | 1.397342 | 0 | 7 | 1800 |
| BLOCKB02_L208_S1 | MEASURED | 8 | 1800 | 0.850333 | 1.626383 | 1.688167 | 2.600533 | 0.284845 | 0.886967 | 1.593767 | 0 | 7 | 1800 |
| BLOCKB02_L208_A1 | MEASURED | 8 | 1800 | 0.129778 | 6.477987 | 9.370068 | 12.657468 | 0.742624 | 0.773983 | 6.269153 | 0 | 7 | 1800 |
| BLOCKB02_L200_A1 | MEASURED | 8 | 1800 | 0.131588 | 7.767033 | 10.213239 | 12.854589 | 0.645429 | 0.983376 | 7.689014 | 0 | 7 | 1800 |
| BLOCKB02_L200_S1 | MEASURED | 8 | 1800 | 1.002292 | 2.139262 | 2.765029 | 2.894572 | 0.346530 | 1.072822 | 2.123616 | 0 | 7 | 1800 |
| BLOCKB02_L208_A2 | MEASURED | 8 | 1800 | 0.134316 | 6.783622 | 9.788884 | 13.316276 | 0.669125 | 0.794388 | 6.725069 | 0 | 7 | 1800 |
| BLOCKB02_L208_S2 | MEASURED | 8 | 1800 | 0.852275 | 1.622431 | 1.722924 | 2.506841 | 0.256223 | 0.889399 | 1.228635 | 0 | 7 | 1800 |
| BLOCKB02_L200_A2 | MEASURED | 8 | 1800 | 0.129167 | 7.721090 | 9.968144 | 12.319878 | 0.643257 | 0.972051 | 7.642584 | 0 | 7 | 1800 |
| BLOCKB02_L200_S2 | MEASURED | 8 | 1800 | 0.998417 | 2.133434 | 2.769119 | 3.178121 | 0.343169 | 1.072930 | 2.113890 | 0 | 7 | 1800 |
| BLOCKB02_L216_S2 | MEASURED | 8 | 1800 | 0.488870 | 1.527573 | 1.603921 | 2.556384 | 0.275039 | 0.666233 | 1.406370 | 0 | 7 | 1800 |
| BLOCKB02_L216_A2 | MEASURED | 8 | 1800 | 0.134520 | 4.253280 | 9.188601 | 12.536262 | 0.637413 | 0.578950 | 3.887677 | 0 | 7 | 1800 |
| BLOCKB02_L200_S3 | MEASURED | 8 | 1800 | 1.029291 | 2.147277 | 2.780989 | 2.988524 | 0.369189 | 1.084304 | 2.129599 | 0 | 7 | 1800 |
| BLOCKB02_L200_A3 | MEASURED | 8 | 1800 | 0.132788 | 7.511462 | 10.245558 | 12.600513 | 0.664245 | 0.983253 | 7.437228 | 0 | 7 | 1800 |
| BLOCKB02_L216_S3 | MEASURED | 8 | 1800 | 0.486990 | 1.512712 | 1.583430 | 2.742900 | 0.286030 | 0.659785 | 1.452088 | 0 | 7 | 1800 |
| BLOCKB02_L216_A3 | MEASURED | 8 | 1800 | 0.135103 | 4.248747 | 8.669096 | 14.040988 | 0.659089 | 0.572046 | 4.079755 | 0 | 7 | 1800 |
| BLOCKB02_L208_A3 | MEASURED | 8 | 1800 | 0.130182 | 6.796223 | 9.656116 | 13.637936 | 0.652338 | 0.790798 | 6.445714 | 0 | 7 | 1800 |
| BLOCKB02_L208_S3 | MEASURED | 8 | 1800 | 0.846881 | 1.618554 | 1.674365 | 2.425656 | 0.327271 | 0.880409 | 1.412026 | 0 | 7 | 1800 |
| BLOCKB02_L216_A4 | MEASURED | 8 | 1800 | 0.132950 | 4.263586 | 8.352744 | 13.073031 | 0.677255 | 0.568482 | 4.085888 | 0 | 7 | 1800 |
| BLOCKB02_L216_S4 | MEASURED | 8 | 1800 | 0.490730 | 1.530878 | 1.606475 | 2.478711 | 0.291724 | 0.668869 | 1.482951 | 0 | 7 | 1800 |
| BLOCKB02_L200_S4 | MEASURED | 8 | 1800 | 1.020622 | 2.131240 | 2.754754 | 2.804898 | 0.329770 | 1.073588 | 2.062648 | 0 | 7 | 1800 |
| BLOCKB02_L200_A4 | MEASURED | 8 | 1800 | 0.132876 | 7.427793 | 10.322453 | 11.470591 | 0.641041 | 0.979282 | 7.280594 | 0 | 7 | 1800 |
| BLOCKB02_L208_S4 | MEASURED | 8 | 1800 | 0.861289 | 1.623766 | 1.698976 | 2.480932 | 0.285243 | 0.889089 | 1.591533 | 0 | 7 | 1800 |
| BLOCKB02_L208_A4 | MEASURED | 8 | 1800 | 0.131283 | 6.368543 | 9.581820 | 13.257119 | 0.636828 | 0.784589 | 6.135467 | 0 | 7 | 1800 |
| BLOCKB02_L208_S5 | MEASURED | 8 | 1800 | 0.858645 | 1.625416 | 1.681644 | 2.064346 | 0.270501 | 0.882229 | 1.596035 | 0 | 7 | 1800 |
| BLOCKB02_L208_A5 | MEASURED | 8 | 1800 | 0.131825 | 6.646437 | 9.548147 | 13.937827 | 0.664032 | 0.785729 | 6.216772 | 0 | 7 | 1800 |
| BLOCKB02_L216_A5 | MEASURED | 8 | 1800 | 0.133825 | 4.255327 | 8.989795 | 12.350917 | 0.641587 | 0.572855 | 3.704813 | 0 | 7 | 1800 |
| BLOCKB02_L216_S5 | MEASURED | 8 | 1800 | 0.509586 | 1.584225 | 1.781185 | 2.749202 | 0.382455 | 0.688508 | 1.493378 | 0 | 7 | 1800 |
| BLOCKB02_L200_A5 | MEASURED | 8 | 1800 | 0.133852 | 7.947577 | 10.598253 | 13.871815 | 0.677874 | 1.003696 | 7.413567 | 0 | 7 | 1800 |
| BLOCKB02_L200_S5 | MEASURED | 8 | 1800 | 1.014988 | 2.131251 | 2.764958 | 3.047065 | 0.710819 | 1.077255 | 2.102543 | 0 | 7 | 1800 |

### Per-stream host release-observation lateness

| Run | stream_id | frames | mean ms | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| BLOCKB02_WARMUP_L200_E40_S | 0 | 450 | 0.085628 | 0.075693 | 0.117829 | 0.269258 | 1.358638 |
| BLOCKB02_WARMUP_L200_E40_S | 1 | 450 | 0.248675 | 0.127116 | 1.130527 | 1.464057 | 1.505359 |
| BLOCKB02_WARMUP_L200_E40_S | 2 | 450 | 0.388032 | 0.148413 | 1.463943 | 1.523201 | 1.624653 |
| BLOCKB02_WARMUP_L200_E40_S | 3 | 450 | 0.534875 | 0.224254 | 1.534996 | 1.603506 | 2.555997 |
| BLOCKB02_WARMUP_L200_E40_S | 4 | 450 | 0.694664 | 0.579904 | 1.603791 | 1.700245 | 2.569312 |
| BLOCKB02_WARMUP_L200_E40_S | 5 | 450 | 0.857576 | 0.863484 | 1.667090 | 1.789058 | 2.581840 |
| BLOCKB02_WARMUP_L200_E40_S | 6 | 450 | 1.029533 | 1.039579 | 1.731984 | 1.828420 | 2.593895 |
| BLOCKB02_WARMUP_L200_E40_S | 7 | 450 | 1.156719 | 1.090625 | 2.206269 | 2.855628 | 2.898488 |
| BLOCKB02_L216_A1 | 0 | 1800 | 0.121363 | 0.075867 | 0.233758 | 1.431050 | 2.780358 |
| BLOCKB02_L216_A1 | 1 | 1800 | 0.231856 | 0.129709 | 1.225120 | 1.492739 | 2.981538 |
| BLOCKB02_L216_A1 | 2 | 1800 | 0.308647 | 0.145565 | 1.372925 | 2.439270 | 3.800626 |
| BLOCKB02_L216_A1 | 3 | 1800 | 0.382334 | 0.159626 | 1.965355 | 3.586601 | 4.946485 |
| BLOCKB02_L216_A1 | 4 | 1800 | 0.456237 | 0.173357 | 2.571552 | 4.732224 | 6.763720 |
| BLOCKB02_L216_A1 | 5 | 1800 | 0.538327 | 0.186625 | 3.188293 | 6.238912 | 8.484060 |
| BLOCKB02_L216_A1 | 6 | 1800 | 0.630928 | 0.199920 | 3.798068 | 7.974155 | 11.640576 |
| BLOCKB02_L216_A1 | 7 | 1800 | 0.704377 | 0.213049 | 4.408299 | 9.124376 | 12.798221 |
| BLOCKB02_L216_S1 | 0 | 1800 | 0.119143 | 0.076055 | 0.248400 | 1.376111 | 2.708473 |
| BLOCKB02_L216_S1 | 1 | 1800 | 0.229054 | 0.128333 | 1.180840 | 1.450961 | 2.755297 |
| BLOCKB02_L216_S1 | 2 | 1800 | 0.310223 | 0.146979 | 1.284492 | 1.479318 | 2.770158 |
| BLOCKB02_L216_S1 | 3 | 1800 | 0.395252 | 0.166604 | 1.357613 | 1.560762 | 3.213634 |
| BLOCKB02_L216_S1 | 4 | 1800 | 0.484953 | 0.189132 | 1.447392 | 1.633795 | 3.227726 |
| BLOCKB02_L216_S1 | 5 | 1800 | 0.579733 | 0.274810 | 1.505188 | 1.861389 | 3.240485 |
| BLOCKB02_L216_S1 | 6 | 1800 | 0.679588 | 0.433631 | 1.581460 | 1.939032 | 3.253161 |
| BLOCKB02_L216_S1 | 7 | 1800 | 0.785085 | 0.600325 | 1.645742 | 2.083431 | 3.265606 |
| BLOCKB02_L208_S1 | 0 | 1800 | 0.089518 | 0.075969 | 0.114729 | 0.313910 | 1.631078 |
| BLOCKB02_L208_S1 | 1 | 1800 | 0.223467 | 0.127731 | 0.987635 | 1.365126 | 1.862960 |
| BLOCKB02_L208_S1 | 2 | 1800 | 0.333387 | 0.147230 | 1.371330 | 1.434606 | 2.610319 |
| BLOCKB02_L208_S1 | 3 | 1800 | 0.447939 | 0.169913 | 1.431079 | 1.501796 | 2.625116 |
| BLOCKB02_L208_S1 | 4 | 1800 | 0.569620 | 0.289868 | 1.499425 | 1.596575 | 2.639163 |
| BLOCKB02_L208_S1 | 5 | 1800 | 0.698636 | 0.603542 | 1.571243 | 1.667577 | 2.652728 |
| BLOCKB02_L208_S1 | 6 | 1800 | 0.832892 | 0.787796 | 1.633837 | 1.715867 | 2.665700 |
| BLOCKB02_L208_S1 | 7 | 1800 | 0.976484 | 0.957366 | 1.708497 | 1.939832 | 2.678330 |
| BLOCKB02_L208_A1 | 0 | 1800 | 0.128430 | 0.076256 | 0.516963 | 1.265823 | 2.063124 |
| BLOCKB02_L208_A1 | 1 | 1800 | 0.261108 | 0.126655 | 1.160557 | 1.549155 | 2.567029 |
| BLOCKB02_L208_A1 | 2 | 1800 | 0.362650 | 0.142309 | 1.853702 | 2.601585 | 3.796749 |
| BLOCKB02_L208_A1 | 3 | 1800 | 0.461615 | 0.155853 | 2.709875 | 3.827673 | 5.027413 |
| BLOCKB02_L208_A1 | 4 | 1800 | 0.560175 | 0.169355 | 3.569988 | 5.057948 | 6.251272 |
| BLOCKB02_L208_A1 | 5 | 1800 | 0.667612 | 0.182466 | 4.430358 | 6.758429 | 8.122330 |
| BLOCKB02_L208_A1 | 6 | 1800 | 0.781438 | 0.195531 | 5.295747 | 8.273377 | 11.808773 |
| BLOCKB02_L208_A1 | 7 | 1800 | 0.902413 | 0.208432 | 6.786116 | 9.533291 | 12.888735 |
| BLOCKB02_L200_A1 | 0 | 1800 | 0.114538 | 0.075968 | 0.258395 | 0.924070 | 2.332055 |
| BLOCKB02_L200_A1 | 1 | 1800 | 0.279588 | 0.127583 | 1.189514 | 1.849244 | 2.383120 |
| BLOCKB02_L200_A1 | 2 | 1800 | 0.409470 | 0.142842 | 2.155939 | 2.787405 | 3.604398 |
| BLOCKB02_L200_A1 | 3 | 1800 | 0.537358 | 0.156923 | 3.162398 | 4.102948 | 4.926395 |
| BLOCKB02_L200_A1 | 4 | 1800 | 0.668674 | 0.170189 | 4.170229 | 5.458584 | 6.998851 |
| BLOCKB02_L200_A1 | 5 | 1800 | 0.812709 | 0.183402 | 5.187698 | 7.515799 | 9.183118 |
| BLOCKB02_L200_A1 | 6 | 1800 | 0.956604 | 0.196643 | 6.488051 | 8.983146 | 10.502949 |
| BLOCKB02_L200_A1 | 7 | 1800 | 1.097914 | 0.210111 | 7.947410 | 10.307438 | 12.929871 |
| BLOCKB02_L200_S1 | 0 | 1800 | 0.088458 | 0.076893 | 0.104428 | 0.334436 | 1.438451 |
| BLOCKB02_L200_S1 | 1 | 1800 | 0.253184 | 0.130960 | 1.143875 | 1.456112 | 2.257669 |
| BLOCKB02_L200_S1 | 2 | 1800 | 0.393312 | 0.153050 | 1.463128 | 1.523279 | 2.273632 |
| BLOCKB02_L200_S1 | 3 | 1800 | 0.541341 | 0.228386 | 1.532258 | 1.602284 | 2.471860 |
| BLOCKB02_L200_S1 | 4 | 1800 | 0.697145 | 0.589671 | 1.605801 | 1.673579 | 2.485239 |
| BLOCKB02_L200_S1 | 5 | 1800 | 0.860813 | 0.860237 | 1.669022 | 1.734384 | 2.498443 |
| BLOCKB02_L200_S1 | 6 | 1800 | 1.034115 | 1.036719 | 1.731108 | 1.850109 | 2.674861 |
| BLOCKB02_L200_S1 | 7 | 1800 | 1.161280 | 1.095751 | 2.228043 | 2.846361 | 3.649557 |
| BLOCKB02_L208_A2 | 0 | 1800 | 0.119650 | 0.075673 | 0.232335 | 1.447983 | 2.698292 |
| BLOCKB02_L208_A2 | 1 | 1800 | 0.253203 | 0.127780 | 1.099362 | 1.520214 | 3.217305 |
| BLOCKB02_L208_A2 | 2 | 1800 | 0.354045 | 0.143750 | 1.856384 | 2.589214 | 4.077644 |
| BLOCKB02_L208_A2 | 3 | 1800 | 0.452845 | 0.157919 | 2.711032 | 3.814652 | 4.934602 |
| BLOCKB02_L208_A2 | 4 | 1800 | 0.551679 | 0.171666 | 3.568612 | 5.047045 | 5.797495 |
| BLOCKB02_L208_A2 | 5 | 1800 | 0.671163 | 0.186448 | 4.427809 | 6.980645 | 10.925120 |
| BLOCKB02_L208_A2 | 6 | 1800 | 0.787794 | 0.199753 | 5.292691 | 8.616701 | 12.157395 |
| BLOCKB02_L208_A2 | 7 | 1800 | 0.914038 | 0.212860 | 6.957404 | 9.863453 | 13.388466 |
| BLOCKB02_L208_S2 | 0 | 1800 | 0.131606 | 0.076690 | 0.528877 | 1.225226 | 2.341633 |
| BLOCKB02_L208_S2 | 1 | 1800 | 0.268642 | 0.130068 | 1.200771 | 1.666171 | 2.510869 |
| BLOCKB02_L208_S2 | 2 | 1800 | 0.377939 | 0.150575 | 1.395167 | 2.059217 | 2.984347 |
| BLOCKB02_L208_S2 | 3 | 1800 | 0.492682 | 0.175539 | 1.467173 | 2.102882 | 3.000116 |
| BLOCKB02_L208_S2 | 4 | 1800 | 0.615312 | 0.322245 | 1.557743 | 2.249446 | 3.157059 |
| BLOCKB02_L208_S2 | 5 | 1800 | 0.744096 | 0.643390 | 1.614497 | 2.355714 | 3.182522 |
| BLOCKB02_L208_S2 | 6 | 1800 | 0.878740 | 0.796898 | 1.677062 | 2.405206 | 3.195411 |
| BLOCKB02_L208_S2 | 7 | 1800 | 1.021004 | 0.986627 | 1.757512 | 2.507533 | 3.655916 |
| BLOCKB02_L200_A2 | 0 | 1800 | 0.101515 | 0.075385 | 0.163428 | 0.720616 | 2.262871 |
| BLOCKB02_L200_A2 | 1 | 1800 | 0.263104 | 0.124925 | 1.151433 | 1.478114 | 2.318095 |
| BLOCKB02_L200_A2 | 2 | 1800 | 0.393442 | 0.140333 | 2.150939 | 2.779374 | 3.231797 |
| BLOCKB02_L200_A2 | 3 | 1800 | 0.521111 | 0.154065 | 3.155137 | 4.101102 | 4.557291 |
| BLOCKB02_L200_A2 | 4 | 1800 | 0.650287 | 0.167243 | 4.163497 | 5.456375 | 6.140682 |
| BLOCKB02_L200_A2 | 5 | 1800 | 0.792258 | 0.180206 | 5.181195 | 7.345311 | 9.755906 |
| BLOCKB02_L200_A2 | 6 | 1800 | 0.940266 | 0.193443 | 6.427206 | 8.742382 | 11.079770 |
| BLOCKB02_L200_A2 | 7 | 1800 | 1.073566 | 0.206254 | 7.806012 | 10.051248 | 12.398052 |
| BLOCKB02_L200_S2 | 0 | 1800 | 0.100535 | 0.076042 | 0.110762 | 0.995972 | 2.566812 |
| BLOCKB02_L200_S2 | 1 | 1800 | 0.265942 | 0.130634 | 1.139402 | 1.460705 | 2.623673 |
| BLOCKB02_L200_S2 | 2 | 1800 | 0.405496 | 0.151622 | 1.466906 | 1.624261 | 3.082706 |
| BLOCKB02_L200_S2 | 3 | 1800 | 0.553496 | 0.218409 | 1.548082 | 1.816137 | 3.097419 |
| BLOCKB02_L200_S2 | 4 | 1800 | 0.708778 | 0.596832 | 1.611467 | 1.915704 | 3.173544 |
| BLOCKB02_L200_S2 | 5 | 1800 | 0.872730 | 0.847407 | 1.682854 | 2.132865 | 3.553395 |
| BLOCKB02_L200_S2 | 6 | 1800 | 1.045568 | 1.032397 | 1.754172 | 2.165965 | 3.568635 |
| BLOCKB02_L200_S2 | 7 | 1800 | 1.173465 | 1.100803 | 2.224652 | 2.845952 | 3.581960 |
| BLOCKB02_L216_S2 | 0 | 1800 | 0.117268 | 0.076784 | 0.244021 | 1.142154 | 2.012306 |
| BLOCKB02_L216_S2 | 1 | 1800 | 0.227729 | 0.130254 | 0.962736 | 1.344742 | 2.342437 |
| BLOCKB02_L216_S2 | 2 | 1800 | 0.308936 | 0.148278 | 1.292354 | 1.519337 | 2.359048 |
| BLOCKB02_L216_S2 | 3 | 1800 | 0.393311 | 0.167624 | 1.363412 | 1.687644 | 2.373603 |
| BLOCKB02_L216_S2 | 4 | 1800 | 0.483915 | 0.192474 | 1.451503 | 2.031509 | 2.395653 |
| BLOCKB02_L216_S2 | 5 | 1800 | 0.578068 | 0.278843 | 1.507117 | 2.094657 | 2.488534 |
| BLOCKB02_L216_S2 | 6 | 1800 | 0.678334 | 0.435036 | 1.580546 | 2.253412 | 3.211435 |
| BLOCKB02_L216_S2 | 7 | 1800 | 0.783500 | 0.598121 | 1.650391 | 2.275503 | 3.224009 |
| BLOCKB02_L216_A2 | 0 | 1800 | 0.130020 | 0.076746 | 0.440673 | 1.238561 | 2.483782 |
| BLOCKB02_L216_A2 | 1 | 1800 | 0.239091 | 0.130771 | 1.149606 | 1.366297 | 2.505636 |
| BLOCKB02_L216_A2 | 2 | 1800 | 0.313347 | 0.146617 | 1.340800 | 2.390063 | 3.540354 |
| BLOCKB02_L216_A2 | 3 | 1800 | 0.386136 | 0.160671 | 1.929174 | 3.509526 | 4.678891 |
| BLOCKB02_L216_A2 | 4 | 1800 | 0.458475 | 0.174583 | 2.526643 | 4.639330 | 5.809855 |
| BLOCKB02_L216_A2 | 5 | 1800 | 0.542548 | 0.188033 | 3.131719 | 5.974028 | 9.901470 |
| BLOCKB02_L216_A2 | 6 | 1800 | 0.637197 | 0.201151 | 3.729799 | 8.128469 | 11.473230 |
| BLOCKB02_L216_A2 | 7 | 1800 | 0.708970 | 0.213989 | 4.328350 | 9.256739 | 12.617916 |
| BLOCKB02_L200_S3 | 0 | 1800 | 0.092154 | 0.076747 | 0.103732 | 0.390988 | 1.764206 |
| BLOCKB02_L200_S3 | 1 | 1800 | 0.260092 | 0.132163 | 1.150116 | 1.471574 | 1.819948 |
| BLOCKB02_L200_S3 | 2 | 1800 | 0.400929 | 0.153911 | 1.473763 | 1.561118 | 1.909492 |
| BLOCKB02_L200_S3 | 3 | 1800 | 0.549492 | 0.228233 | 1.537469 | 1.684790 | 3.279228 |
| BLOCKB02_L200_S3 | 4 | 1800 | 0.709674 | 0.602492 | 1.615808 | 1.765630 | 3.293015 |
| BLOCKB02_L200_S3 | 5 | 1800 | 0.874015 | 0.877892 | 1.686031 | 1.842338 | 3.306201 |
| BLOCKB02_L200_S3 | 6 | 1800 | 1.048576 | 1.047810 | 1.747287 | 1.945894 | 3.320960 |
| BLOCKB02_L200_S3 | 7 | 1800 | 1.176458 | 1.112424 | 2.233331 | 2.867665 | 3.334071 |
| BLOCKB02_L200_A3 | 0 | 1800 | 0.114096 | 0.075973 | 0.239137 | 1.173178 | 2.234409 |
| BLOCKB02_L200_A3 | 1 | 1800 | 0.278832 | 0.128864 | 1.225206 | 1.474335 | 2.281696 |
| BLOCKB02_L200_A3 | 2 | 1800 | 0.408332 | 0.144449 | 2.146395 | 2.776905 | 3.641585 |
| BLOCKB02_L200_A3 | 3 | 1800 | 0.537777 | 0.158851 | 3.154785 | 4.107227 | 5.031253 |
| BLOCKB02_L200_A3 | 4 | 1800 | 0.673014 | 0.172288 | 4.172673 | 5.624994 | 7.516405 |
| BLOCKB02_L200_A3 | 5 | 1800 | 0.820016 | 0.185055 | 5.182102 | 7.682048 | 10.650026 |
| BLOCKB02_L200_A3 | 6 | 1800 | 0.965422 | 0.198270 | 6.544928 | 9.015078 | 11.657913 |
| BLOCKB02_L200_A3 | 7 | 1800 | 1.097349 | 0.210832 | 7.676364 | 10.325287 | 12.671254 |
| BLOCKB02_L216_S3 | 0 | 1800 | 0.112971 | 0.077296 | 0.164574 | 1.268375 | 2.194377 |
| BLOCKB02_L216_S3 | 1 | 1800 | 0.220819 | 0.129887 | 1.046204 | 1.393480 | 2.641594 |
| BLOCKB02_L216_S3 | 2 | 1800 | 0.301513 | 0.148467 | 1.284195 | 1.492206 | 2.658918 |
| BLOCKB02_L216_S3 | 3 | 1800 | 0.385609 | 0.167220 | 1.349527 | 1.536000 | 2.673955 |
| BLOCKB02_L216_S3 | 4 | 1800 | 0.474886 | 0.189186 | 1.414350 | 1.598361 | 2.688260 |
| BLOCKB02_L216_S3 | 5 | 1800 | 0.568717 | 0.258223 | 1.496985 | 1.671807 | 2.702047 |
| BLOCKB02_L216_S3 | 6 | 1800 | 0.667866 | 0.428137 | 1.555087 | 1.887599 | 2.715538 |
| BLOCKB02_L216_S3 | 7 | 1800 | 0.772756 | 0.606526 | 1.616662 | 2.068081 | 3.368168 |
| BLOCKB02_L216_A3 | 0 | 1800 | 0.122055 | 0.076273 | 0.245354 | 1.369016 | 3.238060 |
| BLOCKB02_L216_A3 | 1 | 1800 | 0.230009 | 0.129468 | 1.150287 | 1.438322 | 3.284495 |
| BLOCKB02_L216_A3 | 2 | 1800 | 0.305150 | 0.145341 | 1.346223 | 2.398368 | 3.889755 |
| BLOCKB02_L216_A3 | 3 | 1800 | 0.377621 | 0.159415 | 1.925859 | 3.522184 | 5.015912 |
| BLOCKB02_L216_A3 | 4 | 1800 | 0.450393 | 0.172970 | 2.521813 | 4.646959 | 6.150410 |
| BLOCKB02_L216_A3 | 5 | 1800 | 0.535560 | 0.186100 | 3.128914 | 5.947031 | 11.859346 |
| BLOCKB02_L216_A3 | 6 | 1800 | 0.619912 | 0.199918 | 3.726245 | 7.684713 | 12.993900 |
| BLOCKB02_L216_A3 | 7 | 1800 | 0.694101 | 0.215029 | 4.325109 | 8.806893 | 14.126269 |
| BLOCKB02_L208_A3 | 0 | 1800 | 0.136745 | 0.075755 | 0.541599 | 1.512688 | 2.441287 |
| BLOCKB02_L208_A3 | 1 | 1800 | 0.269128 | 0.126364 | 1.299275 | 1.664718 | 2.936013 |
| BLOCKB02_L208_A3 | 2 | 1800 | 0.369854 | 0.142314 | 1.861376 | 2.595282 | 3.629640 |
| BLOCKB02_L208_A3 | 3 | 1800 | 0.468427 | 0.156290 | 2.707375 | 3.821632 | 4.856018 |
| BLOCKB02_L208_A3 | 4 | 1800 | 0.567448 | 0.169584 | 3.578598 | 5.044861 | 6.079490 |
| BLOCKB02_L208_A3 | 5 | 1800 | 0.689070 | 0.182572 | 4.437615 | 7.045236 | 11.266440 |
| BLOCKB02_L208_A3 | 6 | 1800 | 0.796982 | 0.195741 | 5.304049 | 8.374747 | 12.489726 |
| BLOCKB02_L208_A3 | 7 | 1800 | 0.927542 | 0.208457 | 6.987314 | 9.772379 | 13.711271 |
| BLOCKB02_L208_S3 | 0 | 1800 | 0.124903 | 0.076295 | 0.326861 | 1.141282 | 2.396689 |
| BLOCKB02_L208_S3 | 1 | 1800 | 0.257974 | 0.128772 | 1.174707 | 1.416973 | 2.906778 |
| BLOCKB02_L208_S3 | 2 | 1800 | 0.366424 | 0.148587 | 1.373215 | 1.669585 | 2.921547 |
| BLOCKB02_L208_S3 | 3 | 1800 | 0.482607 | 0.174336 | 1.463480 | 1.797795 | 2.936445 |
| BLOCKB02_L208_S3 | 4 | 1800 | 0.603035 | 0.325482 | 1.531128 | 2.057631 | 2.949353 |
| BLOCKB02_L208_S3 | 5 | 1800 | 0.730133 | 0.624311 | 1.594527 | 2.174770 | 2.962186 |
| BLOCKB02_L208_S3 | 6 | 1800 | 0.864373 | 0.785116 | 1.665980 | 2.378721 | 3.599630 |
| BLOCKB02_L208_S3 | 7 | 1800 | 1.005312 | 0.974452 | 1.738887 | 2.486025 | 3.660913 |
| BLOCKB02_L216_A4 | 0 | 1800 | 0.119387 | 0.076274 | 0.254047 | 1.374499 | 2.509521 |
| BLOCKB02_L216_A4 | 1 | 1800 | 0.227808 | 0.127694 | 1.050030 | 1.550211 | 2.555993 |
| BLOCKB02_L216_A4 | 2 | 1800 | 0.301603 | 0.143139 | 1.344201 | 2.404761 | 3.200785 |
| BLOCKB02_L216_A4 | 3 | 1800 | 0.374491 | 0.157145 | 1.933608 | 3.527954 | 4.361894 |
| BLOCKB02_L216_A4 | 4 | 1800 | 0.449067 | 0.170745 | 2.539594 | 4.663948 | 7.170293 |
| BLOCKB02_L216_A4 | 5 | 1800 | 0.533105 | 0.184086 | 3.138713 | 5.970316 | 10.881438 |
| BLOCKB02_L216_A4 | 6 | 1800 | 0.615797 | 0.197953 | 3.739310 | 7.305730 | 12.018704 |
| BLOCKB02_L216_A4 | 7 | 1800 | 0.687869 | 0.211218 | 4.339935 | 8.433562 | 13.155221 |
| BLOCKB02_L216_S4 | 0 | 1800 | 0.110563 | 0.076806 | 0.160129 | 1.085015 | 7.432070 |
| BLOCKB02_L216_S4 | 1 | 1800 | 0.221717 | 0.130974 | 0.922942 | 1.295841 | 7.488153 |
| BLOCKB02_L216_S4 | 2 | 1800 | 0.303252 | 0.149485 | 1.284448 | 1.444620 | 7.502293 |
| BLOCKB02_L216_S4 | 3 | 1800 | 0.388111 | 0.167968 | 1.349917 | 1.584063 | 7.689489 |
| BLOCKB02_L216_S4 | 4 | 1800 | 0.478629 | 0.189501 | 1.435573 | 1.656920 | 7.700452 |
| BLOCKB02_L216_S4 | 5 | 1800 | 0.573149 | 0.268004 | 1.500986 | 1.769752 | 7.713711 |
| BLOCKB02_L216_S4 | 6 | 1800 | 0.673266 | 0.430472 | 1.574783 | 1.877697 | 7.724220 |
| BLOCKB02_L216_S4 | 7 | 1800 | 0.779432 | 0.593215 | 1.643080 | 2.043687 | 7.734729 |
| BLOCKB02_L200_S4 | 0 | 1800 | 0.098250 | 0.076685 | 0.147591 | 0.842435 | 2.203521 |
| BLOCKB02_L200_S4 | 1 | 1800 | 0.262424 | 0.130378 | 1.136695 | 1.451376 | 3.057100 |
| BLOCKB02_L200_S4 | 2 | 1800 | 0.402030 | 0.151123 | 1.457261 | 1.552237 | 3.071887 |
| BLOCKB02_L200_S4 | 3 | 1800 | 0.551928 | 0.228061 | 1.533636 | 1.740056 | 3.085304 |
| BLOCKB02_L200_S4 | 4 | 1800 | 0.706374 | 0.600456 | 1.622009 | 1.801395 | 3.099276 |
| BLOCKB02_L200_S4 | 5 | 1800 | 0.870011 | 0.864848 | 1.678873 | 1.892551 | 3.111470 |
| BLOCKB02_L200_S4 | 6 | 1800 | 1.044966 | 1.044093 | 1.756092 | 2.008617 | 3.123953 |
| BLOCKB02_L200_S4 | 7 | 1800 | 1.171838 | 1.109046 | 2.210239 | 2.833970 | 4.492424 |
| BLOCKB02_L200_A4 | 0 | 1800 | 0.111847 | 0.075594 | 0.234969 | 1.059996 | 2.386940 |
| BLOCKB02_L200_A4 | 1 | 1800 | 0.276455 | 0.128002 | 1.151247 | 1.481676 | 2.458841 |
| BLOCKB02_L200_A4 | 2 | 1800 | 0.405747 | 0.143330 | 2.153662 | 2.779916 | 3.781211 |
| BLOCKB02_L200_A4 | 3 | 1800 | 0.534338 | 0.157435 | 3.156737 | 4.097867 | 5.102691 |
| BLOCKB02_L200_A4 | 4 | 1800 | 0.666376 | 0.170853 | 4.163125 | 5.442068 | 7.742561 |
| BLOCKB02_L200_A4 | 5 | 1800 | 0.810035 | 0.184346 | 5.177094 | 7.746716 | 9.076542 |
| BLOCKB02_L200_A4 | 6 | 1800 | 0.954931 | 0.197856 | 6.348126 | 9.159508 | 10.396847 |
| BLOCKB02_L200_A4 | 7 | 1800 | 1.091129 | 0.210944 | 7.515563 | 10.431521 | 11.717753 |
| BLOCKB02_L208_S4 | 0 | 1800 | 0.111052 | 0.076662 | 0.145676 | 1.168033 | 2.395766 |
| BLOCKB02_L208_S4 | 1 | 1800 | 0.247131 | 0.129092 | 1.048201 | 1.414071 | 2.645435 |
| BLOCKB02_L208_S4 | 2 | 1800 | 0.357121 | 0.149350 | 1.377945 | 1.537438 | 3.155808 |
| BLOCKB02_L208_S4 | 3 | 1800 | 0.471563 | 0.173957 | 1.460284 | 1.770716 | 3.169780 |
| BLOCKB02_L208_S4 | 4 | 1800 | 0.592576 | 0.299551 | 1.529147 | 1.914408 | 3.182762 |
| BLOCKB02_L208_S4 | 5 | 1800 | 0.721802 | 0.618119 | 1.594060 | 2.150387 | 3.195512 |
| BLOCKB02_L208_S4 | 6 | 1800 | 0.857130 | 0.787462 | 1.662420 | 2.397596 | 3.649987 |
| BLOCKB02_L208_S4 | 7 | 1800 | 1.000142 | 0.966886 | 1.737209 | 2.416754 | 3.663571 |
| BLOCKB02_L208_A4 | 0 | 1800 | 0.127730 | 0.076204 | 0.344265 | 1.551614 | 2.666865 |
| BLOCKB02_L208_A4 | 1 | 1800 | 0.262884 | 0.127233 | 1.276164 | 1.726567 | 3.150755 |
| BLOCKB02_L208_A4 | 2 | 1800 | 0.363274 | 0.142736 | 1.853969 | 2.598123 | 4.377734 |
| BLOCKB02_L208_A4 | 3 | 1800 | 0.462647 | 0.156314 | 2.708284 | 3.821190 | 5.607085 |
| BLOCKB02_L208_A4 | 4 | 1800 | 0.562231 | 0.169658 | 3.574002 | 5.050142 | 6.850234 |
| BLOCKB02_L208_A4 | 5 | 1800 | 0.677485 | 0.183016 | 4.433347 | 6.903424 | 10.468551 |
| BLOCKB02_L208_A4 | 6 | 1800 | 0.788274 | 0.196400 | 5.300324 | 8.365536 | 12.082744 |
| BLOCKB02_L208_A4 | 7 | 1800 | 0.912319 | 0.209545 | 6.479732 | 9.837431 | 13.328141 |
| BLOCKB02_L208_S5 | 0 | 1800 | 0.101896 | 0.075281 | 0.130856 | 0.891043 | 2.205815 |
| BLOCKB02_L208_S5 | 1 | 1800 | 0.236188 | 0.127105 | 0.998518 | 1.367985 | 2.664704 |
| BLOCKB02_L208_S5 | 2 | 1800 | 0.344371 | 0.146243 | 1.366846 | 1.471549 | 3.157056 |
| BLOCKB02_L208_S5 | 3 | 1800 | 0.459363 | 0.168832 | 1.440745 | 1.590374 | 3.171927 |
| BLOCKB02_L208_S5 | 4 | 1800 | 0.579899 | 0.295523 | 1.519975 | 1.710004 | 3.185547 |
| BLOCKB02_L208_S5 | 5 | 1800 | 0.706947 | 0.608063 | 1.576597 | 1.831941 | 3.197677 |
| BLOCKB02_L208_S5 | 6 | 1800 | 0.842298 | 0.782600 | 1.664087 | 1.952055 | 3.210825 |
| BLOCKB02_L208_S5 | 7 | 1800 | 0.984124 | 0.949590 | 1.726891 | 2.128219 | 3.224149 |
| BLOCKB02_L208_A5 | 0 | 1800 | 0.133906 | 0.076090 | 0.533918 | 1.293931 | 2.256225 |
| BLOCKB02_L208_A5 | 1 | 1800 | 0.266486 | 0.127286 | 1.196602 | 1.481792 | 3.183573 |
| BLOCKB02_L208_A5 | 2 | 1800 | 0.369289 | 0.143470 | 1.856352 | 2.589607 | 4.421691 |
| BLOCKB02_L208_A5 | 3 | 1800 | 0.468797 | 0.157509 | 2.708084 | 3.820922 | 5.646819 |
| BLOCKB02_L208_A5 | 4 | 1800 | 0.567419 | 0.171069 | 3.567171 | 5.046921 | 6.874993 |
| BLOCKB02_L208_A5 | 5 | 1800 | 0.683113 | 0.184080 | 4.427436 | 7.092690 | 11.553642 |
| BLOCKB02_L208_A5 | 6 | 1800 | 0.798875 | 0.197416 | 5.300508 | 8.584429 | 12.797317 |
| BLOCKB02_L208_A5 | 7 | 1800 | 0.919636 | 0.210326 | 6.750690 | 9.956188 | 14.026501 |
| BLOCKB02_L216_A5 | 0 | 1800 | 0.137935 | 0.076413 | 0.628293 | 1.400022 | 4.640066 |
| BLOCKB02_L216_A5 | 1 | 1800 | 0.246376 | 0.129975 | 1.224413 | 1.528447 | 4.683595 |
| BLOCKB02_L216_A5 | 2 | 1800 | 0.320782 | 0.145798 | 1.382180 | 2.388987 | 4.698558 |
| BLOCKB02_L216_A5 | 3 | 1800 | 0.393979 | 0.159998 | 1.929225 | 3.518749 | 4.710900 |
| BLOCKB02_L216_A5 | 4 | 1800 | 0.465965 | 0.173217 | 2.527480 | 4.645961 | 5.542282 |
| BLOCKB02_L216_A5 | 5 | 1800 | 0.551435 | 0.186492 | 3.125894 | 6.190875 | 9.188045 |
| BLOCKB02_L216_A5 | 6 | 1800 | 0.638689 | 0.199848 | 3.725155 | 7.966996 | 11.280673 |
| BLOCKB02_L216_A5 | 7 | 1800 | 0.710789 | 0.213001 | 4.333106 | 9.091931 | 12.425550 |
| BLOCKB02_L216_S5 | 0 | 1800 | 0.111842 | 0.077453 | 0.208430 | 1.060124 | 2.319776 |
| BLOCKB02_L216_S5 | 1 | 1800 | 0.226266 | 0.133364 | 0.930903 | 1.385924 | 2.377332 |
| BLOCKB02_L216_S5 | 2 | 1800 | 0.309679 | 0.152535 | 1.307473 | 1.620552 | 2.393785 |
| BLOCKB02_L216_S5 | 3 | 1800 | 0.397301 | 0.172568 | 1.385191 | 1.748603 | 3.209995 |
| BLOCKB02_L216_S5 | 4 | 1800 | 0.491009 | 0.198819 | 1.476918 | 1.917909 | 3.224032 |
| BLOCKB02_L216_S5 | 5 | 1800 | 0.588765 | 0.285875 | 1.547436 | 1.942271 | 3.237143 |
| BLOCKB02_L216_S5 | 6 | 1800 | 0.691562 | 0.437914 | 1.639868 | 1.987495 | 3.251023 |
| BLOCKB02_L216_S5 | 7 | 1800 | 0.800350 | 0.614137 | 1.701808 | 2.109320 | 3.263458 |
| BLOCKB02_L200_A5 | 0 | 1800 | 0.144342 | 0.076655 | 0.615038 | 1.556704 | 3.413652 |
| BLOCKB02_L200_A5 | 1 | 1800 | 0.308864 | 0.131275 | 1.304415 | 1.695216 | 3.538990 |
| BLOCKB02_L200_A5 | 2 | 1800 | 0.439417 | 0.147571 | 2.155380 | 2.789679 | 4.864433 |
| BLOCKB02_L200_A5 | 3 | 1800 | 0.570050 | 0.161928 | 3.164582 | 4.124737 | 6.193468 |
| BLOCKB02_L200_A5 | 4 | 1800 | 0.703343 | 0.175551 | 4.182766 | 5.562961 | 7.626708 |
| BLOCKB02_L200_A5 | 5 | 1800 | 0.854275 | 0.188904 | 5.197836 | 7.665046 | 11.293556 |
| BLOCKB02_L200_A5 | 6 | 1800 | 1.013778 | 0.201920 | 6.912090 | 9.365353 | 12.884507 |
| BLOCKB02_L200_A5 | 7 | 1800 | 1.148038 | 0.215085 | 8.028604 | 10.687651 | 13.950896 |
| BLOCKB02_L200_S5 | 0 | 1800 | 0.103676 | 0.076060 | 0.118351 | 0.981789 | 2.146688 |
| BLOCKB02_L200_S5 | 1 | 1800 | 0.268288 | 0.130369 | 1.144669 | 1.486118 | 2.911383 |
| BLOCKB02_L200_S5 | 2 | 1800 | 0.409499 | 0.152421 | 1.463433 | 1.717115 | 3.078813 |
| BLOCKB02_L200_S5 | 3 | 1800 | 0.559010 | 0.222946 | 1.547799 | 1.935966 | 3.092276 |
| BLOCKB02_L200_S5 | 4 | 1800 | 0.713807 | 0.595228 | 1.623378 | 2.070188 | 3.104415 |
| BLOCKB02_L200_S5 | 5 | 1800 | 0.877446 | 0.874406 | 1.681747 | 2.112249 | 3.625650 |
| BLOCKB02_L200_S5 | 6 | 1800 | 1.053299 | 1.050659 | 1.766941 | 2.222539 | 3.652882 |
| BLOCKB02_L200_S5 | 7 | 1800 | 1.180931 | 1.109708 | 2.220894 | 2.852842 | 3.997593 |

### Initial source slot: exact timestamps

Each vector is in stream ID order 0..K-1; every stream has frame_id=0, logical source_slot=0, scheduled timestamp equal to the common t0. The observed vector is the pre-publication scheduler observation, not exact queue insertion. Warmups remain labeled above.

| Run | common scheduled t0 (ns) | admission_observed_ns vector |
|---|---:|---|
| BLOCKB02_WARMUP_L200_E40_S | 3475543758479 | [3475543858254, 3475544081616, 3475544101319, 3475544116847, 3475544130384, 3475544143671, 3475544156755, 3475544231404] |
| BLOCKB02_L216_A1 | 3507115916646 | [3507116011399, 3507116198002, 3507116282271, 3507116360105, 3507116435503, 3507116510412, 3507116585550, 3507116659800] |
| BLOCKB02_L216_S1 | 3588203964182 | [3588204050008, 3588204236648, 3588204255814, 3588204270814, 3588204284175, 3588204296824, 3588204308814, 3588204320953] |
| BLOCKB02_L208_S1 | 3670534390594 | [3670534487519, 3670534681030, 3670534700493, 3670534716734, 3670534730873, 3670534745179, 3670534758679, 3670534772364] |
| BLOCKB02_L208_A1 | 3754386154395 | [3754386246213, 3754386486121, 3754386581715, 3754386676428, 3754386756540, 3754386836243, 3754386911160, 3754386988837] |
| BLOCKB02_L200_A1 | 3837447226613 | [3837447325371, 3837447518918, 3837447600307, 3837447676308, 3837447752067, 3837447825013, 3837447898272, 3837447970800] |
| BLOCKB02_L200_S1 | 3921495940976 | [3921496070944, 3921496266084, 3921496286103, 3921496301381, 3921496315613, 3921496329548, 3921496342909, 3921496417474] |
| BLOCKB02_L208_A2 | 4006278488361 | [4006278584430, 4006278781857, 4006278865709, 4006278946451, 4006279024405, 4006279101368, 4006279177619, 4006279253555] |
| BLOCKB02_L208_S2 | 4088925548481 | [4088925631495, 4088925803783, 4088925822394, 4088925838125, 4088925851496, 4088925863699, 4088925876181, 4088925887718] |
| BLOCKB02_L200_A2 | 4172411485260 | [4172411576554, 4172411756566, 4172411838900, 4172411915873, 4172411991745, 4172412071476, 4172412146227, 4172412219811] |
| BLOCKB02_L200_S2 | 4256135970006 | [4256136041155, 4256136233305, 4256136252620, 4256136267786, 4256136281684, 4256136295434, 4256136309194, 4256136384324] |
| BLOCKB02_L216_S2 | 4341048087335 | [4341048174859, 4341048360249, 4341048379582, 4341048395554, 4341048408944, 4341048422352, 4341048436991, 4341048449898] |
| BLOCKB02_L216_A2 | 4423284130422 | [4423284221698, 4423284405116, 4423284486357, 4423284563775, 4423284638303, 4423284712887, 4423284786351, 4423284859111] |
| BLOCKB02_L200_S3 | 4504547725299 | [4504547809388, 4504548026020, 4504548046835, 4504548061807, 4504548075668, 4504548089372, 4504548102974, 4504548178577] |
| BLOCKB02_L200_A3 | 4589668192417 | [4589668300216, 4589668505736, 4589668587783, 4589668666293, 4589668742572, 4589668816479, 4589668889786, 4589668964461] |
| BLOCKB02_L216_S3 | 4673411932876 | [4673412027232, 4673412219984, 4673412239401, 4673412255809, 4673412270012, 4673412284892, 4673412299123, 4673412313262] |
| BLOCKB02_L216_A3 | 4756107792991 | [4756107887418, 4756108092873, 4756108174957, 4756108252133, 4756108326505, 4756108399634, 4756108473024, 4756108546507] |
| BLOCKB02_L208_A3 | 4837244453169 | [4837244548603, 4837244742271, 4837244823346, 4837244900476, 4837244976569, 4837245050949, 4837245127200, 4837245200941] |
| BLOCKB02_L208_S3 | 4919656253815 | [4919656440989, 4919656668426, 4919656688935, 4919656706509, 4919656722916, 4919656738223, 4919656753380, 4919656768260] |
| BLOCKB02_L216_A4 | 5003424733038 | [5003424832209, 5003425045554, 5003425127823, 5003425207305, 5003425283657, 5003425358945, 5003425433926, 5003425509464] |
| BLOCKB02_L216_S4 | 5084752191143 | [5084752281901, 5084752482078, 5084752501911, 5084752518161, 5084752532857, 5084752547116, 5084752561024, 5084752573625] |
| BLOCKB02_L200_S4 | 5166704873649 | [5166704951780, 5166705130077, 5166705150743, 5166705164790, 5166705178466, 5166705192614, 5166705205754, 5166705281550] |
| BLOCKB02_L200_A4 | 5251466968969 | [5251467093304, 5251467279981, 5251467360796, 5251467436426, 5251467512611, 5251467587677, 5251467661585, 5251467734345] |
| BLOCKB02_L208_S4 | 5335176014854 | [5335176114599, 5335176309915, 5335176329712, 5335176345740, 5335176359758, 5335176373305, 5335176386703, 5335176399842] |
| BLOCKB02_L208_A4 | 5419100840639 | [5419100936250, 5419101118288, 5419101199188, 5419101276539, 5419101350577, 5419101425457, 5419101499189, 5419101573078] |
| BLOCKB02_L208_S5 | 5502203331899 | [5502203408759, 5502203588325, 5502203608029, 5502203624112, 5502203638455, 5502203652418, 5502203666047, 5502203679260] |
| BLOCKB02_L208_A5 | 5585826899242 | [5585826993345, 5585827191892, 5585827274847, 5585827353301, 5585827429367, 5585827505570, 5585827581849, 5585827657377] |
| BLOCKB02_L216_A5 | 5668878739441 | [5668878828244, 5668879013291, 5668879096338, 5668879172774, 5668879246719, 5668879321867, 5668879395276, 5668879469831] |
| BLOCKB02_L216_S5 | 5749892335492 | [5749892431784, 5749892712433, 5749892734378, 5749892751814, 5749892768138, 5749892782952, 5749892796573, 5749892814239] |
| BLOCKB02_L200_A5 | 5831792741680 | [5831792820139, 5831793029298, 5831793123631, 5831793201456, 5831793275521, 5831793350022, 5831793424356, 5831793498013] |
| BLOCKB02_L200_S5 | 5915540301749 | [5915540462162, 5915541019294, 5915541041666, 5915541057731, 5915541070795, 5915541084240, 5915541097906, 5915541172981] |

### Exact inspected files

| Run | raw frame artifact | manifest | schedule fidelity |
|---|---|---|---|
| BLOCKB02_WARMUP_L200_E40_S | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_WARMUP_L200_E40_S/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_WARMUP_L200_E40_S/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_A1 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_S1 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_S1 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_A1 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_A1 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_S1 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_A2 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_S2 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_A2 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_S2 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_S2 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_A2 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_S3 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_A3 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_S3 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_A3 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_A3 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_S3 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_A4 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_S4 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_S4 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_A4 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_S4 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_A4 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_S5 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L208_A5 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_A5 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L216_S5 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_A5 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/manifest.json | UNAVAILABLE: no file produced by this path |
| BLOCKB02_L200_S5 | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/manifest.json | UNAVAILABLE: no file produced by this path |

## block_b_confirmation02
Canonical root: results/timely_capacity_campaign/v2_2/block_b_confirmation02. Plan SHA-256: 2d51128bf897be48cd0db8835a9d1deb423c0053a31e8093350b3b525ca25a08. Measured runs: 25; separately labeled warmup sessions: 1. All 45000 measured slots complete; logical spread mean/p50/p95/max = 0 ns; nonzero, missing, duplicate, unexpected, early-observation and formula-mismatch counts = 0.
Pooled host observation spread mean/p50/p95/p99/max (ms): 0.957596, 0.569094, 2.772736, 8.878780, 15.781815. Pooled lateness mean/p50/p95/p99/max (ms): 0.588967, 0.190325, 1.732979, 4.626673, 15.857215.
### Per-run observation fidelity

Numbers are milliseconds. Mean range and p95 range compare per-stream metrics within that run. Observation ordering is not GPU ordering.

| Run | Scope | K | slots | spread p50 | spread p95 | spread p99 | spread max | first-slot spread | mean range | p95 range | earliest mean sid | latest mean sid | strictly sid-ascending slots |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BCONF02_WARMUP_L200_S | WARMUP diagnostic | 8 | 450 | 1.031620 | 2.145120 | 2.777214 | 2.821162 | 0.871129 | 1.082724 | 2.122541 | 0 | 7 | 450 |
| BCONF02_L216_A1 | MEASURED | 8 | 1800 | 0.136612 | 4.256522 | 8.872287 | 12.784772 | 0.653718 | 0.573800 | 4.095757 | 0 | 7 | 1800 |
| BCONF02_L200_A1 | MEASURED | 8 | 1800 | 0.134399 | 7.920118 | 10.319809 | 12.613854 | 0.631255 | 0.992377 | 7.823149 | 0 | 7 | 1800 |
| BCONF02_L200_S1 | MEASURED | 8 | 1800 | 1.014647 | 2.140327 | 2.776536 | 3.768734 | 0.404402 | 1.078839 | 2.111244 | 0 | 7 | 1800 |
| BCONF02_L208_S1 | MEASURED | 8 | 1800 | 0.868363 | 1.629607 | 1.684188 | 2.787281 | 0.317929 | 0.889923 | 1.597247 | 0 | 7 | 1800 |
| BCONF02_L192_S1 | MEASURED | 8 | 1800 | 1.154537 | 2.849286 | 2.971432 | 3.374897 | 0.326530 | 1.245551 | 2.823153 | 0 | 7 | 1800 |
| BCONF02_L200_A2 | MEASURED | 8 | 1800 | 0.135204 | 7.779901 | 10.328924 | 13.905989 | 0.637360 | 0.991859 | 7.631672 | 0 | 7 | 1800 |
| BCONF02_L200_S2 | MEASURED | 8 | 1800 | 1.000951 | 2.139331 | 2.776037 | 3.173390 | 0.328564 | 1.074744 | 2.122347 | 0 | 7 | 1800 |
| BCONF02_L208_S2 | MEASURED | 8 | 1800 | 0.856200 | 1.620894 | 1.675593 | 2.335337 | 0.289028 | 0.880895 | 1.587873 | 0 | 7 | 1800 |
| BCONF02_L192_S2 | MEASURED | 8 | 1800 | 1.164868 | 2.852142 | 2.979020 | 3.206376 | 0.361834 | 1.247883 | 2.802082 | 0 | 7 | 1800 |
| BCONF02_L216_A2 | MEASURED | 8 | 1800 | 0.135028 | 4.254493 | 9.038111 | 13.879155 | 0.639223 | 0.574617 | 3.892128 | 0 | 7 | 1800 |
| BCONF02_L200_S3 | MEASURED | 8 | 1800 | 1.018610 | 2.134495 | 2.775550 | 3.491252 | 0.372316 | 1.079715 | 2.099269 | 0 | 7 | 1800 |
| BCONF02_L208_S3 | MEASURED | 8 | 1800 | 0.875614 | 1.641988 | 1.773623 | 2.346017 | 0.274222 | 0.897035 | 1.450175 | 0 | 7 | 1800 |
| BCONF02_L192_S3 | MEASURED | 8 | 1800 | 1.158940 | 2.845190 | 2.975259 | 4.256824 | 0.336214 | 1.251467 | 2.830462 | 0 | 7 | 1800 |
| BCONF02_L216_A3 | MEASURED | 8 | 1800 | 0.136376 | 4.262236 | 9.305982 | 12.937679 | 0.760975 | 0.588822 | 3.819042 | 0 | 7 | 1800 |
| BCONF02_L200_A3 | MEASURED | 8 | 1800 | 0.132996 | 7.833233 | 10.126740 | 12.369188 | 0.677420 | 0.986180 | 7.725726 | 0 | 7 | 1800 |
| BCONF02_L208_S4 | MEASURED | 8 | 1800 | 0.885921 | 1.666390 | 1.844634 | 2.641837 | 0.296650 | 0.910833 | 1.604303 | 0 | 7 | 1800 |
| BCONF02_L192_S4 | MEASURED | 8 | 1800 | 1.156691 | 2.859550 | 2.979258 | 3.431629 | 0.341974 | 1.246151 | 2.808627 | 0 | 7 | 1800 |
| BCONF02_L216_A4 | MEASURED | 8 | 1800 | 0.132213 | 4.254876 | 9.011640 | 12.097806 | 0.671364 | 0.575740 | 3.870560 | 0 | 7 | 1800 |
| BCONF02_L200_A4 | MEASURED | 8 | 1800 | 0.137116 | 7.673190 | 10.235507 | 12.772913 | 0.641689 | 0.988693 | 7.619847 | 0 | 7 | 1800 |
| BCONF02_L200_S4 | MEASURED | 8 | 1800 | 1.017506 | 2.145673 | 2.777319 | 3.133999 | 0.351048 | 1.081880 | 2.121853 | 0 | 7 | 1800 |
| BCONF02_L192_S5 | MEASURED | 8 | 1800 | 1.158655 | 2.847559 | 2.962697 | 3.894392 | 0.349576 | 1.249589 | 2.829819 | 0 | 7 | 1800 |
| BCONF02_L216_A5 | MEASURED | 8 | 1800 | 0.135307 | 4.257438 | 8.825745 | 12.537721 | 0.649911 | 0.571445 | 4.011373 | 0 | 7 | 1800 |
| BCONF02_L200_A5 | MEASURED | 8 | 1800 | 0.132454 | 7.990349 | 10.433712 | 15.781815 | 0.639624 | 0.999868 | 7.845422 | 0 | 7 | 1800 |
| BCONF02_L200_S5 | MEASURED | 8 | 1800 | 0.999178 | 2.138996 | 2.759411 | 3.169343 | 0.333345 | 1.076047 | 2.100089 | 0 | 7 | 1800 |
| BCONF02_L208_S5 | MEASURED | 8 | 1800 | 0.862982 | 1.625769 | 1.682254 | 2.389923 | 0.267269 | 0.885955 | 1.435114 | 0 | 7 | 1800 |

### Per-stream host release-observation lateness

| Run | stream_id | frames | mean ms | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| BCONF02_WARMUP_L200_S | 0 | 450 | 0.097143 | 0.076563 | 0.108544 | 0.742511 | 1.631301 |
| BCONF02_WARMUP_L200_S | 1 | 450 | 0.263936 | 0.131609 | 1.132878 | 1.452542 | 1.717700 |
| BCONF02_WARMUP_L200_S | 2 | 450 | 0.405054 | 0.156241 | 1.461520 | 1.557851 | 2.226892 |
| BCONF02_WARMUP_L200_S | 3 | 450 | 0.553619 | 0.228388 | 1.548153 | 1.649999 | 2.243466 |
| BCONF02_WARMUP_L200_S | 4 | 450 | 0.709588 | 0.602779 | 1.621743 | 1.782223 | 2.612939 |
| BCONF02_WARMUP_L200_S | 5 | 450 | 0.877401 | 0.866280 | 1.680712 | 1.889910 | 2.627559 |
| BCONF02_WARMUP_L200_S | 6 | 450 | 1.050198 | 1.042587 | 1.754485 | 2.014073 | 2.691164 |
| BCONF02_WARMUP_L200_S | 7 | 450 | 1.179867 | 1.122081 | 2.231085 | 2.856070 | 2.900749 |
| BCONF02_L216_A1 | 0 | 1800 | 0.109496 | 0.076313 | 0.239569 | 1.027908 | 1.984979 |
| BCONF02_L216_A1 | 1 | 1800 | 0.221002 | 0.131105 | 0.926610 | 1.287210 | 2.688829 |
| BCONF02_L216_A1 | 2 | 1800 | 0.295168 | 0.146833 | 1.330416 | 2.395943 | 3.818727 |
| BCONF02_L216_A1 | 3 | 1800 | 0.367839 | 0.160762 | 1.924967 | 3.524947 | 4.947329 |
| BCONF02_L216_A1 | 4 | 1800 | 0.440857 | 0.174625 | 2.535340 | 4.648551 | 6.084820 |
| BCONF02_L216_A1 | 5 | 1800 | 0.525189 | 0.187924 | 3.135363 | 6.182870 | 10.590676 |
| BCONF02_L216_A1 | 6 | 1800 | 0.610889 | 0.201539 | 3.735492 | 7.868135 | 11.738037 |
| BCONF02_L216_A1 | 7 | 1800 | 0.683296 | 0.215211 | 4.335326 | 8.991704 | 12.864213 |
| BCONF02_L200_A1 | 0 | 1800 | 0.099257 | 0.076414 | 0.176993 | 0.621926 | 2.013326 |
| BCONF02_L200_A1 | 1 | 1800 | 0.267226 | 0.129748 | 1.157960 | 1.474050 | 3.111023 |
| BCONF02_L200_A1 | 2 | 1800 | 0.397003 | 0.145568 | 2.161873 | 2.787557 | 4.467812 |
| BCONF02_L200_A1 | 3 | 1800 | 0.525681 | 0.159734 | 3.170492 | 4.111282 | 5.791405 |
| BCONF02_L200_A1 | 4 | 1800 | 0.661721 | 0.173495 | 4.178570 | 5.526185 | 7.952186 |
| BCONF02_L200_A1 | 5 | 1800 | 0.809357 | 0.186470 | 5.196463 | 7.738625 | 10.193756 |
| BCONF02_L200_A1 | 6 | 1800 | 0.955442 | 0.199455 | 6.583302 | 9.093621 | 11.520313 |
| BCONF02_L200_A1 | 7 | 1800 | 1.091634 | 0.212642 | 8.000142 | 10.462547 | 12.851806 |
| BCONF02_L200_S1 | 0 | 1800 | 0.089122 | 0.076468 | 0.111654 | 0.348324 | 1.479556 |
| BCONF02_L200_S1 | 1 | 1800 | 0.258035 | 0.134546 | 1.134668 | 1.464698 | 2.260351 |
| BCONF02_L200_S1 | 2 | 1800 | 0.399622 | 0.155176 | 1.470137 | 1.558073 | 2.459415 |
| BCONF02_L200_S1 | 3 | 1800 | 0.546986 | 0.229837 | 1.541689 | 1.628579 | 2.476572 |
| BCONF02_L200_S1 | 4 | 1800 | 0.702841 | 0.599779 | 1.603779 | 1.724093 | 2.754306 |
| BCONF02_L200_S1 | 5 | 1800 | 0.866583 | 0.865381 | 1.672542 | 1.804405 | 2.769213 |
| BCONF02_L200_S1 | 6 | 1800 | 1.039099 | 1.031170 | 1.741358 | 1.895080 | 3.107681 |
| BCONF02_L200_S1 | 7 | 1800 | 1.167961 | 1.104817 | 2.222898 | 2.859661 | 3.844509 |
| BCONF02_L208_S1 | 0 | 1800 | 0.094170 | 0.076969 | 0.126854 | 0.805176 | 1.807763 |
| BCONF02_L208_S1 | 1 | 1800 | 0.235898 | 0.134497 | 1.012335 | 1.372157 | 1.877541 |
| BCONF02_L208_S1 | 2 | 1800 | 0.345109 | 0.154767 | 1.374904 | 1.468902 | 2.730487 |
| BCONF02_L208_S1 | 3 | 1800 | 0.460095 | 0.178262 | 1.450319 | 1.569184 | 2.802500 |
| BCONF02_L208_S1 | 4 | 1800 | 0.580714 | 0.294908 | 1.520496 | 1.590300 | 2.814871 |
| BCONF02_L208_S1 | 5 | 1800 | 0.708397 | 0.605868 | 1.582310 | 1.682808 | 2.920970 |
| BCONF02_L208_S1 | 6 | 1800 | 0.843013 | 0.778709 | 1.656164 | 1.805241 | 2.935359 |
| BCONF02_L208_S1 | 7 | 1800 | 0.984093 | 0.961358 | 1.724101 | 1.950036 | 3.178884 |
| BCONF02_L192_S1 | 0 | 1800 | 0.096260 | 0.077263 | 0.111270 | 0.770428 | 1.708192 |
| BCONF02_L192_S1 | 1 | 1800 | 0.286682 | 0.131638 | 1.236857 | 1.509955 | 2.601080 |
| BCONF02_L192_S1 | 2 | 1800 | 0.455408 | 0.157475 | 1.511484 | 1.628486 | 2.658260 |
| BCONF02_L192_S1 | 3 | 1800 | 0.633990 | 0.474408 | 1.580072 | 1.735707 | 2.673130 |
| BCONF02_L192_S1 | 4 | 1800 | 0.821287 | 0.792149 | 1.654421 | 1.804947 | 2.687362 |
| BCONF02_L192_S1 | 5 | 1800 | 1.019165 | 1.013446 | 1.726789 | 2.003504 | 2.856469 |
| BCONF02_L192_S1 | 6 | 1800 | 1.175815 | 1.134606 | 2.404814 | 2.927558 | 3.773581 |
| BCONF02_L192_S1 | 7 | 1800 | 1.341811 | 1.249211 | 2.934423 | 3.085278 | 3.916293 |
| BCONF02_L200_A2 | 0 | 1800 | 0.112818 | 0.076068 | 0.235743 | 1.121455 | 2.314596 |
| BCONF02_L200_A2 | 1 | 1800 | 0.280487 | 0.130434 | 1.150953 | 1.564918 | 3.562850 |
| BCONF02_L200_A2 | 2 | 1800 | 0.410168 | 0.145939 | 2.150076 | 2.787798 | 4.888025 |
| BCONF02_L200_A2 | 3 | 1800 | 0.538907 | 0.160481 | 3.165304 | 4.113132 | 6.218431 |
| BCONF02_L200_A2 | 4 | 1800 | 0.673132 | 0.173996 | 4.176205 | 5.550647 | 7.547059 |
| BCONF02_L200_A2 | 5 | 1800 | 0.824784 | 0.187146 | 5.186780 | 7.753436 | 11.750786 |
| BCONF02_L200_A2 | 6 | 1800 | 0.971415 | 0.200266 | 6.625105 | 9.141796 | 13.086359 |
| BCONF02_L200_A2 | 7 | 1800 | 1.104677 | 0.213384 | 7.867415 | 10.479274 | 14.423514 |
| BCONF02_L200_S2 | 0 | 1800 | 0.098058 | 0.076522 | 0.105668 | 0.827364 | 4.550139 |
| BCONF02_L200_S2 | 1 | 1800 | 0.263411 | 0.130814 | 1.139882 | 1.454669 | 4.606408 |
| BCONF02_L200_S2 | 2 | 1800 | 0.404101 | 0.152389 | 1.463752 | 1.546626 | 4.622658 |
| BCONF02_L200_S2 | 3 | 1800 | 0.551070 | 0.224411 | 1.539401 | 1.607697 | 4.638713 |
| BCONF02_L200_S2 | 4 | 1800 | 0.706604 | 0.599190 | 1.598146 | 1.711997 | 4.877204 |
| BCONF02_L200_S2 | 5 | 1800 | 0.872619 | 0.865765 | 1.668434 | 2.036673 | 4.888519 |
| BCONF02_L200_S2 | 6 | 1800 | 1.044912 | 1.035052 | 1.750810 | 2.247180 | 4.898334 |
| BCONF02_L200_S2 | 7 | 1800 | 1.172801 | 1.101021 | 2.228015 | 2.861308 | 4.909250 |
| BCONF02_L208_S2 | 0 | 1800 | 0.100986 | 0.076160 | 0.126025 | 0.900636 | 2.135195 |
| BCONF02_L208_S2 | 1 | 1800 | 0.235581 | 0.129151 | 1.001339 | 1.357510 | 2.820471 |
| BCONF02_L208_S2 | 2 | 1800 | 0.343812 | 0.148356 | 1.364897 | 1.473914 | 2.844258 |
| BCONF02_L208_S2 | 3 | 1800 | 0.459074 | 0.171409 | 1.440111 | 1.620307 | 2.859351 |
| BCONF02_L208_S2 | 4 | 1800 | 0.579575 | 0.287483 | 1.516158 | 1.682012 | 2.872573 |
| BCONF02_L208_S2 | 5 | 1800 | 0.706206 | 0.612318 | 1.580328 | 1.737003 | 2.884832 |
| BCONF02_L208_S2 | 6 | 1800 | 0.840699 | 0.782915 | 1.648069 | 1.863180 | 2.899203 |
| BCONF02_L208_S2 | 7 | 1800 | 0.981881 | 0.958986 | 1.713898 | 1.926182 | 3.384706 |
| BCONF02_L192_S2 | 0 | 1800 | 0.101047 | 0.076163 | 0.129632 | 0.948783 | 2.479677 |
| BCONF02_L192_S2 | 1 | 1800 | 0.293664 | 0.132091 | 1.250162 | 1.498738 | 2.537899 |
| BCONF02_L192_S2 | 2 | 1800 | 0.462275 | 0.158390 | 1.504381 | 1.611292 | 3.705188 |
| BCONF02_L192_S2 | 3 | 1800 | 0.641268 | 0.479546 | 1.593726 | 1.781105 | 3.720993 |
| BCONF02_L192_S2 | 4 | 1800 | 0.830007 | 0.793825 | 1.661112 | 2.081965 | 3.735124 |
| BCONF02_L192_S2 | 5 | 1800 | 1.028513 | 1.015532 | 1.748279 | 2.243039 | 3.748522 |
| BCONF02_L192_S2 | 6 | 1800 | 1.183442 | 1.135001 | 2.423618 | 2.926271 | 3.774309 |
| BCONF02_L192_S2 | 7 | 1800 | 1.348930 | 1.250806 | 2.931714 | 3.078108 | 4.934265 |
| BCONF02_L216_A2 | 0 | 1800 | 0.127154 | 0.076143 | 0.439035 | 1.287761 | 2.266312 |
| BCONF02_L216_A2 | 1 | 1800 | 0.236170 | 0.130196 | 1.033220 | 1.452124 | 2.336886 |
| BCONF02_L216_A2 | 2 | 1800 | 0.311663 | 0.146178 | 1.353701 | 2.394538 | 3.124618 |
| BCONF02_L216_A2 | 3 | 1800 | 0.384805 | 0.160369 | 1.939393 | 3.520084 | 4.256631 |
| BCONF02_L216_A2 | 4 | 1800 | 0.457437 | 0.173816 | 2.535793 | 4.662709 | 5.417594 |
| BCONF02_L216_A2 | 5 | 1800 | 0.539733 | 0.187287 | 3.134585 | 5.986899 | 9.677495 |
| BCONF02_L216_A2 | 6 | 1800 | 0.629568 | 0.200752 | 3.732184 | 7.982971 | 12.065853 |
| BCONF02_L216_A2 | 7 | 1800 | 0.701771 | 0.213763 | 4.331163 | 9.107363 | 13.954997 |
| BCONF02_L200_S3 | 0 | 1800 | 0.093806 | 0.076310 | 0.115579 | 0.651052 | 2.272048 |
| BCONF02_L200_S3 | 1 | 1800 | 0.260357 | 0.131931 | 1.135243 | 1.455491 | 3.068725 |
| BCONF02_L200_S3 | 2 | 1800 | 0.403434 | 0.158122 | 1.463592 | 1.552554 | 3.083901 |
| BCONF02_L200_S3 | 3 | 1800 | 0.552913 | 0.228965 | 1.547553 | 1.791295 | 3.096817 |
| BCONF02_L200_S3 | 4 | 1800 | 0.709084 | 0.583712 | 1.617649 | 1.816645 | 3.625715 |
| BCONF02_L200_S3 | 5 | 1800 | 0.873066 | 0.855614 | 1.682295 | 1.956167 | 3.638974 |
| BCONF02_L200_S3 | 6 | 1800 | 1.045484 | 1.043689 | 1.755959 | 2.049501 | 3.652150 |
| BCONF02_L200_S3 | 7 | 1800 | 1.173521 | 1.106531 | 2.214848 | 2.856178 | 4.146692 |
| BCONF02_L208_S3 | 0 | 1800 | 0.118536 | 0.076422 | 0.299351 | 1.226407 | 4.069256 |
| BCONF02_L208_S3 | 1 | 1800 | 0.255664 | 0.130016 | 1.056300 | 1.530321 | 4.123544 |
| BCONF02_L208_S3 | 2 | 1800 | 0.365200 | 0.149624 | 1.378430 | 1.606921 | 4.139229 |
| BCONF02_L208_S3 | 3 | 1800 | 0.482936 | 0.174636 | 1.476986 | 1.806422 | 4.151498 |
| BCONF02_L208_S3 | 4 | 1800 | 0.605972 | 0.321380 | 1.542861 | 1.955614 | 4.385786 |
| BCONF02_L208_S3 | 5 | 1800 | 0.734979 | 0.640607 | 1.612330 | 2.095593 | 4.396795 |
| BCONF02_L208_S3 | 6 | 1800 | 0.872376 | 0.814966 | 1.685541 | 2.194606 | 4.406675 |
| BCONF02_L208_S3 | 7 | 1800 | 1.015571 | 1.017665 | 1.749526 | 2.320017 | 4.415888 |
| BCONF02_L192_S3 | 0 | 1800 | 0.090847 | 0.076290 | 0.091177 | 0.535625 | 1.913436 |
| BCONF02_L192_S3 | 1 | 1800 | 0.285973 | 0.130130 | 1.241192 | 1.503482 | 3.154061 |
| BCONF02_L192_S3 | 2 | 1800 | 0.456473 | 0.154147 | 1.514694 | 1.651368 | 3.171515 |
| BCONF02_L192_S3 | 3 | 1800 | 0.636295 | 0.479245 | 1.598596 | 1.725667 | 3.186755 |
| BCONF02_L192_S3 | 4 | 1800 | 0.825573 | 0.796293 | 1.655873 | 1.937972 | 3.199061 |
| BCONF02_L192_S3 | 5 | 1800 | 1.022711 | 1.013254 | 1.739296 | 2.060494 | 3.212311 |
| BCONF02_L192_S3 | 6 | 1800 | 1.176968 | 1.141697 | 2.399783 | 2.921234 | 4.391793 |
| BCONF02_L192_S3 | 7 | 1800 | 1.342314 | 1.249472 | 2.921639 | 3.058584 | 4.405895 |
| BCONF02_L216_A3 | 0 | 1800 | 0.137387 | 0.076253 | 0.521507 | 1.301743 | 3.277673 |
| BCONF02_L216_A3 | 1 | 1800 | 0.249741 | 0.131346 | 1.189342 | 1.482166 | 3.337943 |
| BCONF02_L216_A3 | 2 | 1800 | 0.324972 | 0.146708 | 1.349596 | 2.397215 | 3.940890 |
| BCONF02_L216_A3 | 3 | 1800 | 0.398641 | 0.161000 | 1.937302 | 3.527329 | 5.194554 |
| BCONF02_L216_A3 | 4 | 1800 | 0.471646 | 0.174895 | 2.533517 | 4.652008 | 6.409781 |
| BCONF02_L216_A3 | 5 | 1800 | 0.561098 | 0.188242 | 3.132774 | 6.513150 | 9.703982 |
| BCONF02_L216_A3 | 6 | 1800 | 0.653113 | 0.201717 | 3.730907 | 8.433573 | 11.893520 |
| BCONF02_L216_A3 | 7 | 1800 | 0.726209 | 0.215160 | 4.340549 | 9.559344 | 13.032711 |
| BCONF02_L200_A3 | 0 | 1800 | 0.106187 | 0.075546 | 0.177492 | 1.077093 | 2.663616 |
| BCONF02_L200_A3 | 1 | 1800 | 0.270680 | 0.129375 | 1.149845 | 1.489273 | 2.740296 |
| BCONF02_L200_A3 | 2 | 1800 | 0.400280 | 0.144767 | 2.150377 | 2.785097 | 4.062830 |
| BCONF02_L200_A3 | 3 | 1800 | 0.528281 | 0.158564 | 3.158659 | 4.113440 | 5.395947 |
| BCONF02_L200_A3 | 4 | 1800 | 0.661851 | 0.171791 | 4.175645 | 5.523995 | 7.349811 |
| BCONF02_L200_A3 | 5 | 1800 | 0.806279 | 0.184904 | 5.182548 | 7.530364 | 9.622832 |
| BCONF02_L200_A3 | 6 | 1800 | 0.956184 | 0.197705 | 6.623759 | 8.984750 | 10.948811 |
| BCONF02_L200_A3 | 7 | 1800 | 1.092368 | 0.210899 | 7.903218 | 10.308302 | 12.445716 |
| BCONF02_L208_S4 | 0 | 1800 | 0.115810 | 0.077746 | 0.222677 | 1.167808 | 2.511546 |
| BCONF02_L208_S4 | 1 | 1800 | 0.254600 | 0.133580 | 1.136665 | 1.557119 | 2.711379 |
| BCONF02_L208_S4 | 2 | 1800 | 0.368037 | 0.154542 | 1.400790 | 1.745336 | 2.725407 |
| BCONF02_L208_S4 | 3 | 1800 | 0.485839 | 0.181792 | 1.480857 | 2.073244 | 3.070396 |
| BCONF02_L208_S4 | 4 | 1800 | 0.609980 | 0.306028 | 1.570569 | 2.165615 | 3.208235 |
| BCONF02_L208_S4 | 5 | 1800 | 0.742297 | 0.616858 | 1.663824 | 2.268142 | 3.221245 |
| BCONF02_L208_S4 | 6 | 1800 | 0.880614 | 0.807200 | 1.735903 | 2.358384 | 3.234754 |
| BCONF02_L208_S4 | 7 | 1800 | 1.026643 | 0.997846 | 1.826980 | 2.469788 | 3.248217 |
| BCONF02_L192_S4 | 0 | 1800 | 0.103289 | 0.075838 | 0.132656 | 1.028409 | 2.125313 |
| BCONF02_L192_S4 | 1 | 1800 | 0.294003 | 0.129588 | 1.239359 | 1.506506 | 2.670676 |
| BCONF02_L192_S4 | 2 | 1800 | 0.463243 | 0.155704 | 1.512890 | 1.597365 | 2.686352 |
| BCONF02_L192_S4 | 3 | 1800 | 0.640930 | 0.474712 | 1.598490 | 1.876669 | 2.824289 |
| BCONF02_L192_S4 | 4 | 1800 | 0.829098 | 0.796947 | 1.659171 | 2.031428 | 2.838437 |
| BCONF02_L192_S4 | 5 | 1800 | 1.027926 | 1.018336 | 1.744887 | 2.287443 | 3.314060 |
| BCONF02_L192_S4 | 6 | 1800 | 1.183516 | 1.136923 | 2.416607 | 2.938925 | 4.098174 |
| BCONF02_L192_S4 | 7 | 1800 | 1.349440 | 1.257037 | 2.941283 | 3.071870 | 4.110887 |
| BCONF02_L216_A4 | 0 | 1800 | 0.133975 | 0.076158 | 0.460828 | 1.580593 | 3.281467 |
| BCONF02_L216_A4 | 1 | 1800 | 0.241736 | 0.128726 | 1.203444 | 1.645800 | 3.340485 |
| BCONF02_L216_A4 | 2 | 1800 | 0.315659 | 0.143954 | 1.364694 | 2.395912 | 3.357106 |
| BCONF02_L216_A4 | 3 | 1800 | 0.388392 | 0.158199 | 1.938846 | 3.518300 | 3.968656 |
| BCONF02_L216_A4 | 4 | 1800 | 0.460363 | 0.171441 | 2.527780 | 4.646695 | 5.093107 |
| BCONF02_L216_A4 | 5 | 1800 | 0.548348 | 0.184103 | 3.124993 | 6.197469 | 9.708270 |
| BCONF02_L216_A4 | 6 | 1800 | 0.637244 | 0.197192 | 3.731907 | 7.961281 | 10.837165 |
| BCONF02_L216_A4 | 7 | 1800 | 0.709715 | 0.210337 | 4.331387 | 9.085590 | 12.174882 |
| BCONF02_L200_A4 | 0 | 1800 | 0.107448 | 0.076182 | 0.232832 | 0.919901 | 1.823764 |
| BCONF02_L200_A4 | 1 | 1800 | 0.272117 | 0.130707 | 1.140570 | 1.471587 | 2.118461 |
| BCONF02_L200_A4 | 2 | 1800 | 0.401932 | 0.146865 | 2.142417 | 2.777477 | 3.444190 |
| BCONF02_L200_A4 | 3 | 1800 | 0.531764 | 0.161407 | 3.151755 | 4.113978 | 5.075334 |
| BCONF02_L200_A4 | 4 | 1800 | 0.662382 | 0.174885 | 4.167448 | 5.486495 | 6.500675 |
| BCONF02_L200_A4 | 5 | 1800 | 0.813310 | 0.188569 | 5.176620 | 7.510027 | 9.539811 |
| BCONF02_L200_A4 | 6 | 1800 | 0.960945 | 0.201890 | 6.386565 | 9.093270 | 11.819546 |
| BCONF02_L200_A4 | 7 | 1800 | 1.096140 | 0.215081 | 7.852680 | 10.310615 | 12.838682 |
| BCONF02_L200_S4 | 0 | 1800 | 0.089789 | 0.076033 | 0.111598 | 0.360978 | 2.257802 |
| BCONF02_L200_S4 | 1 | 1800 | 0.256234 | 0.131350 | 1.143104 | 1.467237 | 2.311033 |
| BCONF02_L200_S4 | 2 | 1800 | 0.396536 | 0.153413 | 1.469330 | 1.542024 | 2.325728 |
| BCONF02_L200_S4 | 3 | 1800 | 0.546793 | 0.233156 | 1.538488 | 1.632964 | 2.877509 |
| BCONF02_L200_S4 | 4 | 1800 | 0.706754 | 0.597379 | 1.613024 | 1.732270 | 2.892305 |
| BCONF02_L200_S4 | 5 | 1800 | 0.870627 | 0.869200 | 1.681409 | 1.836580 | 3.272649 |
| BCONF02_L200_S4 | 6 | 1800 | 1.044194 | 1.040294 | 1.747151 | 2.164423 | 3.285733 |
| BCONF02_L200_S4 | 7 | 1800 | 1.171669 | 1.105185 | 2.233452 | 2.863072 | 3.299789 |
| BCONF02_L192_S5 | 0 | 1800 | 0.087451 | 0.075072 | 0.095946 | 0.421486 | 1.753026 |
| BCONF02_L192_S5 | 1 | 1800 | 0.278907 | 0.127549 | 1.227847 | 1.495147 | 2.080046 |
| BCONF02_L192_S5 | 2 | 1800 | 0.450768 | 0.156876 | 1.497951 | 1.581226 | 2.972676 |
| BCONF02_L192_S5 | 3 | 1800 | 0.629380 | 0.469276 | 1.578100 | 1.684297 | 2.986379 |
| BCONF02_L192_S5 | 4 | 1800 | 0.817043 | 0.787153 | 1.651118 | 1.846216 | 2.999268 |
| BCONF02_L192_S5 | 5 | 1800 | 1.014329 | 1.013768 | 1.712157 | 1.928881 | 3.011592 |
| BCONF02_L192_S5 | 6 | 1800 | 1.170856 | 1.128373 | 2.400023 | 2.920355 | 3.357929 |
| BCONF02_L192_S5 | 7 | 1800 | 1.337040 | 1.248765 | 2.925766 | 3.044970 | 4.441563 |
| BCONF02_L216_A5 | 0 | 1800 | 0.126476 | 0.076227 | 0.325033 | 1.546218 | 3.361553 |
| BCONF02_L216_A5 | 1 | 1800 | 0.236818 | 0.130711 | 1.089866 | 1.887562 | 3.415924 |
| BCONF02_L216_A5 | 2 | 1800 | 0.310806 | 0.145826 | 1.347869 | 2.400527 | 3.431859 |
| BCONF02_L216_A5 | 3 | 1800 | 0.383571 | 0.160039 | 1.940261 | 3.516581 | 4.383101 |
| BCONF02_L216_A5 | 4 | 1800 | 0.456533 | 0.173559 | 2.540575 | 4.642494 | 5.772211 |
| BCONF02_L216_A5 | 5 | 1800 | 0.534684 | 0.186785 | 3.139078 | 5.941400 | 7.572011 |
| BCONF02_L216_A5 | 6 | 1800 | 0.625907 | 0.200075 | 3.737849 | 7.769044 | 11.487706 |
| BCONF02_L216_A5 | 7 | 1800 | 0.697921 | 0.213313 | 4.336406 | 8.898908 | 12.615462 |
| BCONF02_L200_A5 | 0 | 1800 | 0.111188 | 0.076012 | 0.250461 | 0.962312 | 2.343890 |
| BCONF02_L200_A5 | 1 | 1800 | 0.274272 | 0.128299 | 1.159034 | 1.539302 | 2.655013 |
| BCONF02_L200_A5 | 2 | 1800 | 0.403948 | 0.143457 | 2.151134 | 2.785079 | 3.681464 |
| BCONF02_L200_A5 | 3 | 1800 | 0.533089 | 0.157413 | 3.160202 | 4.127016 | 5.049068 |
| BCONF02_L200_A5 | 4 | 1800 | 0.667067 | 0.170873 | 4.179313 | 5.545490 | 7.604829 |
| BCONF02_L200_A5 | 5 | 1800 | 0.825381 | 0.183893 | 5.190324 | 7.862650 | 13.191319 |
| BCONF02_L200_A5 | 6 | 1800 | 0.975807 | 0.197207 | 6.759592 | 9.406171 | 14.524438 |
| BCONF02_L200_A5 | 7 | 1800 | 1.111056 | 0.210344 | 8.095884 | 10.517373 | 15.857215 |
| BCONF02_L200_S5 | 0 | 1800 | 0.091964 | 0.076604 | 0.119861 | 0.591426 | 1.273193 |
| BCONF02_L200_S5 | 1 | 1800 | 0.257557 | 0.132122 | 1.136552 | 1.452205 | 2.340441 |
| BCONF02_L200_S5 | 2 | 1800 | 0.397073 | 0.153522 | 1.458115 | 1.524885 | 2.355700 |
| BCONF02_L200_S5 | 3 | 1800 | 0.547679 | 0.228373 | 1.532938 | 1.756958 | 2.458509 |
| BCONF02_L200_S5 | 4 | 1800 | 0.702416 | 0.597230 | 1.610774 | 1.785627 | 2.480740 |
| BCONF02_L200_S5 | 5 | 1800 | 0.865817 | 0.860097 | 1.664806 | 1.910006 | 2.494398 |
| BCONF02_L200_S5 | 6 | 1800 | 1.040773 | 1.040726 | 1.750769 | 2.012355 | 2.772915 |
| BCONF02_L200_S5 | 7 | 1800 | 1.168011 | 1.104983 | 2.219950 | 2.841655 | 3.417771 |
| BCONF02_L208_S5 | 0 | 1800 | 0.118446 | 0.076508 | 0.309511 | 1.036843 | 2.229701 |
| BCONF02_L208_S5 | 1 | 1800 | 0.254499 | 0.131534 | 1.025457 | 1.372223 | 2.303350 |
| BCONF02_L208_S5 | 2 | 1800 | 0.363694 | 0.151237 | 1.370750 | 1.609407 | 2.320165 |
| BCONF02_L208_S5 | 3 | 1800 | 0.477999 | 0.176928 | 1.455043 | 1.860224 | 2.379807 |
| BCONF02_L208_S5 | 4 | 1800 | 0.598442 | 0.310328 | 1.530542 | 1.906626 | 3.014615 |
| BCONF02_L208_S5 | 5 | 1800 | 0.728659 | 0.620937 | 1.614010 | 2.193478 | 3.641158 |
| BCONF02_L208_S5 | 6 | 1800 | 0.863017 | 0.804665 | 1.686057 | 2.240830 | 3.655195 |
| BCONF02_L208_S5 | 7 | 1800 | 1.004401 | 0.980965 | 1.744625 | 2.285893 | 3.667806 |

### Initial source slot: exact timestamps

Each vector is in stream ID order 0..K-1; every stream has frame_id=0, logical source_slot=0, scheduled timestamp equal to the common t0. The observed vector is the pre-publication scheduler observation, not exact queue insertion. Warmups remain labeled above.

| Run | common scheduled t0 (ns) | admission_observed_ns vector |
|---|---:|---|
| BCONF02_WARMUP_L200_S | 9828406348739 | [9828406438765, 9828407146420, 9828407177865, 9828407194096, 9828407208189, 9828407222356, 9828407234856, 9828407309894] |
| BCONF02_L216_A1 | 9859976255445 | [9859976339314, 9859976524954, 9859976609649, 9859976687808, 9859976763632, 9859976841494, 9859976917235, 9859976993032] |
| BCONF02_L200_A1 | 9941335579771 | [9941335670407, 9941335845167, 9941335926196, 9941336008984, 9941336083012, 9941336156411, 9941336228827, 9941336301662] |
| BCONF02_L200_S1 | 10025038549137 | [10025038638387, 10025038872223, 10025038892538, 10025038908363, 10025038921705, 10025038953825, 10025038967177, 10025039042789] |
| BCONF02_L208_S1 | 10110299893409 | [10110299984840, 10110300201092, 10110300223907, 10110300240370, 10110300256963, 10110300272501, 10110300287751, 10110300302769] |
| BCONF02_L192_S1 | 10194246604492 | [10194246699009, 10194246875668, 10194246894409, 10194246909705, 10194246923159, 10194246937733, 10194247012984, 10194247025539] |
| BCONF02_L200_A2 | 10280621568745 | [10280621655781, 10280621831883, 10280621913763, 10280621993188, 10280622068874, 10280622143753, 10280622218429, 10280622293141] |
| BCONF02_L200_S2 | 10365005422499 | [10365005515582, 10365005691341, 10365005710387, 10365005726193, 10365005740239, 10365005754591, 10365005768785, 10365005844146] |
| BCONF02_L208_S2 | 10449719021729 | [10449719112267, 10449719307036, 10449719328175, 10449719345008, 10449719359332, 10449719373027, 10449719387739, 10449719401295] |
| BCONF02_L192_S2 | 10533300248854 | [10533300340405, 10533300542498, 10533300563905, 10533300581155, 10533300595776, 10533300610739, 10533300688285, 10533300702239] |
| BCONF02_L216_A2 | 10618953770917 | [10618953855287, 10618954038167, 10618954121380, 10618954196992, 10618954273575, 10618954347557, 10618954421057, 10618954494510] |
| BCONF02_L200_S3 | 10700373193246 | [10700373291617, 10700373505628, 10700373526896, 10700373544248, 10700373558470, 10700373573739, 10700373587544, 10700373663933] |
| BCONF02_L208_S3 | 10784799339113 | [10784799423572, 10784799609850, 10784799628961, 10784799643230, 10784799655600, 10784799668980, 10784799683841, 10784799697794] |
| BCONF02_L192_S3 | 10869117162823 | [10869117254614, 10869117440550, 10869117459940, 10869117474875, 10869117487995, 10869117501078, 10869117577949, 10869117590828] |
| BCONF02_L216_A3 | 10954974742979 | [10954974846011, 10954975070781, 10954975167226, 10954975258374, 10954975333874, 10954975422144, 10954975529653, 10954975606986] |
| BCONF02_L200_A3 | 11036219916535 | [11036220017039, 11036220225957, 11036220314504, 11036220393180, 11036220467967, 11036220544376, 11036220618672, 11036220694459] |
| BCONF02_L208_S4 | 11119908193520 | [11119908282680, 11119908485060, 11119908505830, 11119908522608, 11119908536765, 11119908550765, 11119908564811, 11119908579330] |
| BCONF02_L192_S4 | 11203656020412 | [11203656114537, 11203656302658, 11203656323112, 11203656338825, 11203656352889, 11203656367093, 11203656443742, 11203656456511] |
| BCONF02_L216_A4 | 11289459316240 | [11289459412992, 11289459611456, 11289459694817, 11289459774041, 11289459850254, 11289459925726, 11289460010717, 11289460084356] |
| BCONF02_L200_A4 | 11371012659352 | [11371012754505, 11371012941460, 11371013024590, 11371013101007, 11371013174924, 11371013250332, 11371013322823, 11371013396194] |
| BCONF02_L200_S4 | 11455103807601 | [11455103886653, 11455104080543, 11455104101070, 11455104117459, 11455104131959, 11455104146543, 11455104161303, 11455104237701] |
| BCONF02_L192_S5 | 11539707871782 | [11539707963155, 11539708159054, 11539708178850, 11539708195231, 11539708209592, 11539708223323, 11539708299342, 11539708312731] |
| BCONF02_L216_A5 | 11625516669297 | [11625516751063, 11625516936398, 11625517019833, 11625517097815, 11625517174028, 11625517250908, 11625517326548, 11625517400974] |
| BCONF02_L200_A5 | 11706792447247 | [11706792541092, 11706792725435, 11706792806714, 11706792884770, 11706792958030, 11706793032548, 11706793107910, 11706793180716] |
| BCONF02_L200_S5 | 11790616413038 | [11790616507591, 11790616693564, 11790616712018, 11790616726463, 11790616739648, 11790616753629, 11790616766435, 11790616840936] |
| BCONF02_L208_S5 | 11875356414257 | [11875356502225, 11875356683327, 11875356702188, 11875356717216, 11875356730226, 11875356743642, 11875356756735, 11875356769494] |

### Exact inspected files

| Run | raw frame artifact | manifest | schedule fidelity |
|---|---|---|---|
| BCONF02_WARMUP_L200_S | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_WARMUP_L200_S/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_WARMUP_L200_S/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L216_A1 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_A1 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_S1 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L208_S1 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L192_S1 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_A2 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_S2 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L208_S2 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L192_S2 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L216_A2 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_S3 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L208_S3 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L192_S3 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L216_A3 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_A3 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L208_S4 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L192_S4 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L216_A4 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_A4 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_S4 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L192_S5 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L216_A5 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_A5 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L200_S5 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/manifest.json | UNAVAILABLE: no file produced by this path |
| BCONF02_L208_S5 | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/per_frame.csv.gz | results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/manifest.json | UNAVAILABLE: no file produced by this path |

## edge_e48_confirmation01
Canonical root: results/timely_capacity_campaign/v2_2/edge_e48_confirmation01. Plan SHA-256: b3705e5a34863ac262ff714b4ff031028ec8a9b5a78d8df97338832c869760c3. Measured runs: 13; separately labeled warmup sessions: 1. All 11700 measured slots complete; logical spread mean/p50/p95/max = 0 ns; nonzero, missing, duplicate, unexpected, early-observation and formula-mismatch counts = 0.
Pooled host observation spread mean/p50/p95/p99/max (ms): 0.702847, 0.512566, 3.056999, 3.078850, 3.572453. Pooled lateness mean/p50/p95/p99/max (ms): 0.514355, 0.307609, 1.321567, 2.959385, 5.056172.
### Per-run observation fidelity

Numbers are milliseconds. Mean range and p95 range compare per-stream metrics within that run. Observation ordering is not GPU ordering.

| Run | Scope | K | slots | spread p50 | spread p95 | spread p99 | spread max | first-slot spread | mean range | p95 range | earliest mean sid | latest mean sid | strictly sid-ascending slots |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EDGE48C01_WARMUP_E48_S | WARMUP diagnostic | 8 | 450 | 0.522793 | 0.954325 | 0.982770 | 1.789226 | 0.941678 | 0.680246 | 0.939912 | 0 | 7 | 450 |
| EDGE48C01_E48_A1 | MEASURED | 8 | 900 | 0.041181 | 3.074702 | 3.097180 | 3.206526 | 0.044426 | 0.644383 | 3.059239 | 0 | 7 | 900 |
| EDGE48C01_E48_S1 | MEASURED | 8 | 900 | 0.516737 | 0.947033 | 0.992985 | 1.092307 | 0.950345 | 0.667630 | 0.932865 | 0 | 7 | 900 |
| EDGE48C01_E48_S2 | MEASURED | 8 | 900 | 0.519825 | 0.952457 | 0.995699 | 1.173651 | 0.959752 | 0.669106 | 0.934551 | 0 | 7 | 900 |
| EDGE48C01_E48_A2 | MEASURED | 8 | 900 | 0.042074 | 3.074547 | 3.092114 | 3.572453 | 0.043435 | 0.647126 | 3.051848 | 0 | 7 | 900 |
| EDGE48C01_E48_A3 | MEASURED | 8 | 900 | 0.041315 | 3.071363 | 3.105245 | 3.357629 | 0.042732 | 0.646083 | 3.054302 | 0 | 7 | 900 |
| EDGE48C01_E48_S3 | MEASURED | 8 | 900 | 0.518668 | 0.954060 | 0.988069 | 1.595559 | 0.959307 | 0.667487 | 0.941614 | 0 | 7 | 900 |
| EDGE48C01_E48_S4 | MEASURED | 8 | 900 | 0.512937 | 0.945132 | 0.978919 | 1.552494 | 0.942808 | 0.659666 | 0.937484 | 0 | 7 | 900 |
| EDGE48C01_E48_A4 | MEASURED | 8 | 900 | 0.041528 | 3.070379 | 3.085120 | 3.151812 | 0.044037 | 0.644710 | 3.054793 | 0 | 7 | 900 |
| EDGE48C01_E48_A5 | MEASURED | 8 | 900 | 0.042065 | 3.067924 | 3.081956 | 3.269712 | 0.042834 | 0.644950 | 3.054350 | 0 | 7 | 900 |
| EDGE48C01_E48_S5 | MEASURED | 8 | 900 | 0.521118 | 0.953538 | 0.998641 | 2.808266 | 0.941354 | 0.674395 | 0.938579 | 0 | 7 | 900 |
| EDGE48C01_E64_S1 | MEASURED | 8 | 900 | 0.890488 | 0.920676 | 0.948829 | 1.333846 | 0.942836 | 0.840386 | 0.911843 | 0 | 7 | 900 |
| EDGE48C01_E64_S2 | MEASURED | 8 | 900 | 0.931242 | 0.955255 | 1.003851 | 1.314427 | 0.958454 | 0.870654 | 0.944739 | 0 | 7 | 900 |
| EDGE48C01_E64_S3 | MEASURED | 8 | 900 | 0.897247 | 0.954322 | 0.969089 | 1.249538 | 0.953353 | 0.860441 | 0.945767 | 0 | 7 | 900 |

### Per-stream host release-observation lateness

| Run | stream_id | frames | mean ms | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| EDGE48C01_WARMUP_E48_S | 0 | 450 | 0.191089 | 0.243745 | 0.276143 | 0.300880 | 0.410661 |
| EDGE48C01_WARMUP_E48_S | 1 | 450 | 0.291970 | 0.258205 | 0.738942 | 0.761928 | 0.778864 |
| EDGE48C01_WARMUP_E48_S | 2 | 450 | 0.389099 | 0.275147 | 0.756667 | 0.782975 | 0.791519 |
| EDGE48C01_WARMUP_E48_S | 3 | 450 | 0.487518 | 0.523970 | 0.765879 | 0.788465 | 0.796899 |
| EDGE48C01_WARMUP_E48_S | 4 | 450 | 0.586279 | 0.711607 | 0.774813 | 0.806318 | 0.937028 |
| EDGE48C01_WARMUP_E48_S | 5 | 450 | 0.685107 | 0.744163 | 0.785535 | 0.820864 | 0.943065 |
| EDGE48C01_WARMUP_E48_S | 6 | 450 | 0.779850 | 0.757061 | 1.200095 | 1.218405 | 2.029878 |
| EDGE48C01_WARMUP_E48_S | 7 | 450 | 0.871335 | 0.779957 | 1.216055 | 1.257121 | 2.041378 |
| EDGE48C01_E48_A1 | 0 | 900 | 0.170923 | 0.112931 | 0.290474 | 0.312236 | 2.204202 |
| EDGE48C01_E48_A1 | 1 | 900 | 0.271110 | 0.259888 | 0.764686 | 0.794506 | 2.212174 |
| EDGE48C01_E48_A1 | 2 | 900 | 0.362798 | 0.265908 | 1.197916 | 1.227456 | 2.217684 |
| EDGE48C01_E48_A1 | 3 | 900 | 0.453435 | 0.271542 | 1.627625 | 1.657905 | 2.223091 |
| EDGE48C01_E48_A1 | 4 | 900 | 0.543930 | 0.276965 | 2.056743 | 2.086780 | 2.228434 |
| EDGE48C01_E48_A1 | 5 | 900 | 0.635408 | 0.282491 | 2.493493 | 2.518422 | 2.553207 |
| EDGE48C01_E48_A1 | 6 | 900 | 0.725680 | 0.287644 | 2.923327 | 2.947789 | 2.983875 |
| EDGE48C01_E48_A1 | 7 | 900 | 0.815307 | 0.292797 | 3.349714 | 3.373257 | 3.409561 |
| EDGE48C01_E48_S1 | 0 | 900 | 0.160264 | 0.111745 | 0.284247 | 0.304237 | 0.552206 |
| EDGE48C01_E48_S1 | 1 | 900 | 0.260491 | 0.250226 | 0.744229 | 0.774038 | 1.135772 |
| EDGE48C01_E48_S1 | 2 | 900 | 0.356940 | 0.277861 | 0.762829 | 0.783698 | 1.142958 |
| EDGE48C01_E48_S1 | 3 | 900 | 0.452973 | 0.513910 | 0.771601 | 0.791052 | 1.148819 |
| EDGE48C01_E48_S1 | 4 | 900 | 0.548694 | 0.539246 | 0.778586 | 0.797413 | 1.154671 |
| EDGE48C01_E48_S1 | 5 | 900 | 0.646160 | 0.612270 | 0.787955 | 0.828849 | 1.161189 |
| EDGE48C01_E48_S1 | 6 | 900 | 0.736921 | 0.744452 | 1.198906 | 1.230175 | 1.616663 |
| EDGE48C01_E48_S1 | 7 | 900 | 0.827893 | 0.774649 | 1.217112 | 1.243247 | 1.622061 |
| EDGE48C01_E48_S2 | 0 | 900 | 0.153426 | 0.111357 | 0.278595 | 0.298142 | 1.281146 |
| EDGE48C01_E48_S2 | 1 | 900 | 0.252954 | 0.145433 | 0.737200 | 0.767324 | 1.287516 |
| EDGE48C01_E48_S2 | 2 | 900 | 0.349003 | 0.273578 | 0.751889 | 0.776821 | 1.292646 |
| EDGE48C01_E48_S2 | 3 | 900 | 0.445634 | 0.514528 | 0.764263 | 0.784019 | 1.297859 |
| EDGE48C01_E48_S2 | 4 | 900 | 0.541881 | 0.540631 | 0.773413 | 0.795830 | 1.741184 |
| EDGE48C01_E48_S2 | 5 | 900 | 0.639974 | 0.609666 | 0.786375 | 0.813939 | 1.746489 |
| EDGE48C01_E48_S2 | 6 | 900 | 0.731560 | 0.648381 | 1.196688 | 1.234247 | 1.751823 |
| EDGE48C01_E48_S2 | 7 | 900 | 0.822532 | 0.775227 | 1.213146 | 1.255874 | 1.756999 |
| EDGE48C01_E48_A2 | 0 | 900 | 0.199639 | 0.254316 | 0.296978 | 0.429623 | 0.515969 |
| EDGE48C01_E48_A2 | 1 | 900 | 0.302842 | 0.269328 | 0.762736 | 0.792575 | 1.100203 |
| EDGE48C01_E48_A2 | 2 | 900 | 0.394901 | 0.275159 | 1.202022 | 1.232419 | 1.555055 |
| EDGE48C01_E48_A2 | 3 | 900 | 0.485276 | 0.280552 | 1.632218 | 1.662393 | 1.989899 |
| EDGE48C01_E48_A2 | 4 | 900 | 0.575684 | 0.286173 | 2.060546 | 2.092293 | 2.455391 |
| EDGE48C01_E48_A2 | 5 | 900 | 0.667208 | 0.291552 | 2.492778 | 2.530608 | 2.916783 |
| EDGE48C01_E48_A2 | 6 | 900 | 0.757312 | 0.296900 | 2.921988 | 2.959331 | 3.354201 |
| EDGE48C01_E48_A2 | 7 | 900 | 0.846765 | 0.302158 | 3.348826 | 3.385121 | 3.833388 |
| EDGE48C01_E48_A3 | 0 | 900 | 0.178455 | 0.129329 | 0.291130 | 0.317032 | 2.073873 |
| EDGE48C01_E48_A3 | 1 | 900 | 0.280591 | 0.259195 | 0.760263 | 0.795558 | 2.081012 |
| EDGE48C01_E48_A3 | 2 | 900 | 0.372744 | 0.264798 | 1.198597 | 1.228919 | 2.086559 |
| EDGE48C01_E48_A3 | 3 | 900 | 0.463396 | 0.270123 | 1.630802 | 1.670021 | 2.091836 |
| EDGE48C01_E48_A3 | 4 | 900 | 0.553830 | 0.275331 | 2.057145 | 2.099304 | 2.470383 |
| EDGE48C01_E48_A3 | 5 | 900 | 0.645186 | 0.280720 | 2.491404 | 2.529848 | 2.901690 |
| EDGE48C01_E48_A3 | 6 | 900 | 0.735219 | 0.285978 | 2.920502 | 2.959686 | 3.335256 |
| EDGE48C01_E48_A3 | 7 | 900 | 0.824538 | 0.291324 | 3.345431 | 3.385174 | 3.780895 |
| EDGE48C01_E48_S3 | 0 | 900 | 0.145059 | 0.079119 | 0.272206 | 0.298863 | 1.325784 |
| EDGE48C01_E48_S3 | 1 | 900 | 0.244388 | 0.123420 | 0.738667 | 0.786521 | 1.804489 |
| EDGE48C01_E48_S3 | 2 | 900 | 0.341205 | 0.264803 | 0.755317 | 0.805066 | 1.818664 |
| EDGE48C01_E48_S3 | 3 | 900 | 0.436578 | 0.512280 | 0.765902 | 0.813251 | 1.824266 |
| EDGE48C01_E48_S3 | 4 | 900 | 0.532677 | 0.534947 | 0.775796 | 0.842811 | 1.829674 |
| EDGE48C01_E48_S3 | 5 | 900 | 0.629690 | 0.558137 | 0.784306 | 0.890149 | 1.834868 |
| EDGE48C01_E48_S3 | 6 | 900 | 0.720971 | 0.626439 | 1.195591 | 1.263455 | 2.267869 |
| EDGE48C01_E48_S3 | 7 | 900 | 0.812546 | 0.768881 | 1.213820 | 1.269150 | 2.273425 |
| EDGE48C01_E48_S4 | 0 | 900 | 0.137051 | 0.078130 | 0.274924 | 0.345385 | 0.657802 |
| EDGE48C01_E48_S4 | 1 | 900 | 0.234950 | 0.120390 | 0.732665 | 0.763773 | 1.534609 |
| EDGE48C01_E48_S4 | 2 | 900 | 0.329866 | 0.271556 | 0.754771 | 0.773406 | 1.547072 |
| EDGE48C01_E48_S4 | 3 | 900 | 0.424510 | 0.510636 | 0.764192 | 0.798042 | 1.555248 |
| EDGE48C01_E48_S4 | 4 | 900 | 0.519074 | 0.525322 | 0.771777 | 0.804680 | 1.563350 |
| EDGE48C01_E48_S4 | 5 | 900 | 0.614283 | 0.541416 | 0.780432 | 0.883593 | 1.569896 |
| EDGE48C01_E48_S4 | 6 | 900 | 0.705937 | 0.613921 | 1.190540 | 1.221844 | 2.203204 |
| EDGE48C01_E48_S4 | 7 | 900 | 0.796717 | 0.767249 | 1.212408 | 1.249749 | 2.210296 |
| EDGE48C01_E48_A4 | 0 | 900 | 0.169069 | 0.125698 | 0.292742 | 0.310143 | 0.686431 |
| EDGE48C01_E48_A4 | 1 | 900 | 0.270869 | 0.256827 | 0.760087 | 0.780846 | 0.795868 |
| EDGE48C01_E48_A4 | 2 | 900 | 0.361815 | 0.262487 | 1.191702 | 1.214815 | 1.295363 |
| EDGE48C01_E48_A4 | 3 | 900 | 0.452794 | 0.267741 | 1.629834 | 1.651517 | 1.729123 |
| EDGE48C01_E48_A4 | 4 | 900 | 0.543192 | 0.273150 | 2.059771 | 2.082302 | 2.161559 |
| EDGE48C01_E48_A4 | 5 | 900 | 0.633590 | 0.278513 | 2.489346 | 2.512644 | 2.593412 |
| EDGE48C01_E48_A4 | 6 | 900 | 0.724151 | 0.283979 | 2.922136 | 2.950227 | 3.036191 |
| EDGE48C01_E48_A4 | 7 | 900 | 0.813779 | 0.289399 | 3.347535 | 3.375868 | 3.461951 |
| EDGE48C01_E48_A5 | 0 | 900 | 0.184443 | 0.245654 | 0.291544 | 0.312633 | 2.034054 |
| EDGE48C01_E48_A5 | 1 | 900 | 0.287049 | 0.263865 | 0.763420 | 0.793837 | 2.483111 |
| EDGE48C01_E48_A5 | 2 | 900 | 0.378349 | 0.269814 | 1.199147 | 1.227952 | 2.911102 |
| EDGE48C01_E48_A5 | 3 | 900 | 0.468720 | 0.275342 | 1.628956 | 1.660738 | 3.337705 |
| EDGE48C01_E48_A5 | 4 | 900 | 0.558831 | 0.280759 | 2.059160 | 2.088148 | 3.763632 |
| EDGE48C01_E48_A5 | 5 | 900 | 0.649559 | 0.286237 | 2.491549 | 2.523366 | 4.202013 |
| EDGE48C01_E48_A5 | 6 | 900 | 0.740032 | 0.291673 | 2.921194 | 2.953166 | 4.630403 |
| EDGE48C01_E48_A5 | 7 | 900 | 0.829394 | 0.296955 | 3.345894 | 3.378117 | 5.056172 |
| EDGE48C01_E48_S5 | 0 | 900 | 0.185617 | 0.241568 | 0.280184 | 0.410951 | 1.434581 |
| EDGE48C01_E48_S5 | 1 | 900 | 0.285845 | 0.257403 | 0.748632 | 0.782737 | 1.441109 |
| EDGE48C01_E48_S5 | 2 | 900 | 0.382700 | 0.280270 | 0.761122 | 0.806734 | 1.885276 |
| EDGE48C01_E48_S5 | 3 | 900 | 0.479928 | 0.515819 | 0.771654 | 0.837167 | 1.890767 |
| EDGE48C01_E48_S5 | 4 | 900 | 0.576293 | 0.560124 | 0.779947 | 0.842720 | 1.896147 |
| EDGE48C01_E48_S5 | 5 | 900 | 0.674431 | 0.742155 | 0.788304 | 0.993081 | 1.901323 |
| EDGE48C01_E48_S5 | 6 | 900 | 0.766198 | 0.756849 | 1.208402 | 1.253609 | 1.906452 |
| EDGE48C01_E48_S5 | 7 | 900 | 0.860012 | 0.782628 | 1.218762 | 1.345860 | 2.881618 |
| EDGE48C01_E64_S1 | 0 | 900 | 0.073953 | 0.065112 | 0.091006 | 0.245881 | 1.811723 |
| EDGE48C01_E64_S1 | 1 | 900 | 0.194641 | 0.072392 | 0.507451 | 0.666192 | 1.822214 |
| EDGE48C01_E64_S1 | 2 | 900 | 0.314723 | 0.498964 | 0.525032 | 0.720752 | 2.298613 |
| EDGE48C01_E64_S1 | 3 | 900 | 0.434994 | 0.507638 | 0.541185 | 0.733214 | 2.304493 |
| EDGE48C01_E64_S1 | 4 | 900 | 0.555566 | 0.514887 | 0.943182 | 0.953334 | 2.310335 |
| EDGE48C01_E64_S1 | 5 | 900 | 0.675090 | 0.525545 | 0.963547 | 1.111925 | 2.742790 |
| EDGE48C01_E64_S1 | 6 | 900 | 0.794344 | 0.945312 | 0.979887 | 1.174151 | 2.748781 |
| EDGE48C01_E64_S1 | 7 | 900 | 0.914338 | 0.955953 | 1.002849 | 1.186439 | 2.754559 |
| EDGE48C01_E64_S2 | 0 | 900 | 0.168976 | 0.132114 | 0.277445 | 0.289034 | 1.937836 |
| EDGE48C01_E64_S2 | 1 | 900 | 0.298413 | 0.257807 | 0.741008 | 0.762792 | 2.411493 |
| EDGE48C01_E64_S2 | 2 | 900 | 0.426437 | 0.503715 | 0.760806 | 0.781605 | 2.418188 |
| EDGE48C01_E64_S2 | 3 | 900 | 0.554516 | 0.558492 | 0.769360 | 0.790159 | 2.423993 |
| EDGE48C01_E64_S2 | 4 | 900 | 0.679668 | 0.729923 | 0.969666 | 1.190785 | 2.855678 |
| EDGE48C01_E64_S2 | 5 | 900 | 0.799977 | 0.755340 | 1.199342 | 1.219369 | 2.861679 |
| EDGE48C01_E64_S2 | 6 | 900 | 0.919614 | 0.956230 | 1.212154 | 1.246366 | 2.867411 |
| EDGE48C01_E64_S2 | 7 | 900 | 1.039630 | 1.046835 | 1.222184 | 1.262104 | 2.873040 |
| EDGE48C01_E64_S3 | 0 | 900 | 0.134830 | 0.075335 | 0.273267 | 0.285896 | 0.349906 |
| EDGE48C01_E64_S3 | 1 | 900 | 0.261838 | 0.235801 | 0.727355 | 0.753231 | 0.763310 |
| EDGE48C01_E64_S3 | 2 | 900 | 0.386661 | 0.503751 | 0.749811 | 0.767646 | 0.821289 |
| EDGE48C01_E64_S3 | 3 | 900 | 0.511771 | 0.519206 | 0.763058 | 0.778733 | 0.855152 |
| EDGE48C01_E64_S3 | 4 | 900 | 0.635489 | 0.542504 | 0.944606 | 1.183973 | 1.209967 |
| EDGE48C01_E64_S3 | 5 | 900 | 0.755419 | 0.747561 | 1.190267 | 1.213007 | 1.246414 |
| EDGE48C01_E64_S3 | 6 | 900 | 0.875143 | 0.952848 | 1.208994 | 1.228816 | 1.282058 |
| EDGE48C01_E64_S3 | 7 | 900 | 0.995271 | 0.968911 | 1.219033 | 1.250020 | 1.573329 |

### Initial source slot: exact timestamps

Each vector is in stream ID order 0..K-1; every stream has frame_id=0, logical source_slot=0, scheduled timestamp equal to the common t0. The observed vector is the pre-publication scheduler observation, not exact queue insertion. Warmups remain labeled above.

| Run | common scheduled t0 (ns) | admission_observed_ns vector |
|---|---:|---|
| EDGE48C01_WARMUP_E48_S | 42582238529641 | [42582238831024, 42582238843950, 42582239316618, 42582239322164, 42582239327673, 42582239333266, 42582239338655, 42582239772702] |
| EDGE48C01_E48_A1 | 42609300521230 | [42609300797600, 42609300807906, 42609300814239, 42609300819665, 42609300825397, 42609300831295, 42609300836517, 42609300842026] |
| EDGE48C01_E48_S1 | 42650450403301 | [42650450686056, 42650450696575, 42650451182779, 42650451188131, 42650451193751, 42650451199326, 42650451204705, 42650451636401] |
| EDGE48C01_E48_S2 | 42691511496643 | [42691511794312, 42691511804701, 42691512301017, 42691512306480, 42691512312082, 42691512317610, 42691512323008, 42691512754064] |
| EDGE48C01_E48_A2 | 42732589718060 | [42732589991833, 42732590001917, 42732590007796, 42732590013204, 42732590018944, 42732590024722, 42732590029870, 42732590035268] |
| EDGE48C01_E48_A3 | 42773712524308 | [42773712793440, 42773712803765, 42773712809542, 42773712815024, 42773712820163, 42773712825931, 42773712830978, 42773712836172] |
| EDGE48C01_E48_S3 | 42814819525739 | [42814819783602, 42814819793296, 42814820289705, 42814820295260, 42814820301066, 42814820306816, 42814820312612, 42814820742909] |
| EDGE48C01_E48_S4 | 42855854603400 | [42855854719034, 42855854730108, 42855855207609, 42855855213359, 42855855219146, 42855855224674, 42855855230276, 42855855661842] |
| EDGE48C01_E48_A4 | 42896877163031 | [42896877287613, 42896877297910, 42896877303836, 42896877309336, 42896877315141, 42896877320993, 42896877326169, 42896877331650] |
| EDGE48C01_E48_A5 | 42937994870625 | [42937994982960, 42937994992747, 42937994998618, 42937995003997, 42937995009664, 42937995015229, 42937995020377, 42937995025794] |
| EDGE48C01_E48_S5 | 42979122103427 | [42979122414527, 42979122424536, 42979122902630, 42979122908167, 42979122913778, 42979122919472, 42979122925046, 42979123355881] |
| EDGE48C01_E64_S1 | 43020180431457 | [43020182243180, 43020182253671, 43020182730070, 43020182735950, 43020182741792, 43020183174247, 43020183180238, 43020183186016] |
| EDGE48C01_E64_S2 | 43061215599154 | [43061215845647, 43061215855276, 43061216348628, 43061216354563, 43061216360832, 43061216792518, 43061216798564, 43061216804101] |
| EDGE48C01_E64_S3 | 43102281567189 | [43102281850852, 43102281861954, 43102282347806, 43102282353593, 43102282360093, 43102282792631, 43102282798575, 43102282804205] |

### Exact inspected files

| Run | raw frame artifact | manifest | schedule fidelity |
|---|---|---|---|
| EDGE48C01_WARMUP_E48_S | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_WARMUP_E48_S/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_WARMUP_E48_S/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_WARMUP_E48_S/schedule_fidelity.json |
| EDGE48C01_E48_A1 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/schedule_fidelity.json |
| EDGE48C01_E48_S1 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/schedule_fidelity.json |
| EDGE48C01_E48_S2 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/schedule_fidelity.json |
| EDGE48C01_E48_A2 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/schedule_fidelity.json |
| EDGE48C01_E48_A3 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/schedule_fidelity.json |
| EDGE48C01_E48_S3 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/schedule_fidelity.json |
| EDGE48C01_E48_S4 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/schedule_fidelity.json |
| EDGE48C01_E48_A4 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/schedule_fidelity.json |
| EDGE48C01_E48_A5 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/schedule_fidelity.json |
| EDGE48C01_E48_S5 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/schedule_fidelity.json |
| EDGE48C01_E64_S1 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/schedule_fidelity.json |
| EDGE48C01_E64_S2 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/schedule_fidelity.json |
| EDGE48C01_E64_S3 | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/manifest.json | results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/schedule_fidelity.json |

## edge_order_robustness01
Canonical root: results/timely_capacity_campaign/v2_2/edge_order_robustness01. Plan SHA-256: 233370402d62b9d185710ef664b6a03c730fa3f72a3784fa86fc9ac59710c727. Measured runs: 15; separately labeled warmup sessions: 1. All 13500 measured slots complete; logical spread mean/p50/p95/max = 0 ns; nonzero, missing, duplicate, unexpected, early-observation and formula-mismatch counts = 0.
Pooled host observation spread mean/p50/p95/p99/max (ms): 0.660457, 0.040223, 3.141121, 3.180846, 5.308777. Pooled lateness mean/p50/p95/p99/max (ms): 0.518391, 0.269926, 2.707073, 3.413911, 7.343049.
### Per-run observation fidelity

Numbers are milliseconds. Mean range and p95 range compare per-stream metrics within that run. Observation ordering is not GPU ordering.

| Run | Scope | K | slots | spread p50 | spread p95 | spread p99 | spread max | first-slot spread | mean range | p95 range | earliest mean sid | latest mean sid | strictly sid-ascending slots |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EDGEORDER01_WARMUP_E48_S | WARMUP diagnostic | 8 | 450 | 0.525572 | 0.965850 | 1.013075 | 1.183256 | 0.946910 | 0.680558 | 0.953145 | 0 | 7 | 450 |
| EDGEORDER01_E48_BASE1 | MEASURED | 8 | 900 | 0.040357 | 3.143203 | 3.176152 | 3.631472 | 0.042176 | 0.659643 | 3.122808 | 0 | 7 | 900 |
| EDGEORDER01_E48_REV1 | MEASURED | 8 | 900 | 0.039435 | 3.137616 | 3.206990 | 4.881552 | 0.042316 | 0.598122 | 3.078770 | 7 | 0 | 720 |
| EDGEORDER01_E48_ROT1 | MEASURED | 8 | 900 | 0.039871 | 3.133897 | 3.160316 | 4.351230 | 0.041955 | 0.032890 | 0.150039 | 0 | 7 | 743 |
| EDGEORDER01_E48_REV2 | MEASURED | 8 | 900 | 0.039940 | 3.142355 | 3.173760 | 5.047553 | 0.040612 | 0.599320 | 3.095165 | 7 | 0 | 720 |
| EDGEORDER01_E48_ROT2 | MEASURED | 8 | 900 | 0.038560 | 3.134310 | 3.202917 | 3.797020 | 0.042592 | 0.032934 | 0.145436 | 0 | 7 | 743 |
| EDGEORDER01_E48_BASE2 | MEASURED | 8 | 900 | 0.040514 | 3.140499 | 3.163445 | 3.774455 | 0.041472 | 0.661875 | 3.124618 | 0 | 7 | 900 |
| EDGEORDER01_E48_ROT3 | MEASURED | 8 | 900 | 0.040768 | 3.138925 | 3.181547 | 3.516016 | 0.042130 | 0.034222 | 0.307729 | 0 | 7 | 743 |
| EDGEORDER01_E48_BASE3 | MEASURED | 8 | 900 | 0.040177 | 3.140637 | 3.224774 | 5.308777 | 0.042287 | 0.666586 | 3.116877 | 0 | 7 | 900 |
| EDGEORDER01_E48_REV3 | MEASURED | 8 | 900 | 0.039890 | 3.139883 | 3.154238 | 4.284459 | 0.043038 | 0.595515 | 3.084562 | 7 | 0 | 720 |
| EDGEORDER01_E48_BASE4 | MEASURED | 8 | 900 | 0.041111 | 3.142484 | 3.173991 | 3.802157 | 0.042602 | 0.661427 | 3.128802 | 0 | 7 | 900 |
| EDGEORDER01_E48_ROT4 | MEASURED | 8 | 900 | 0.039899 | 3.135748 | 3.153406 | 3.366411 | 0.042778 | 0.032987 | 0.186369 | 0 | 7 | 743 |
| EDGEORDER01_E48_REV4 | MEASURED | 8 | 900 | 0.040473 | 3.145726 | 3.207554 | 4.038484 | 0.041344 | 0.597668 | 3.089198 | 7 | 0 | 720 |
| EDGEORDER01_E48_ROT5 | MEASURED | 8 | 900 | 0.040779 | 3.141706 | 3.163606 | 4.400061 | 0.042640 | 0.034036 | 0.159019 | 0 | 7 | 743 |
| EDGEORDER01_E48_REV5 | MEASURED | 8 | 900 | 0.039718 | 3.144879 | 3.180366 | 5.162255 | 0.042880 | 0.599147 | 3.097900 | 7 | 0 | 720 |
| EDGEORDER01_E48_BASE5 | MEASURED | 8 | 900 | 0.041061 | 3.148267 | 3.199184 | 4.163438 | 0.043029 | 0.662358 | 3.118055 | 0 | 7 | 900 |

### Per-stream host release-observation lateness

| Run | stream_id | frames | mean ms | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| EDGEORDER01_WARMUP_E48_S | 0 | 450 | 0.202022 | 0.246210 | 0.283356 | 0.446470 | 1.802747 |
| EDGEORDER01_WARMUP_E48_S | 1 | 450 | 0.303872 | 0.260576 | 0.745334 | 0.782508 | 1.813191 |
| EDGEORDER01_WARMUP_E48_S | 2 | 450 | 0.401574 | 0.279473 | 0.765806 | 0.791784 | 1.819089 |
| EDGEORDER01_WARMUP_E48_S | 3 | 450 | 0.499064 | 0.530717 | 0.774525 | 0.816320 | 2.293317 |
| EDGEORDER01_WARMUP_E48_S | 4 | 450 | 0.597266 | 0.727693 | 0.784081 | 0.941580 | 2.299558 |
| EDGEORDER01_WARMUP_E48_S | 5 | 450 | 0.696691 | 0.749038 | 0.794276 | 1.040305 | 2.306419 |
| EDGEORDER01_WARMUP_E48_S | 6 | 450 | 0.789791 | 0.761741 | 1.212407 | 1.281273 | 2.311393 |
| EDGEORDER01_WARMUP_E48_S | 7 | 450 | 0.882580 | 0.786232 | 1.236501 | 1.296408 | 2.316309 |
| EDGEORDER01_E48_BASE1 | 0 | 900 | 0.178930 | 0.135146 | 0.301804 | 0.363221 | 0.844573 |
| EDGEORDER01_E48_BASE1 | 1 | 900 | 0.283002 | 0.266105 | 0.775706 | 0.809098 | 1.613370 |
| EDGEORDER01_E48_BASE1 | 2 | 900 | 0.376641 | 0.271588 | 1.225503 | 1.254466 | 2.067560 |
| EDGEORDER01_E48_BASE1 | 3 | 900 | 0.469658 | 0.276809 | 1.668390 | 1.697441 | 2.506974 |
| EDGEORDER01_E48_BASE1 | 4 | 900 | 0.562105 | 0.281979 | 2.106703 | 2.136179 | 2.947554 |
| EDGEORDER01_E48_BASE1 | 5 | 900 | 0.654685 | 0.287558 | 2.552368 | 2.588738 | 3.390976 |
| EDGEORDER01_E48_BASE1 | 6 | 900 | 0.747490 | 0.292775 | 2.989261 | 3.026314 | 3.831287 |
| EDGEORDER01_E48_BASE1 | 7 | 900 | 0.838572 | 0.297768 | 3.424612 | 3.460281 | 4.269320 |
| EDGEORDER01_E48_REV1 | 0 | 900 | 0.814043 | 0.251785 | 3.408717 | 3.461611 | 4.953890 |
| EDGEORDER01_E48_REV1 | 1 | 900 | 0.730843 | 0.260236 | 2.973799 | 3.007508 | 3.905196 |
| EDGEORDER01_E48_REV1 | 2 | 900 | 0.647074 | 0.265541 | 2.535018 | 2.568841 | 3.467959 |
| EDGEORDER01_E48_REV1 | 3 | 900 | 0.562737 | 0.270606 | 2.091763 | 2.129154 | 3.023231 |
| EDGEORDER01_E48_REV1 | 4 | 900 | 0.478946 | 0.275722 | 1.653729 | 1.692425 | 2.585022 |
| EDGEORDER01_E48_REV1 | 5 | 900 | 0.394459 | 0.280791 | 1.210691 | 1.243015 | 2.136229 |
| EDGEORDER01_E48_REV1 | 6 | 900 | 0.309446 | 0.286029 | 0.765603 | 0.797790 | 1.956483 |
| EDGEORDER01_E48_REV1 | 7 | 900 | 0.215920 | 0.258348 | 0.329947 | 0.462107 | 1.963844 |
| EDGEORDER01_E48_ROT1 | 0 | 900 | 0.509277 | 0.252645 | 2.722305 | 3.403886 | 3.447087 |
| EDGEORDER01_E48_ROT1 | 1 | 900 | 0.514795 | 0.261627 | 2.709941 | 3.421483 | 3.984609 |
| EDGEORDER01_E48_ROT1 | 2 | 900 | 0.517082 | 0.266515 | 2.715912 | 3.415109 | 4.433632 |
| EDGEORDER01_E48_ROT1 | 3 | 900 | 0.517912 | 0.271545 | 2.590718 | 3.408226 | 3.474368 |
| EDGEORDER01_E48_ROT1 | 4 | 900 | 0.523967 | 0.276658 | 2.712062 | 3.424958 | 3.732389 |
| EDGEORDER01_E48_ROT1 | 5 | 900 | 0.529927 | 0.281656 | 2.709720 | 3.419050 | 3.728219 |
| EDGEORDER01_E48_ROT1 | 6 | 900 | 0.536495 | 0.286671 | 2.572267 | 3.406706 | 3.864084 |
| EDGEORDER01_E48_ROT1 | 7 | 900 | 0.542167 | 0.291519 | 2.705370 | 3.413721 | 4.299811 |
| EDGEORDER01_E48_REV2 | 0 | 900 | 0.828745 | 0.255495 | 3.422949 | 3.462479 | 7.300929 |
| EDGEORDER01_E48_REV2 | 1 | 900 | 0.747847 | 0.264338 | 2.988691 | 3.028741 | 7.309836 |
| EDGEORDER01_E48_REV2 | 2 | 900 | 0.664301 | 0.269780 | 2.550928 | 2.591976 | 7.315466 |
| EDGEORDER01_E48_REV2 | 3 | 900 | 0.577640 | 0.275027 | 2.107612 | 2.141523 | 7.320753 |
| EDGEORDER01_E48_REV2 | 4 | 900 | 0.493679 | 0.280139 | 1.667673 | 1.700168 | 7.326355 |
| EDGEORDER01_E48_REV2 | 5 | 900 | 0.409319 | 0.285154 | 1.227242 | 1.259826 | 7.331901 |
| EDGEORDER01_E48_REV2 | 6 | 900 | 0.323724 | 0.290428 | 0.777515 | 0.803463 | 7.337290 |
| EDGEORDER01_E48_REV2 | 7 | 900 | 0.229424 | 0.273656 | 0.327784 | 0.492157 | 7.343049 |
| EDGEORDER01_E48_ROT2 | 0 | 900 | 0.462842 | 0.084713 | 2.696655 | 3.402453 | 5.438707 |
| EDGEORDER01_E48_ROT2 | 1 | 900 | 0.465513 | 0.091554 | 2.694584 | 3.385268 | 3.448554 |
| EDGEORDER01_E48_ROT2 | 2 | 900 | 0.467975 | 0.096378 | 2.572319 | 3.397270 | 3.677903 |
| EDGEORDER01_E48_ROT2 | 3 | 900 | 0.470051 | 0.101607 | 2.558204 | 3.385613 | 3.431445 |
| EDGEORDER01_E48_ROT2 | 4 | 900 | 0.476771 | 0.107080 | 2.578376 | 3.257614 | 3.437364 |
| EDGEORDER01_E48_ROT2 | 5 | 900 | 0.482780 | 0.111861 | 2.698884 | 3.398103 | 3.577860 |
| EDGEORDER01_E48_ROT2 | 6 | 900 | 0.489346 | 0.117847 | 2.694605 | 3.329717 | 3.978837 |
| EDGEORDER01_E48_ROT2 | 7 | 900 | 0.495776 | 0.122487 | 2.703640 | 3.407910 | 4.451343 |
| EDGEORDER01_E48_BASE2 | 0 | 900 | 0.211600 | 0.257615 | 0.298673 | 0.329825 | 0.615083 |
| EDGEORDER01_E48_BASE2 | 1 | 900 | 0.317573 | 0.267562 | 0.781806 | 0.811196 | 1.131905 |
| EDGEORDER01_E48_BASE2 | 2 | 900 | 0.410936 | 0.272998 | 1.222989 | 1.252646 | 1.800999 |
| EDGEORDER01_E48_BASE2 | 3 | 900 | 0.504280 | 0.278262 | 1.670711 | 1.698844 | 2.258487 |
| EDGEORDER01_E48_BASE2 | 4 | 900 | 0.596711 | 0.283564 | 2.110950 | 2.137093 | 2.706279 |
| EDGEORDER01_E48_BASE2 | 5 | 900 | 0.689333 | 0.289048 | 2.550989 | 2.581499 | 3.160868 |
| EDGEORDER01_E48_BASE2 | 6 | 900 | 0.781817 | 0.297664 | 2.988825 | 3.021302 | 3.600883 |
| EDGEORDER01_E48_BASE2 | 7 | 900 | 0.873475 | 0.303156 | 3.423291 | 3.456167 | 4.036185 |
| EDGEORDER01_E48_ROT3 | 0 | 900 | 0.545643 | 0.264022 | 2.842473 | 3.427862 | 3.861980 |
| EDGEORDER01_E48_ROT3 | 1 | 900 | 0.550451 | 0.273184 | 2.760844 | 3.428575 | 3.854179 |
| EDGEORDER01_E48_ROT3 | 2 | 900 | 0.552786 | 0.278343 | 2.814044 | 3.423595 | 3.474616 |
| EDGEORDER01_E48_ROT3 | 3 | 900 | 0.555129 | 0.283299 | 2.876233 | 3.426204 | 3.597763 |
| EDGEORDER01_E48_ROT3 | 4 | 900 | 0.561208 | 0.288345 | 2.568505 | 3.431504 | 3.776305 |
| EDGEORDER01_E48_ROT3 | 5 | 900 | 0.567677 | 0.293212 | 2.591628 | 3.421742 | 3.815648 |
| EDGEORDER01_E48_ROT3 | 6 | 900 | 0.573497 | 0.298301 | 2.788719 | 3.421114 | 3.446041 |
| EDGEORDER01_E48_ROT3 | 7 | 900 | 0.579866 | 0.303403 | 2.868460 | 3.427665 | 3.812901 |
| EDGEORDER01_E48_BASE3 | 0 | 900 | 0.182579 | 0.240651 | 0.293023 | 0.488349 | 1.862393 |
| EDGEORDER01_E48_BASE3 | 1 | 900 | 0.286644 | 0.262853 | 0.766906 | 0.796951 | 1.869773 |
| EDGEORDER01_E48_BASE3 | 2 | 900 | 0.380078 | 0.268339 | 1.208623 | 1.233950 | 1.875023 |
| EDGEORDER01_E48_BASE3 | 3 | 900 | 0.473061 | 0.273606 | 1.652394 | 1.683022 | 2.212606 |
| EDGEORDER01_E48_BASE3 | 4 | 900 | 0.565104 | 0.278724 | 2.089825 | 2.119589 | 2.662769 |
| EDGEORDER01_E48_BASE3 | 5 | 900 | 0.657541 | 0.284280 | 2.529431 | 2.558464 | 3.127006 |
| EDGEORDER01_E48_BASE3 | 6 | 900 | 0.754500 | 0.289621 | 2.974211 | 3.004817 | 4.765097 |
| EDGEORDER01_E48_BASE3 | 7 | 900 | 0.849164 | 0.294807 | 3.409900 | 3.442502 | 5.378694 |
| EDGEORDER01_E48_REV3 | 0 | 900 | 0.774927 | 0.115955 | 3.411038 | 3.458036 | 4.522513 |
| EDGEORDER01_E48_REV3 | 1 | 900 | 0.693617 | 0.124544 | 2.976360 | 3.023463 | 4.078183 |
| EDGEORDER01_E48_REV3 | 2 | 900 | 0.609643 | 0.130009 | 2.538505 | 2.584434 | 3.616270 |
| EDGEORDER01_E48_REV3 | 3 | 900 | 0.525409 | 0.135360 | 2.095714 | 2.135062 | 3.171876 |
| EDGEORDER01_E48_REV3 | 4 | 900 | 0.441664 | 0.140620 | 1.656888 | 1.699368 | 2.733695 |
| EDGEORDER01_E48_REV3 | 5 | 900 | 0.357185 | 0.145902 | 1.218240 | 1.258983 | 2.292476 |
| EDGEORDER01_E48_REV3 | 6 | 900 | 0.272721 | 0.151107 | 0.771501 | 0.815146 | 1.853379 |
| EDGEORDER01_E48_REV3 | 7 | 900 | 0.179412 | 0.121617 | 0.326476 | 0.418576 | 1.838740 |
| EDGEORDER01_E48_BASE4 | 0 | 900 | 0.189230 | 0.252019 | 0.298534 | 0.426648 | 0.521467 |
| EDGEORDER01_E48_BASE4 | 1 | 900 | 0.294993 | 0.267462 | 0.784596 | 0.814396 | 1.143013 |
| EDGEORDER01_E48_BASE4 | 2 | 900 | 0.387864 | 0.272872 | 1.226618 | 1.255777 | 1.610000 |
| EDGEORDER01_E48_BASE4 | 3 | 900 | 0.481533 | 0.277925 | 1.669084 | 1.714255 | 2.063616 |
| EDGEORDER01_E48_BASE4 | 4 | 900 | 0.573851 | 0.283258 | 2.109360 | 2.149858 | 2.515780 |
| EDGEORDER01_E48_BASE4 | 5 | 900 | 0.666151 | 0.288506 | 2.548450 | 2.588645 | 2.988655 |
| EDGEORDER01_E48_BASE4 | 6 | 900 | 0.758754 | 0.293662 | 2.992262 | 3.035668 | 3.435726 |
| EDGEORDER01_E48_BASE4 | 7 | 900 | 0.850657 | 0.299092 | 3.427337 | 3.473848 | 3.999801 |
| EDGEORDER01_E48_ROT4 | 0 | 900 | 0.471968 | 0.121035 | 2.726353 | 3.400985 | 3.459211 |
| EDGEORDER01_E48_ROT4 | 1 | 900 | 0.475925 | 0.129081 | 2.746427 | 3.416369 | 3.512395 |
| EDGEORDER01_E48_ROT4 | 2 | 900 | 0.477964 | 0.135312 | 2.593476 | 3.414242 | 3.497565 |
| EDGEORDER01_E48_ROT4 | 3 | 900 | 0.480262 | 0.139346 | 2.560058 | 3.411073 | 3.572535 |
| EDGEORDER01_E48_ROT4 | 4 | 900 | 0.486578 | 0.145301 | 2.587243 | 3.419489 | 3.456431 |
| EDGEORDER01_E48_ROT4 | 5 | 900 | 0.492650 | 0.150433 | 2.579471 | 3.396350 | 3.448612 |
| EDGEORDER01_E48_ROT4 | 6 | 900 | 0.498874 | 0.155401 | 2.592295 | 3.326853 | 3.804501 |
| EDGEORDER01_E48_ROT4 | 7 | 900 | 0.504955 | 0.160623 | 2.725346 | 3.415666 | 3.467224 |
| EDGEORDER01_E48_REV4 | 0 | 900 | 0.810049 | 0.256437 | 3.417072 | 3.452038 | 4.143488 |
| EDGEORDER01_E48_REV4 | 1 | 900 | 0.728525 | 0.265339 | 2.981713 | 3.017423 | 3.373496 |
| EDGEORDER01_E48_REV4 | 2 | 900 | 0.643991 | 0.270880 | 2.537573 | 2.575197 | 2.906879 |
| EDGEORDER01_E48_REV4 | 3 | 900 | 0.559469 | 0.276204 | 2.097816 | 2.136447 | 2.424532 |
| EDGEORDER01_E48_REV4 | 4 | 900 | 0.476209 | 0.281417 | 1.657289 | 1.697395 | 1.983111 |
| EDGEORDER01_E48_REV4 | 5 | 900 | 0.390882 | 0.286728 | 1.215248 | 1.234294 | 1.538272 |
| EDGEORDER01_E48_REV4 | 6 | 900 | 0.306152 | 0.291978 | 0.773729 | 0.810852 | 1.276790 |
| EDGEORDER01_E48_REV4 | 7 | 900 | 0.212381 | 0.178032 | 0.327875 | 0.526291 | 1.281771 |
| EDGEORDER01_E48_ROT5 | 0 | 900 | 0.517168 | 0.259214 | 2.737824 | 3.434507 | 3.466092 |
| EDGEORDER01_E48_ROT5 | 1 | 900 | 0.521730 | 0.268694 | 2.736527 | 3.429690 | 3.509721 |
| EDGEORDER01_E48_ROT5 | 2 | 900 | 0.523970 | 0.273921 | 2.592288 | 3.428444 | 3.467162 |
| EDGEORDER01_E48_ROT5 | 3 | 900 | 0.527557 | 0.278994 | 2.582729 | 3.427703 | 4.683074 |
| EDGEORDER01_E48_ROT5 | 4 | 900 | 0.532429 | 0.284351 | 2.579937 | 3.427395 | 3.473915 |
| EDGEORDER01_E48_ROT5 | 5 | 900 | 0.538568 | 0.289274 | 2.578805 | 3.426607 | 3.457347 |
| EDGEORDER01_E48_ROT5 | 6 | 900 | 0.544947 | 0.294169 | 2.599534 | 3.425701 | 3.477061 |
| EDGEORDER01_E48_ROT5 | 7 | 900 | 0.551204 | 0.299587 | 2.730908 | 3.425025 | 3.453561 |
| EDGEORDER01_E48_REV5 | 0 | 900 | 0.786061 | 0.118764 | 3.429519 | 3.467069 | 5.230539 |
| EDGEORDER01_E48_REV5 | 1 | 900 | 0.701976 | 0.127174 | 2.991652 | 3.025859 | 4.500770 |
| EDGEORDER01_E48_REV5 | 2 | 900 | 0.617584 | 0.132790 | 2.553371 | 2.585705 | 4.059775 |
| EDGEORDER01_E48_REV5 | 3 | 900 | 0.531343 | 0.138104 | 2.112985 | 2.144204 | 2.432424 |
| EDGEORDER01_E48_REV5 | 4 | 900 | 0.447171 | 0.143489 | 1.668956 | 1.698818 | 2.438054 |
| EDGEORDER01_E48_REV5 | 5 | 900 | 0.363276 | 0.148720 | 1.228231 | 1.255831 | 2.443294 |
| EDGEORDER01_E48_REV5 | 6 | 900 | 0.279078 | 0.154022 | 0.787240 | 0.813247 | 2.448646 |
| EDGEORDER01_E48_REV5 | 7 | 900 | 0.186915 | 0.118639 | 0.331620 | 0.426800 | 2.453915 |
| EDGEORDER01_E48_BASE5 | 0 | 900 | 0.213472 | 0.261193 | 0.312004 | 0.503905 | 1.618310 |
| EDGEORDER01_E48_BASE5 | 1 | 900 | 0.319556 | 0.274273 | 0.788137 | 0.819608 | 1.626097 |
| EDGEORDER01_E48_BASE5 | 2 | 900 | 0.412654 | 0.279876 | 1.228924 | 1.259938 | 1.631412 |
| EDGEORDER01_E48_BASE5 | 3 | 900 | 0.505816 | 0.285161 | 1.674603 | 1.708191 | 2.033519 |
| EDGEORDER01_E48_BASE5 | 4 | 900 | 0.598140 | 0.290203 | 2.113182 | 2.148478 | 2.494116 |
| EDGEORDER01_E48_BASE5 | 5 | 900 | 0.690410 | 0.295567 | 2.553701 | 2.588719 | 2.949465 |
| EDGEORDER01_E48_BASE5 | 6 | 900 | 0.783024 | 0.300785 | 2.995637 | 3.027020 | 3.391590 |
| EDGEORDER01_E48_BASE5 | 7 | 900 | 0.875830 | 0.305991 | 3.430059 | 3.467068 | 4.285616 |

### Initial source slot: exact timestamps

Each vector is in stream ID order 0..K-1; every stream has frame_id=0, logical source_slot=0, scheduled timestamp equal to the common t0. The observed vector is the pre-publication scheduler observation, not exact queue insertion. Warmups remain labeled above.

| Run | common scheduled t0 (ns) | admission_observed_ns vector |
|---|---:|---|
| EDGEORDER01_WARMUP_E48_S | 142500629586995 | [142500629887509, 142500629901389, 142500630379496, 142500630385376, 142500630390487, 142500630395811, 142500630400932, 142500630834419] |
| EDGEORDER01_E48_BASE1 | 142526716250478 | [142526716531752, 142526716541502, 142526716547215, 142526716552577, 142526716558114, 142526716563558, 142526716568678, 142526716573928] |
| EDGEORDER01_E48_REV1 | 142567888218991 | [142567888486731, 142567888496982, 142567888502584, 142567888507991, 142567888513390, 142567888518797, 142567888523890, 142567888529047] |
| EDGEORDER01_E48_ROT1 | 142609067615149 | [142609067880880, 142609067890417, 142609067896074, 142609067901398, 142609067906705, 142609067912353, 142609067917612, 142609067922835] |
| EDGEORDER01_E48_REV2 | 142650260184243 | [142650260276095, 142650260283928, 142650260289522, 142650260295013, 142650260300559, 142650260306392, 142650260311550, 142650260316707] |
| EDGEORDER01_E48_ROT2 | 142691445834778 | [142691446097914, 142691446107738, 142691446113395, 142691446118738, 142691446124182, 142691446129979, 142691446135090, 142691446140506] |
| EDGEORDER01_E48_BASE2 | 142732598378457 | [142732598637925, 142732598647517, 142732598652990, 142732598658008, 142732598663388, 142732598669073, 142732598674156, 142732598679397] |
| EDGEORDER01_E48_ROT3 | 142773769153540 | [142773769429951, 142773769439784, 142773769445469, 142773769450849, 142773769456163, 142773769461886, 142773769466933, 142773769472081] |
| EDGEORDER01_E48_BASE3 | 142815900035651 | [142815900289225, 142815900298882, 142815900304632, 142815900309901, 142815900315382, 142815900321021, 142815900326216, 142815900331512] |
| EDGEORDER01_E48_REV3 | 142857017651469 | [142857017916757, 142857017926989, 142857017932647, 142857017938193, 142857017943730, 142857017949443, 142857017954564, 142857017959795] |
| EDGEORDER01_E48_BASE4 | 142898141242762 | [142898141498897, 142898141508897, 142898141514527, 142898141519740, 142898141525267, 142898141530758, 142898141535906, 142898141541499] |
| EDGEORDER01_E48_ROT4 | 142939274602514 | [142939274721132, 142939274731326, 142939274736910, 142939274742326, 142939274747725, 142939274753401, 142939274758632, 142939274763910] |
| EDGEORDER01_E48_REV4 | 142980481286309 | [142980481395748, 142980481405184, 142980481410508, 142980481415925, 142980481421268, 142980481426647, 142980481431768, 142980481437092] |
| EDGEORDER01_E48_ROT5 | 143021666252824 | [143021666531078, 143021666541467, 143021666547032, 143021666552439, 143021666557819, 143021666563431, 143021666568459, 143021666573718] |
| EDGEORDER01_E48_REV5 | 143062855337987 | [143062855612616, 143062855623134, 143062855628736, 143062855634060, 143062855639441, 143062855645209, 143062855650367, 143062855655496] |
| EDGEORDER01_E48_BASE5 | 143104067805998 | [143104068091077, 143104068101457, 143104068107170, 143104068112568, 143104068117643, 143104068123467, 143104068128818, 143104068134106] |

### Exact inspected files

| Run | raw frame artifact | manifest | schedule fidelity |
|---|---|---|---|
| EDGEORDER01_WARMUP_E48_S | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_WARMUP_E48_S/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_WARMUP_E48_S/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_WARMUP_E48_S/schedule_fidelity.json |
| EDGEORDER01_E48_BASE1 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/schedule_fidelity.json |
| EDGEORDER01_E48_REV1 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/schedule_fidelity.json |
| EDGEORDER01_E48_ROT1 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/schedule_fidelity.json |
| EDGEORDER01_E48_REV2 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/schedule_fidelity.json |
| EDGEORDER01_E48_ROT2 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/schedule_fidelity.json |
| EDGEORDER01_E48_BASE2 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/schedule_fidelity.json |
| EDGEORDER01_E48_ROT3 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/schedule_fidelity.json |
| EDGEORDER01_E48_BASE3 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/schedule_fidelity.json |
| EDGEORDER01_E48_REV3 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/schedule_fidelity.json |
| EDGEORDER01_E48_BASE4 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/schedule_fidelity.json |
| EDGEORDER01_E48_ROT4 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/schedule_fidelity.json |
| EDGEORDER01_E48_REV4 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/schedule_fidelity.json |
| EDGEORDER01_E48_ROT5 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/schedule_fidelity.json |
| EDGEORDER01_E48_REV5 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/schedule_fidelity.json |
| EDGEORDER01_E48_BASE5 | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/source_frames.csv | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/manifest.json | results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/schedule_fidelity.json |

## Input SHA-256 inventory

Only inspected traces and small metadata were hashed, not whole raw result trees. This identity record does not replace campaign provenance.

```text
92f3ab29f27a7fd054800987962ad709682913e7de0494ef874d233d7e8a6adf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/per_frame.csv.gz
b561aae31d8925a388c431de464172c67a21aeb7f68dff7fa2405d2257134576  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/manifest.json
8d0899f57d06a9cad9802e940a64efd3fb10b6675ec1976ca15e2ea2239003cf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/per_frame.csv.gz
a9a2b76331fb2bd8d6b19362706e0ca602347cd9649172571b8304e0a058774f  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/manifest.json
e81efd7382eaec1b90b5e1d3810072cfbe8c20c0f9409a804b08df6226de9c2e  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/per_frame.csv.gz
08df19fd34de4e0f980ad58a25888bcbc6fc86f08cae0b4591749f57c3545cab  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/manifest.json
2745b14682d2eb1c5f988bc4756f405c192894ec6ef5d62eaf6375cb37a80bff  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/per_frame.csv.gz
83bede9655ba696b5eee03e7cf2fe363e433eeb0188d98e3003fb9f8541a6c59  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/manifest.json
26be9b57006e17be36ea97eeb3a260de3c88121a6df18a048091d22b51df40a8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/per_frame.csv.gz
2dca25da6595960934dcdf489c2f59726ea77df58d3d5deba412eb0fc46bf362  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/manifest.json
de3bb9cb31d658f8df22ed1451df31d6f803631a19c2c9c7514ca0f2b1fbd3d3  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/per_frame.csv.gz
bbfd85c27ab9928fff2c9c77a97fb60076cfe571784f7ac29dd5af1e4ad24938  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/manifest.json
c84650344cd0b84205cac92f6ef453d106b3ebc5d10dd819fa389df67a4ca218  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/per_frame.csv.gz
b23b5ff2a484baa070253161cb20b4a764a636ed4592163f9d4df25e8815242e  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/manifest.json
a76f8efe99590cd83b074e8d479ec3f57574c18233ef3e81a76781ee84ad8d91  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/per_frame.csv.gz
ef86f71c9dbebd29e54a58ac4715dd63705b15406e8fed1491be8614a2894c4b  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/manifest.json
e27d53b01a2dfd0b02403b423ef12c9dbc96385022926906e7ea975e61f8b268  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/per_frame.csv.gz
e6be4b893b7a257f695c5d1e911fb0bf8f84fdefb63fc8a1a03c49b11d49c275  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/manifest.json
c06d309a5ad846902032268d95af407d29f2f53c828f07cd6932838c1c13469c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/per_frame.csv.gz
260699e80ffcc764668398a5c5d7e6cd6ad9bc828cae2a14a304498fa764587d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/manifest.json
eaabc07f8744aa217dc8e8e53d6c70220f5cf5e6b1da43f05b0126dbfe3334f8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/per_frame.csv.gz
44f1b5a86bdf227353acb16c99fe7c5b3f024c3e8504f486e3be589a1b4ca6cb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/manifest.json
330a5dd31da8f1e51cfc4d502a07fa8f9e3c4c305e53f775708f5ff1bc7ab41d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/per_frame.csv.gz
c5f2dc5cfa64da280e29c7286eb819320c82e3b0f0868eae7ecb61feced5b8aa  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/manifest.json
062d8b8c80ab7c499f14b6bce370d630b1e2461c520818d0290b22e294e2150d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/per_frame.csv.gz
0bbd72c8680b0ad54d8f6408c46a256c709fff9b6d50eadda3bced8acc19930c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/manifest.json
2b071df339c3d1e332eec5cbe07a9d39d267b48f347dd8d0f60c97e69f3bf9bb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/per_frame.csv.gz
1e80bad23740b1ff488c4f75ba7306ce0d2c64b0041bd615b21f28a2f48b2fe0  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/manifest.json
488445feb7fd62eb3cc5f682c524b012a352a9928ab79db828885570a0c8100a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/per_frame.csv.gz
e5d274ea0ac2464c443bfde83ff42e1bb2e64b6a87127abbaa89c0cf5ec624ba  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/manifest.json
dc9e7ad0b1b5b7415dcc6b5bc99417364aa681d82e0a15857563eaaba0db9209  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/per_frame.csv.gz
4a164772433bc62940cb89b7818cb2a99a9f2a8526b51cba66be3463a46ebc92  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/manifest.json
50d20e6908bb6f389f8bd5ebe1f57ea16deae91f3a6815d5851f24a2843c759d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/per_frame.csv.gz
653f4421e8059d55f72c8698e214a20ff5a4c93f83756ee92b1b6d06b79738bb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/manifest.json
f3941b789e2a64a4956b819bb27427c831394f5eaa4062d6ad81f05b6f75bc1e  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/per_frame.csv.gz
8627d189e926525f000780f79a21e3483b206abdffa3617d35563f02135ececb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/manifest.json
efa3ef71a28a8ec7a7844c608bea18f6c1f7ae41ff2882eb18615bf6ff881ff0  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/per_frame.csv.gz
783d19b046f14f43e062d12b2568ac7e82e8a1858a830f6cb1ef805ae99d1d08  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/manifest.json
5bff3cf7882f390620040bf8d0d65f19a4965eee98852fc24219c8d9462df408  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/per_frame.csv.gz
05e48908e0f00ee73ee610c471777694ff3f3ea29fcb15a42714bf8bf953e797  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/manifest.json
9e626a215991e5bc54272aa4907c9bd7c80c8711925a2d980a7befb54fe4d1a8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/per_frame.csv.gz
a5cce6deb57ef613023174949529165565ce91ebf5b0e4bbeb23f512d6fff5a3  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/manifest.json
00e1033b3d3842ba0faee1ee20d21e8e1ef7f29b2aada3ea6f8e870f5a7c29e5  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/per_frame.csv.gz
052d554d90125d0f8f8738e94de11f8c8470247d547daa62fc3d188780101ff3  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/manifest.json
c6d7251cae38ec9a7be2cbfb512695c31ca394b4e6f8df8705408d6246f56e0d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/per_frame.csv.gz
fb1eef265e1d3c86dda2d9e5ec3392b4d52d27b919057eb6979b79dd6ec2774c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/manifest.json
ded9ba4ba8a0abcc022437780542ba4b4996a791ec2e09118601c82967c24724  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/per_frame.csv.gz
9ab205da6e424c50bd42853f1d0ef5e0d9371324a7bfedd34f41a11708322a3a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/manifest.json
24f1670d02abb24763bbd0305706780a3dfd250e7441210ddf9e8e4d588abbb8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/per_frame.csv.gz
cb1d09c6b902a2d4714e62da9c9b89f955c602a6b6b9af5f20c7b086817012b7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/manifest.json
17b21388d79acaeddd8a62d3138507a99216cb8a3e25db1bf93326a1bfc096c9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/per_frame.csv.gz
a5cb066128fa003be46c5d7543d029f8b9cfd7ea71fa443aa802570430e37f1d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/manifest.json
d22578b3eef4c24aeb9778e61a766fed21fcf6e41c75992f32a47367767b67c7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/per_frame.csv.gz
f4bc40fc73e2ecc3bdc7e150e853a5e085c5c7063bb80201f2a66594b70d4f5a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/manifest.json
e19c88df0b33bf786f9e50364769b0426da3aa38395e332ed287dc7025f552c4  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/per_frame.csv.gz
fd151ebf873bc2f0f6e96b87768ca2389d394baa6921745efd3fe26540b36edd  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/manifest.json
936351164c64c31c16e8617d7e5743f71ae1bbff68b2e114300aa2717b0b24a9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/per_frame.csv.gz
bc20a2d0e4ab461004ea0b7f959b04370d1473f95e6c0d9e8a0627031b45e118  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/manifest.json
8841162979cd2772510cf44eba9951dc3235962f41167ec098604522f9da6fca  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/per_frame.csv.gz
7cb565748359c06f4bab7176bf22c15ccb2502569d4dc76595e33f9a84da02c9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/manifest.json
84b41b5992d29d8de8fe11861874780f68118d0d5650a447902fb7f6cde8bec4  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/per_frame.csv.gz
11722e9ac2753dd4f7a129c60644dc6e7495dcb63e42d8ef6ab10b96849cbe21  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/manifest.json
b5047d4fd5e77b8be82747bbbb0de12db360f382d00475acddfaf1f6f926b411  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/per_frame.csv.gz
7409c1f7313df14dd0f1a87c4c9ad6a1de7c7f82e5ce27818012e8f9f36cf399  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/manifest.json
9fec054473b67fb407e1890bb10e083de8ebeb95da07454c29270b8e96f22999  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/per_frame.csv.gz
2dc1cb8b3f92b0a9f69850923153f8add3ad0b8e46a4c3e3ea9e0b255af97b39  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/manifest.json
f55c8cbfd4590065082a9907c5835263e705fe0fc349f3ff560e5039c9f3c1ac  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/per_frame.csv.gz
9aa9abd6602264526fdf2adb4c3b0eea5cf5da2eac6b30363ad64b3548b8b1b5  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/manifest.json
bca3296cea014f7529bcfd9ec0d123e8f267e5b87260ca1289df7d52356d76a7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/per_frame.csv.gz
2ad19e8756f9a1d55204e635a3b251d75bd44cb5c9682d0c15d9860a22b1260c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/manifest.json
e519673d216debe11dd651e7c75ffaa9c2f3aab83c25b577d62a6ec0c9014414  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/per_frame.csv.gz
64c262cdcc5f63e55a4e548b6c874280c96410fbd811d03e79c5fd267e0d923a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/manifest.json
55fc1b0e7d73ef623ef4f1adca2047ea3ca9e710721c2ef4b42e770d3986cf21  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/per_frame.csv.gz
526ea7fb09dc5ce83ab06b44cc246f394d365852b957755d78339d89d07ee8df  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/manifest.json
869298d39c23eae71eceab04ac6281c15f4a2608381f930fab7c134bb0f0b10c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/per_frame.csv.gz
5f9276e9ae942a27034a2c974f6e99d0619afa53767562dbda52faa75cc36b38  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/manifest.json
59a2394052e71f0cbea7ffecaef67e5be888e6966184913167aa9c2a6724d769  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/per_frame.csv.gz
ec582171f0629101281c6703b9df78368440c30b88ba4fe59065994dfe060cdf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/manifest.json
bccd1a10e6785e1715e29d88b0934c79540496e557f988f6bc542b4125a56256  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/per_frame.csv.gz
11e299624cc764c66b1bfe04de01a8d5ef798e7ac5af4cd7ccacd0672b0c99eb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/manifest.json
3378b12a1ca430925601558a1f1c413a34c6bf3fb34a76a6ce765136a44252da  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/plan.json
bbe065e2fa1a05d89f9e7809a8139c6b0cbf6336421a3b1c0db810fecf00f727  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_WARMUP_L200_E40_S/per_frame.csv.gz
7931385b77f4d71b06f19427affe8a6ca6ecdf6af2dea8ef5ad0b0a88a6ccce3  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_WARMUP_L200_E40_S/manifest.json
ede34631687a8e0a46451aac7a5ffd9fb480e9b8b65ee60ae8b2b83863406c24  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/per_frame.csv.gz
5dc8a68c9012a62885b590d5e869a9838197b7ec4b9823eab40125c9b452bf08  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/manifest.json
65da008fcbfa6b2e6f529dc6423f1904b00c3a5b198c487d0b21dbdee6b4d4b7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/per_frame.csv.gz
d651b9b5d038513c8bb42d7fd39a08e871854998f960ca0154cbd0923e57c409  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/manifest.json
9a9cd6a2c1e6595d7b651a23fcf19b2f0aa40c0ca06e177958a277e8e9e04018  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/per_frame.csv.gz
5b9c80efa007ec2a0a7cc4b584e4092888530105b84c5793dfacc3491c7a1d79  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/manifest.json
ab316a5ce1db555cdd7a80f8c86ef0cd0aa0bd74d5f8ff9e6af9525d3ada1c8a  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/per_frame.csv.gz
d8dd7d060378a8f57a0c7639d36c9232c42cdc7557331ebb9781c6182a6c064e  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/manifest.json
47090ac9378cdb373459bb4781e1310f11cf77c15cf6e69a2193dece3e929264  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/per_frame.csv.gz
346026e76f3a123c0cc959a8c10d25c7ecbba0df5a5ef937eceee53141182c30  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/manifest.json
74477531c3ac159a17a9dded3e06db01f82c54044f1e9394aa2f15653bf4e3dc  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/per_frame.csv.gz
86cbe5ae46278f1b1453d60e0d585d02a471c7a21e1a68404659c7c03b4b6727  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/manifest.json
a87fc19d9091c40e2a2db0d7b519931f34a7d6b64d856fdf4f644c15ebdb40a9  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/per_frame.csv.gz
b98067477e424dc55c3bde5ca3161639e47d2f1c2dde1f8b412da5ca83e8edb5  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/manifest.json
98d5358c1ed16d8074f2c63abd1792e8a4616ba1979d077fdd7a3c32d44e4725  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/per_frame.csv.gz
54fd396867a053fd5c723ed2cf3123088f3fe63da64213a6bcee95e168879216  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/manifest.json
49730a7e8485d2c48e003291bdfe951fcff3b2d48ca2c1fd600fb4c148c77726  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/per_frame.csv.gz
5964160f4e5651dadec47b68d4d11d7ddc083d5833061b395434cc3f5d6132f3  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/manifest.json
29eefe032e3ecf43a28b0a21f8c4946d8037142d2e3ca2bc79027bee4ae271fe  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/per_frame.csv.gz
70f48a1fae38804e3e4dacaca6cde659724d31394d4a5fab3415c6cec4037483  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/manifest.json
b9fbdff870c3eae20c85ca79d44c737aded81a2f3477351f4b1c0fd8e53b02c3  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/per_frame.csv.gz
135668f8a93fe5a829a53f50fe001b5f78079d9e8b4aae3cb6e25067158265a4  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/manifest.json
4c1627381011d3d9979d488963b9006a68fb174bfae3e8567bd46bc24f5afcce  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/per_frame.csv.gz
9ae33dfdacf1ebf82f293cd4d9adff1f1d88ba77d85e9e1524863439588faa2f  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/manifest.json
e7f96266e104da3e4e2168b1d2b902ee62d62214e0afcdbb5448bdf68a2ed32b  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/per_frame.csv.gz
1dc146cc2d4dad8b81a88745acab752f8842ada4e5fedf0da52cf97fbdcaff4d  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/manifest.json
57a348959ae70012d4a8536c6a406f71d721efd4e31a0a6d438b8657e4602142  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/per_frame.csv.gz
e3c40854cb7d69a3c968ceaf5f34b6b736a47b7c05070d7c841bcae85f54a1e5  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/manifest.json
ac68f2d502eb8f09284ef7d1ea68e1547c9f473f3838fbdfe3be9ca5b9afe6d6  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/per_frame.csv.gz
17a8dfbcbf1b6ee334567365b4b70f0638593bcbe5083580b48074d8567ad387  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/manifest.json
2e70e915692c2efe3ed7e533d8eb4c1bd2b09797814c8cf4fa2af1fe92fd0d68  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/per_frame.csv.gz
a192dd830f9fb407794a5acab26b247f190263487f3fe8018ecb29a074fe2527  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/manifest.json
76566a0e3246434dc00d283e6affe59312e493cb4c02f57b4be2fcd8c809d672  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/per_frame.csv.gz
9963111f090a574594af481e95e561e1d514c6c766a09077888772e900ca4799  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/manifest.json
328c188b73d2678c2968842eadf2ffda8a67dbab0da33f880d6a8a704fb2ecd2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/per_frame.csv.gz
1c375afa3b094eee76f5fa7768f9f3a2e18dcf6b0e5178d9ede54b2761cf12ae  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/manifest.json
d34f77e0f499bce7c4c4282584dc6f0b7957183a3b0d50184fe471d9a9df7cd6  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/per_frame.csv.gz
44db1cfa4d07b4437f51380983df83198577d96843446fa9f85bd5fc14e222e7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/manifest.json
f4358f5f0363330f53cbdfecfc0f49a988e9765471b74906172f8d234dbaefb8  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/per_frame.csv.gz
b421bb220626571c955c21821e3a7c38fe24a128cb6ca099c70053057b779986  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/manifest.json
9b4cb1bdecd42b12266a2d920a37c56190e27f2d355f59efbc9ecda5eda03ea7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/per_frame.csv.gz
a91864fb559ad5da331722b6a3749b30416459ecbe0457ab3498f83abee0d33f  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/manifest.json
c17c7148f341afb393ae016a022ecd1e715f02a237fc00d13cc102ac8a7e5d9b  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/per_frame.csv.gz
0b66093c996912e75d6c1779e81e97b79f81284bc3638bb329012207833485b9  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/manifest.json
cf42e4bcade34e3048fff0ee4483c01341a4c3f083ee5c5971438233878fe1c9  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/per_frame.csv.gz
48b1d39c214b1ef6cf093078b5c4daf90be996399ae2cb707912dc3060e05fae  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/manifest.json
76538031d2a852530c36f25faf09628007c839dcb73e6ae7cbc4a005300f4ffa  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/per_frame.csv.gz
2ca2fd47753bb9722b9a72e36f0cdce8ef8f5c470147965bc8a60d6a6a1653c7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/manifest.json
42a27652588588b866ff4528e6548457d1ac122391354d390b59638dd50c05fb  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/per_frame.csv.gz
5a18168e96ec0e8b8cbf771a1101690c3e241d1bb1e48e567553fd9a71a2f899  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/manifest.json
14566f1cd93aa1a7b344920a53801752140cb0c8c0906d698de1d1dd668bf3e2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/per_frame.csv.gz
c6839927d52526f86860b06ee621fff1b271680a4e04872e3852a3bad7816530  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/manifest.json
a4830b82bd52a4f7612a7ab8eb2715ec65e002392ea3fb8da02e091ee2df54cc  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/per_frame.csv.gz
cb4c0e01650a78c7d6e1ce0ed85f5a5d16ad3fb9b0303ea1525565d9688a7427  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/manifest.json
29fa4b1bdcbbbf38265642d55e96d76e0641cdccfcac307d53cb17b93b7505b1  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/per_frame.csv.gz
f422cee8aa314e6002b725731756ab383957d026f283bc1cdee86e11dd8b3901  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/manifest.json
50fe980a566086f0ffd4659bd2585091750c43c043a85b7286baf07e5b09b449  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/per_frame.csv.gz
3eb29e1d7244e7508679e0e64a7a793463b1c36e13fbf980c14176ccf2a5e05e  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/manifest.json
085f69b3d09f3a0a8af40c1c5f52def3e62fba166da3656942cf7b7b425802a5  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/per_frame.csv.gz
7f00c6760f23958345d5e4c2b2b9835aa7ba073ffaa2a4d3dc9b30f8334ecfd7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/manifest.json
ecc6cfc219572ae2754ae3f9f3d8c7e9bcdfed0274c18a951bf459d71a66abe3  results/timely_capacity_campaign/v2_2/block_b_grid02/plan.json
35512acf779afdcfcb13e1ab363fc23b2fcc03d61ee8bfd026676868b89b32e7  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_WARMUP_L200_S/per_frame.csv.gz
ebc6810d9c255fe508450db60dc56c52a57af0deb0e017078c3878b212af1b35  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_WARMUP_L200_S/manifest.json
55c1a26835f1dfd2d629476736dab2d9672fd2cff5c9d8915f9f30ac1d6bc051  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/per_frame.csv.gz
915c73aec198dd0ae8c7b226d21331a846d26361e236fa0381f385b152307d5d  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/manifest.json
a856dddb10670f297e4434190db47cc2f73247a870d3ac074dfe2c6e6e17fc7d  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/per_frame.csv.gz
0ba1d4feb81ac62e5462d8b7cded3d06a5c79d549eb5b22603deff99c92ca954  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/manifest.json
9ed299552fe7e06af354aef81a2321f5a64d6c36a92a3c89629425ffaea2138e  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/per_frame.csv.gz
7f96ddf4abeb3b6754230ac37d1074b1be30890c00c7e8603c5f08271390fd18  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/manifest.json
d05578aea439a43de0fe46bd26dffc8a203e51a941b3c9f689fae9c67812f8e7  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/per_frame.csv.gz
ee7b34cfddfeb838037f2b33da8f3d40b1aa91b506dd6ced001abf0d56d57b01  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/manifest.json
f29097df99ed4aff640c2c081f5ef525cdc95ea86ed442d97c2e932c3b247ff4  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/per_frame.csv.gz
2ddc623744aa610844f412c241fe25563bc5422ccff8a9b69e693369ff0f4482  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/manifest.json
b4ecac47248bd8cd0b15fdeb7507f940b89d068e699d728525e75acc11249762  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/per_frame.csv.gz
70a56da1bfe54c268cb1690c10a5bb489e7e7c73d3a6c73a17a01d33fcac4b84  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/manifest.json
61e1462d61da9d422e35f25696f84b71809a926b140826f9d1561d692e0dfc43  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/per_frame.csv.gz
0c49782717fc29a83b88a2fa0c8f85cde8f75b881dc925e6f7b246d5ce8b58ec  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/manifest.json
c4ca49982a8f0e2ac09c02ea1aadeec4b1936975945003b80f0c068d036ce25b  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/per_frame.csv.gz
a61d7a6e12bf469425f055dc62f97183cc81d785872e527b9594b0c2702e4bab  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/manifest.json
c3d560b915d31c0f69f64972956ba343ff4795fb4a205bfcb30ef8156720145a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/per_frame.csv.gz
09231bb5858c789d688fcdf26ffe0f19a4ba39fb8bbe5b827890725ec0e9c6d0  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/manifest.json
748001705a33e91913590b54214d6103a695c2acde7c2d3257f5ede7739544b5  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/per_frame.csv.gz
6a61e228d641a86eaf916cd54416d3d52862b9c4ed660e924d0281ad954a7a58  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/manifest.json
ccfec5479883744d4149b47add5195a9f471048e89e1ba6bcfa642edaed155b8  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/per_frame.csv.gz
41b668d9d009526d756980e81a901a20c42d5231336e561ec8525c7435126f4a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/manifest.json
01a65f2ed1f639cc954cd8e5fa2ada6f47070c6318bcf781c8b0057b0db4ee44  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/per_frame.csv.gz
6dd49919eaaa677a73860ceed22bcc17d6db5d94ef6dadaf3fe9de83c406b2ff  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/manifest.json
aea02020d1454273e64dba21edc2376c90108313e4659697d79fbd0e4e36e038  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/per_frame.csv.gz
8a743b9a2dc29621f6db5e25075bea9abe95f2329f872efd033fe1978c497f63  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/manifest.json
2d740507c38dcb82c79eb2c64d181b12e01f5dd2b4f824c2ad4d66b9b851384f  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/per_frame.csv.gz
5a328ca31ddb0c52395320da7ebb9b3fafe11d21341a12ee3c22c58e25c38508  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/manifest.json
d41dfb6202d6d3b028640957d9861fcdc4b3695b34741160f76ca8e834e7980c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/per_frame.csv.gz
f765ea387f4add93eef646fb699890cfe100ee2c61ca09460a63376e0f0b1da9  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/manifest.json
532f3a64325cd1e480e22bfcedd6b379c354b12e9095c49f2ad4a7d28297adad  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/per_frame.csv.gz
fa6a93375bd46feeea3d7069d9d9ac4661d528549f47d78b3306c0873904dbdd  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/manifest.json
49f4aa0c485bd58cd82e49214cf49ae7207dad3f8954dcece12b71d9cee295cd  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/per_frame.csv.gz
ea7389c8897fcb29b138d91eb342f8331dc2273f9fd8be9c3dde7b2dedf77230  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/manifest.json
1221f98b443ea215245fedfc051621af0dde82b719e99cc905acc9a18d660e97  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/per_frame.csv.gz
0f7a1c5bd0e666b97ead7c30c92375a9de83a4252d9f1ac11032674fcfa72a83  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/manifest.json
41c019b0108c0621e5efc9cc03cf83ef14c58ea3dcbf3d16dc2cbb247c30b185  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/per_frame.csv.gz
c4df661dd87a19b084fb054bce3f7b68a3a27f305c631035a03aa167ba2a872c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/manifest.json
499e7a14e37d5c499c9416097445ec18803e9250249c14c1653e7975f7b4041a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/per_frame.csv.gz
bf10d0863d9da5f2610cf394de74a822a328eda1320455953764ec9262396ccc  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/manifest.json
bd3d1222d1d03c0e068689a2410a89946f0c159a9817493b57440eeb57cf939e  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/per_frame.csv.gz
987ffa579c97e4f768f8555dc5512f3b1139cf2259b5cd0cd4bc937e6a3c7ac4  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/manifest.json
23eae907bf568ad290486f8fc0f61e076a53eed0de1b394152a3b49ab00faa6a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/per_frame.csv.gz
b9a31ae7331939696aa9752af85252c861edc032c39dfe246bfea971b44d9084  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/manifest.json
0833e4453636adbbc56a26769cc39e343be77f732b123a903bc25925b6f0310a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/per_frame.csv.gz
5700ce725e346cddaea8100711454d7f444549f69d68312068e7407a0aad2d9c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/manifest.json
ffa1be7c25e0353805ebfb1ea2c36df57f869c403594f8ffd159fc6b7e327895  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/per_frame.csv.gz
9d2194ab41bf3cd90d77b5267f0c8ddd3a81b99b1deb7c219a7a4aaefc106437  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/manifest.json
bcd2025ad97918dac255fcf47f0aca1c9c3cd9a21360553f79dbf2e9cfd83168  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/per_frame.csv.gz
4527cb74c8bfe3748468b14e0ac5c00f7c30597a9b0ce8beb2a1058d045b156b  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/manifest.json
2d51128bf897be48cd0db8835a9d1deb423c0053a31e8093350b3b525ca25a08  results/timely_capacity_campaign/v2_2/block_b_confirmation02/plan.json
207ae50a7e7193f06798b3b08a65af89ac04d2739b117503165d1b38a929a963  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_WARMUP_E48_S/schedule_fidelity.json
65b68d2ea34e016b0e8dfb95ecdfb4665278f81f25f8a2f82c37d1b94a15cecb  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_WARMUP_E48_S/source_frames.csv
2c28c9fd180d0d75cdfdb032b955b629da30f286d9cac66f51317b1408958954  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_WARMUP_E48_S/manifest.json
4defa4a682496ab5d9e33bf78370cf365525f73ef3498e63ef6c171eaf55d15d  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/schedule_fidelity.json
67e71db0dd26223375c9846bef3d3db3615e015a9f66611628c49404950c296c  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/source_frames.csv
1a9f3708000c96c32482fa02060f53b829b4676862beeb83cba559a1223dd737  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/manifest.json
66e0733ad03b3ae18413c1d3295b7a4d16594528720437fb2d226b4f79373064  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/schedule_fidelity.json
936703f3b9deb2bb33936edc18253a1f56efd6b59e359dbd703cae0570de763a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/source_frames.csv
e6a8b420223205a5d76c53820ea460bb3cd71d8a13c092e55f4901ba1cf946ac  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/manifest.json
66e0733ad03b3ae18413c1d3295b7a4d16594528720437fb2d226b4f79373064  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/schedule_fidelity.json
53f785252e9473c46218c98f71487cbb2eb9034cd32654c7aa95784e7bccea76  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/source_frames.csv
f3f915591cd22b557101e63889987b79af4b2e57926327c8d4d96edccbd06e16  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/manifest.json
4defa4a682496ab5d9e33bf78370cf365525f73ef3498e63ef6c171eaf55d15d  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/schedule_fidelity.json
c9ccaed92e53709dbf49c732113331d9f535d93ae7e1dc798b6e4a2b59379ebe  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/source_frames.csv
5a5916fa764a93cd57613182f2c7f3e43404dff787c99d0efa79a429c4dc9f48  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/manifest.json
4defa4a682496ab5d9e33bf78370cf365525f73ef3498e63ef6c171eaf55d15d  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/schedule_fidelity.json
03c469f65ca44b0cf8609578f413e94d1802617123082a7621344fd58e06b679  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/source_frames.csv
15bc0d9ba9a0cc957d96f139e8686855b0a09803eae237aa1d4190e22d9486db  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/manifest.json
66e0733ad03b3ae18413c1d3295b7a4d16594528720437fb2d226b4f79373064  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/schedule_fidelity.json
944e7aeeb85fad523203fb572801c3a8477b1db3b366dcc24af6a24368485678  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/source_frames.csv
9babfacc16bb8690f3d15c2da5b90a4b99c6531605a356d56a3c0823411c371a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/manifest.json
66e0733ad03b3ae18413c1d3295b7a4d16594528720437fb2d226b4f79373064  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/schedule_fidelity.json
0ac0041f61e33a61d7da0704b0baad43c839a56dc8322777c768ad193e01c617  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/source_frames.csv
f6b2103619796d4357158f561572f03a7b2882fd49fa5b72b747dbf584dcdc0e  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/manifest.json
4defa4a682496ab5d9e33bf78370cf365525f73ef3498e63ef6c171eaf55d15d  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/schedule_fidelity.json
7ab0af428e6502d821f83adb42049f29a4075b330d5443ac7be22bf5e8888f9e  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/source_frames.csv
768733d11858d1c2c2db629a8b3060a5010c5f4c7bea47bb5aa3cf3654beafe5  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/manifest.json
4defa4a682496ab5d9e33bf78370cf365525f73ef3498e63ef6c171eaf55d15d  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/schedule_fidelity.json
36a740d54dabe7a362f703f65b9b88b1fae5439233ca9e6dad36a8ac5ffc0563  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/source_frames.csv
e461ae5f38f113073baf10696885df452a1deed316f669ad80925469bc238364  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/manifest.json
66e0733ad03b3ae18413c1d3295b7a4d16594528720437fb2d226b4f79373064  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/schedule_fidelity.json
d08d96b5ccd92390fd7414f01af1f82feccd7973f027b313c75dceee5b273efb  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/source_frames.csv
3a17e2c7db65fa904a5c39e195774c1d938c9e2f3ba57a81216419f1ed9fd7aa  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/manifest.json
8b4baceb94202e67351dac24dc266f467780f2f2abe6012b34f55334ef174576  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/schedule_fidelity.json
5422906745e7959aa8901b74b234aac33788f3e6294485a2228c9e60b4f6ac0b  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/source_frames.csv
0095e8a9d23e2d54b9ed129b9a9cb32778af43a16fc553418dc7fca0f1460bfd  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/manifest.json
8b4baceb94202e67351dac24dc266f467780f2f2abe6012b34f55334ef174576  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/schedule_fidelity.json
1ca4205849716e1d597affa58521933222216aab8ed27fa4cb2a08af3c869011  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/source_frames.csv
ede234927ef234abfca256b7b297071c406719a4625a2e4e716ceff7003f969a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/manifest.json
8b4baceb94202e67351dac24dc266f467780f2f2abe6012b34f55334ef174576  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/schedule_fidelity.json
17cd1f76687d84697ca7bb25529ee78275a06686f27b3b7401156c9e8e7343bc  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/source_frames.csv
2dd7696d6d440d5eb0ca9a399dcf90227f0116c8c796b330595e59644e04217b  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/manifest.json
b3705e5a34863ac262ff714b4ff031028ec8a9b5a78d8df97338832c869760c3  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/plan.json
80ea550199f24efa9039dec2b3bdc5eb5916ad6706ace5607ebfabb2bc91745b  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_WARMUP_E48_S/schedule_fidelity.json
ffa9665eac6b47ac98d1f15ea2fdea7b19306f84e1a74ed82f399e09d26dd6e4  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_WARMUP_E48_S/source_frames.csv
ce43fa0301247eca63017c25fcc968743e0e10b5e66dce033c3e2ea0408f0217  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_WARMUP_E48_S/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/schedule_fidelity.json
a4e94bdaa8352de5ee52ce2a8c6912198f311a4dfc49af52a4b41eb04bef5477  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/source_frames.csv
fb27c24e8c16d10a298c718517546b40e47dafc04f528b6a4c5af7916762a133  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/schedule_fidelity.json
d5c5005a1d263789051c5ce1b653e55ff13b084b872bb8eb31140d95186cef81  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/source_frames.csv
2b7ff406827d0fc547f5da581d391b88064794416b92877b440c269ce8bc6001  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/schedule_fidelity.json
2440a2d6f766ab22929718db10d94d39cb7977ecaac9d541bf82a293348a336a  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/source_frames.csv
9f429df18d930c1b34c5316c47e3bd9e2275d986bd9724ae1ca6e89e7991f171  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/schedule_fidelity.json
1ce3754f76b671343e946f2bdd425ea480ef0d4cb4c2a18c2d781017a47b20dd  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/source_frames.csv
ffa5df3300a93a9f3dfbcd033b768f1decfa9c1b28ccf0b4f00499753e2b8425  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/schedule_fidelity.json
f8026ee1ae72749b9c3791f4061d32f90a02d9c9188b45cbce548433688621bf  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/source_frames.csv
927198c0dd1f7fc196d28dde6fad57198b8294321de6605b1457267ce99717af  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/schedule_fidelity.json
7dc28de8e03682c0b84ea182d8135f3875194be220704a2925ffc827967898fc  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/source_frames.csv
2b240c8b303d16f5940db1b26d3069308599f941e2caed97fc8746f092118e21  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/schedule_fidelity.json
c278f79d6c0751a8fd6e5b960821ccbf51e713b62e2ca512e1004a61cf436364  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/source_frames.csv
52312661a9da8afc52a9472b64b823fac7b7be0e9c49d6005ea95aaf8624e4a0  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/schedule_fidelity.json
688e6e856c84ac0f088fe20cabf6ffbf21448ebce98f91c5257c869b7eefced6  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/source_frames.csv
0db42ec8014c38cd9fd0bf91ab451b0f0730c009303d53da6731e0e69b0f4ffa  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/schedule_fidelity.json
342159a39ed85eacff74ce7bd7e4acf4dbba217be0c2d0543b39ef7a36d34383  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/source_frames.csv
c597592464421a1a8d6223abf50eafff054eda8246f48eb88d9a59d904d7c04c  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/schedule_fidelity.json
16da05a6f4c7b1ca1423a540e0da3994d86ccf3c6854c83c4cd5d27416c250d9  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/source_frames.csv
9fee7769652905bde8358e0711ec93491a71c10a3d89088e37a2bc490632a976  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/schedule_fidelity.json
43c474988cbfa8b696e0ff4e32f7aa80929a6fef6810c26c4b27a42c2d2e3d1e  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/source_frames.csv
623aa2f2b95817a35c2f1734e8defa76e63320d796c1cc00e4001a52a40a1ebb  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/schedule_fidelity.json
57738ebf0a9723aa4573eef14db6ebbc7f40d8211cf6988bc2a1929c43f56580  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/source_frames.csv
9fcab1678393ae01ebf2c2783c730f5c70ce51520176174af689e1524b11f343  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/schedule_fidelity.json
a12dd020f5dde14ae247cdbf021c548c1f4462e49d5b121c59aaf8888e065454  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/source_frames.csv
77716fa16b9e217b44cedbb986d6c42b71b605495da4f9cc92543d0895b6925f  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/schedule_fidelity.json
61ce0b7b0f64ce146c80ded11190e11f71dc163d6aa94d5cdee20c995d7564cf  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/source_frames.csv
d3fb83ec990644601ad9db9562760b1c37712f40750fd37486aa8a054e9d9a08  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/manifest.json
c3b5b3244bbe18375a172a2a4f8593a349d69c31a3580a73993538ec747a2494  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/schedule_fidelity.json
4459b6b767fd9a1dd9a2f65476b3c6fedbf38375bd9c8b773a589dc075a028f5  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/source_frames.csv
5f7b3e3e8726e9532017fb2683c803e846e02b05fb5bca89eda7f80365483289  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/manifest.json
233370402d62b9d185710ef664b6a03c730fa3f72a3784fa86fc9ac59710c727  results/timely_capacity_campaign/v2_2/edge_order_robustness01/plan.json
```

## Inspected code SHA-256

```text
b31ad8a84623f2c11c7dc0eeaddcc9449d67efdc84a5d6666ca8199f23784d29  scripts/expired_work_pruning/pruning_common.py
d300ad5586d6425a3e1568fac2b5e3d7f6e9c2f6c01644b9a79eb306d27f626d  scripts/hybrid_capacity_extension/edge_link.py
290db909f9570b321c4d4340f10b17fe31c4239cf5e475a426d2e92ec6a3ac7c  scripts/rate_dvfs_gate/run_rate_dvfs_gate.py
f9e38b2ca78c2ea4b8b2b44ed1db75b48e979342b360cdbca356d2e8d6d1ffeb  scripts/timely_capacity_campaign/block_b_confirmation02/grid_config.py
65e71d7143bc2a480bb2d9435891d13604fde53fa8d128ce00e500f015e61020  scripts/timely_capacity_campaign/block_b_confirmation02/run_thor.py
c0b0d04f31efd5463af2b95b907e3019cc8f77497fb2870a40e0c5408f38ce1f  scripts/timely_capacity_campaign/block_b_grid02/grid_config.py
d5ee119c4e1f8eae79d4909c71166a25bc83f9f2c29b1adf958ab750908dc007  scripts/timely_capacity_campaign/common/service_phase_b1/b1_common.py
2fc3bb7bb9c094c9abde1897896c743634ff845a736b982a23aaab5565cd542a  scripts/timely_capacity_campaign/common/service_phase_v1/build_adapter.py
7a8ef602df2f957366e2d41cdb358a60ae0d7fee5e599a6d5273b302c6fe580c  scripts/timely_capacity_campaign/common/v2_2/v22_builder.py
6f97bb4b60fe1de5cb11cd9eb4582108b9744d0ce2801b377500c498c157d26f  scripts/timely_capacity_campaign/edge_e48_confirmation01/config.py
f7188d9483ef721cbeee6d2d402a43afb2bb7605a8916854f4d17ce5c8af3914  scripts/timely_capacity_campaign/edge_e48_confirmation01/run_thor.py
9cc838d1171785495a31693adb593f53e6ff614283ad6ce49eabbf566946dcca  scripts/timely_capacity_campaign/edge_order_robustness01/config.py
e43b60f074181afffb73a2bbfd2e65e2ac74c9dcf2e2f2a5f3211fbdbddafa21  scripts/timely_capacity_campaign/edge_order_robustness01/run_thor.py
1a3064276ad9eda410a02676e6cc080965f9436078cd84d4706858a4085a2f94  scripts/timely_capacity_campaign/local_finalconfig_ksweep01/config.py
6a296b60964041b27fa3a049b4b30e654c14a39158effc30525d54cfa2376fdb  scripts/timely_capacity_campaign/local_finalconfig_ksweep01/ksweep_schedule.py
d99bd37a3753a6d6d801cf828798dd5e54fa58f69197ce281aa144d56f9c8abe  scripts/timely_capacity_campaign/local_finalconfig_ksweep01/run_ksweep.py
```

Frozen effective-runtime SHA matches the measured K8 R1 execution_runtime.frozen_worker_sha256: 6bf2c6dcce91b0d986480e7e82104dbc6310e6516482134062c8c9a1a04a7b6b. K-sweep derived worker SHA recorded in that measured manifest: 8aa69e967dcb740989d659ae2a91991f3f542cbe32c4418b225c0b39c0e14e52. These code/provenance checks do not run or reconstruct a workload.

## Deadline origin

This follow-up is measurement-definition provenance. It does not reinterpret physical capture timing, add a research contribution, or change any scientific data/result. The earlier “no Git command” statement describes the original synchronization-audit task; this separately approved follow-up stages the approved paths only after verification.

**DEADLINE_ORIGIN = SCHEDULED_LOGICAL_SOURCE_TIME. TIMESTAMP_SEMANTICS_VERDICT = VERIFIED.**

### Exact writer, completion and analyzer path

- **a_{k,n}: logical_arrival_ns.** Full Local/V2.2 writer: scripts/rate_dvfs_gate/run_rate_dvfs_gate.py, run_one → arrivals, lines 405–423; frozen effective_runtime.txt arrivals at 266–283. The shared target is active_start_ns + floor(frame_id*1e9/30).
- **admission_timestamp_ns:** the same scheduled target, not an observed admission instant. Exact alias equality was checked for all 1,317,600 source rows.
- **admission_observed_ns:** actual host monotonic sample inside the source loop, before publication. It is not the origin of the timely formula.
- Edge-only source writers: edge_e48_confirmation01/run_thor.py and edge_order_robustness01/run_thor.py, run_one, lines 345–368; due is written to logical_arrival_ns/admission_timestamp_ns and a fresh monotonic sample to admission_observed_ns.
- **Local c_{k,n}: completion_timestamp_ns**, copied from job.c_ns by run_one.save_records (run_rate_dvfs_gate.py:301–305). In the frozen effective worker, run_one → infer stamps c_ns immediately after worker.infer returns (effective_runtime.txt:203–208). ContextWorker.infer returns after D2H copies and cudaStreamSynchronize (common/service_phase_v1/instrumented_local_runtime.py:119–137). This is the host-observed Local completion, not a GPU-event endpoint.
- **Edge c_{k,n}: response_completion_ns**, copied to c_ns and, in the full hybrid trace, completion_timestamp_ns. hybrid_capacity_extension/edge_link.py, EdgeLink.receiver:95–123 samples Thor monotonic time immediately after recv_message returns, before decode_outputs/output validation; VALID data have subsequently passed those checks. expired_work_pruning/pruning_common.py:124–125 preserves this assignment and marks COMPLETED. Server-side edge_inference_end_ns is not the E2E endpoint.
- Shared summary formula: expired_work_pruning/analyze_pruning.py, summarize → counts:103–115 uses completion_timestamp_ns - logical_arrival_ns <= D*10**6 for completed rows. D=100 ms in all audited runs.
- Local K-sweep child/parent summary: local_finalconfig_ksweep01/summary_adapter.py → b1_summary → D100/campaign/V2/V2.1 summary wrappers → the above counts predicate. K/C cardinality adapters do not change the timely predicate. local_finalconfig_ksweep01/analyze.py:58–109 reads this summary and validates raw/terminal integrity, then exports TIR_source and timely_FPS.
- Grid02/Confirmation02: respective block_b_summary.parameterized_source/summarize preserve that predicate; respective analyze.py → timely:51–54 directly checks end-begin <= 100000000. Summary/analysis per-stream and per-run counts were cross-checked.
- E48/Order: respective run_thor.py → evaluate_session:319–320 computes (response_completion_ns-logical_arrival_ns)/1e6 <= 100; respective analyze.py per-stream calculation uses integer-nanosecond subtraction <=100000000. Both forms agreed with the independent absolute-deadline comparison.
- common/campaign_analysis.py → diagnostics/state:59 separately derives EXPIRED/TIMELY/LATE from the same origin. Stored terminal_state only distinguishes COMPLETED/EXPIRED_DROP; it is not a timely/miss flag.

### Independent recomputation and stored evidence

All 123 measured runs previously inspected were VALID in both saved summary and final per_run.csv. Warmup sessions/worker-warmup rows were excluded. Of **1,317,600 source rows**, **1,157,760 admitted rows** receive a timely/late/expired classification; Edge SKIP rows are not counted as misses.

Independent rule: timely iff a completion exists and c_ns <= absolute_deadline_ns. Every admitted absolute deadline was verified as logical_arrival_ns + 100000000. This classification was compared with the pure predicate extracted from production analyzer AST (without importing runtime/device modules), Edge runtime's millisecond predicate, saved per-run summary counts, final per_run.csv, summary per-stream counts where present, and final per_stream.csv.

MEASURED_ROWS_RECOMPUTED = **1157760** admitted rows.
TIMELY_CLASSIFICATION_MISMATCHES = **0**.
Aggregate/per-stream/TIR/completion-alias checks also had **0** mismatches.
Checks including scheduled/admission alias checks: **1474212**.

No standalone raw timely/miss flag is stored in these schemas. Thus “0 mismatches” means rowwise formula agreement plus exact integer counts and numerical TIR agreement (floating export tolerance 1e-12), not comparison against a nonexistent saved per-frame boolean. Expired rows have no completion and are not timely successes. TIR for Local/Grid/Confirmation uses all source/assigned frames; Edge TIR_admission uses the assigned Edge subset. Cohort timely accounting retains eligible completions during drain; raw active completion FPS is a separate interval metric.

| Campaign | Run | Source rows | Classified admitted rows | Timely | Late completed | Expired | Classification mismatches |
|---|---|---:|---:|---:|---:|---:|---:|
| local_finalconfig_ksweep01 | LOCALFINALKS01_K1_R1 | 1800 | 1800 | 1800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K2_R1 | 3600 | 3600 | 3600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K3_R1 | 5400 | 5400 | 5400 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K4_R1 | 7200 | 7200 | 7200 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K5_R1 | 9000 | 9000 | 9000 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K6_R1 | 10800 | 10800 | 10800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K7_R1 | 12600 | 12600 | 12600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K8_R1 | 14400 | 14400 | 87 | 14313 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K8_R2 | 14400 | 14400 | 208 | 14192 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K7_R2 | 12600 | 12600 | 12600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K6_R2 | 10800 | 10800 | 10800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K5_R2 | 9000 | 9000 | 9000 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K4_R2 | 7200 | 7200 | 7200 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K3_R2 | 5400 | 5400 | 5400 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K2_R2 | 3600 | 3600 | 3600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K1_R2 | 1800 | 1800 | 1800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K1_R3 | 1800 | 1800 | 1800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K2_R3 | 3600 | 3600 | 3600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K3_R3 | 5400 | 5400 | 5400 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K4_R3 | 7200 | 7200 | 7200 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K5_R3 | 9000 | 9000 | 9000 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K6_R3 | 10800 | 10800 | 10800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K7_R3 | 12600 | 12600 | 12600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K8_R3 | 14400 | 14400 | 304 | 14096 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K8_R4 | 14400 | 14400 | 351 | 14049 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K7_R4 | 12600 | 12600 | 12598 | 2 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K6_R4 | 10800 | 10800 | 10800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K5_R4 | 9000 | 9000 | 9000 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K4_R4 | 7200 | 7200 | 7200 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K3_R4 | 5400 | 5400 | 5400 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K2_R4 | 3600 | 3600 | 3600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K1_R4 | 1800 | 1800 | 1800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K1_R5 | 1800 | 1800 | 1800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K2_R5 | 3600 | 3600 | 3600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K3_R5 | 5400 | 5400 | 5400 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K4_R5 | 7200 | 7200 | 7200 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K5_R5 | 9000 | 9000 | 9000 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K6_R5 | 10800 | 10800 | 10800 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K7_R5 | 12600 | 12600 | 12600 | 0 | 0 | 0 |
| local_finalconfig_ksweep01 | LOCALFINALKS01_K8_R5 | 14400 | 14400 | 204 | 14196 | 0 | 0 |
| block_b_grid02 | BLOCKB02_L216_A1 | 14400 | 14400 | 12079 | 1855 | 466 | 0 |
| block_b_grid02 | BLOCKB02_L216_S1 | 14400 | 14400 | 11341 | 2644 | 415 | 0 |
| block_b_grid02 | BLOCKB02_L208_S1 | 14400 | 14400 | 14320 | 44 | 36 | 0 |
| block_b_grid02 | BLOCKB02_L208_A1 | 14400 | 14400 | 12563 | 1601 | 236 | 0 |
| block_b_grid02 | BLOCKB02_L200_A1 | 14400 | 14400 | 13075 | 1260 | 65 | 0 |
| block_b_grid02 | BLOCKB02_L200_S1 | 14400 | 14400 | 14353 | 25 | 22 | 0 |
| block_b_grid02 | BLOCKB02_L208_A2 | 14400 | 14400 | 12270 | 1805 | 325 | 0 |
| block_b_grid02 | BLOCKB02_L208_S2 | 14400 | 14400 | 11990 | 2214 | 196 | 0 |
| block_b_grid02 | BLOCKB02_L200_A2 | 14400 | 14400 | 13148 | 1252 | 0 | 0 |
| block_b_grid02 | BLOCKB02_L200_S2 | 14400 | 14400 | 14382 | 18 | 0 | 0 |
| block_b_grid02 | BLOCKB02_L216_S2 | 14400 | 14400 | 11357 | 2651 | 392 | 0 |
| block_b_grid02 | BLOCKB02_L216_A2 | 14400 | 14400 | 11686 | 2149 | 565 | 0 |
| block_b_grid02 | BLOCKB02_L200_S3 | 14400 | 14400 | 14352 | 23 | 25 | 0 |
| block_b_grid02 | BLOCKB02_L200_A3 | 14400 | 14400 | 13297 | 1100 | 3 | 0 |
| block_b_grid02 | BLOCKB02_L216_S3 | 14400 | 14400 | 11063 | 2847 | 490 | 0 |
| block_b_grid02 | BLOCKB02_L216_A3 | 14400 | 14400 | 11956 | 1952 | 492 | 0 |
| block_b_grid02 | BLOCKB02_L208_A3 | 14400 | 14400 | 12617 | 1629 | 154 | 0 |
| block_b_grid02 | BLOCKB02_L208_S3 | 14400 | 14400 | 11824 | 2321 | 255 | 0 |
| block_b_grid02 | BLOCKB02_L216_A4 | 14400 | 14400 | 11727 | 2091 | 582 | 0 |
| block_b_grid02 | BLOCKB02_L216_S4 | 14400 | 14400 | 11551 | 2474 | 375 | 0 |
| block_b_grid02 | BLOCKB02_L200_S4 | 14400 | 14400 | 14388 | 12 | 0 | 0 |
| block_b_grid02 | BLOCKB02_L200_A4 | 14400 | 14400 | 13313 | 1083 | 4 | 0 |
| block_b_grid02 | BLOCKB02_L208_S4 | 14400 | 14400 | 14397 | 3 | 0 | 0 |
| block_b_grid02 | BLOCKB02_L208_A4 | 14400 | 14400 | 12574 | 1576 | 250 | 0 |
| block_b_grid02 | BLOCKB02_L208_S5 | 14400 | 14400 | 14343 | 33 | 24 | 0 |
| block_b_grid02 | BLOCKB02_L208_A5 | 14400 | 14400 | 12548 | 1691 | 161 | 0 |
| block_b_grid02 | BLOCKB02_L216_A5 | 14400 | 14400 | 11975 | 1955 | 470 | 0 |
| block_b_grid02 | BLOCKB02_L216_S5 | 14400 | 14400 | 11265 | 2702 | 433 | 0 |
| block_b_grid02 | BLOCKB02_L200_A5 | 14400 | 14400 | 12339 | 1841 | 220 | 0 |
| block_b_grid02 | BLOCKB02_L200_S5 | 14400 | 14400 | 14318 | 53 | 29 | 0 |
| block_b_confirmation02 | BCONF02_L216_A1 | 14400 | 14400 | 11883 | 1991 | 526 | 0 |
| block_b_confirmation02 | BCONF02_L200_A1 | 14400 | 14400 | 13168 | 1228 | 4 | 0 |
| block_b_confirmation02 | BCONF02_L200_S1 | 14400 | 14400 | 14390 | 10 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L208_S1 | 14400 | 14400 | 14305 | 95 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L192_S1 | 14400 | 14400 | 14251 | 149 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L200_A2 | 14400 | 14400 | 13124 | 1271 | 5 | 0 |
| block_b_confirmation02 | BCONF02_L200_S2 | 14400 | 14400 | 14368 | 25 | 7 | 0 |
| block_b_confirmation02 | BCONF02_L208_S2 | 14400 | 14400 | 14246 | 108 | 46 | 0 |
| block_b_confirmation02 | BCONF02_L192_S2 | 14400 | 14400 | 14333 | 67 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L216_A2 | 14400 | 14400 | 11869 | 2010 | 521 | 0 |
| block_b_confirmation02 | BCONF02_L200_S3 | 14400 | 14400 | 14336 | 41 | 23 | 0 |
| block_b_confirmation02 | BCONF02_L208_S3 | 14400 | 14400 | 12305 | 1932 | 163 | 0 |
| block_b_confirmation02 | BCONF02_L192_S3 | 14400 | 14400 | 14208 | 191 | 1 | 0 |
| block_b_confirmation02 | BCONF02_L216_A3 | 14400 | 14400 | 12075 | 1879 | 446 | 0 |
| block_b_confirmation02 | BCONF02_L200_A3 | 14400 | 14400 | 12936 | 1374 | 90 | 0 |
| block_b_confirmation02 | BCONF02_L208_S4 | 14400 | 14400 | 13128 | 1154 | 118 | 0 |
| block_b_confirmation02 | BCONF02_L192_S4 | 14400 | 14400 | 14324 | 76 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L216_A4 | 14400 | 14400 | 11944 | 1994 | 462 | 0 |
| block_b_confirmation02 | BCONF02_L200_A4 | 14400 | 14400 | 13173 | 1220 | 7 | 0 |
| block_b_confirmation02 | BCONF02_L200_S4 | 14400 | 14400 | 14307 | 93 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L192_S5 | 14400 | 14400 | 14296 | 62 | 42 | 0 |
| block_b_confirmation02 | BCONF02_L216_A5 | 14400 | 14400 | 11830 | 2005 | 565 | 0 |
| block_b_confirmation02 | BCONF02_L200_A5 | 14400 | 14400 | 13218 | 1182 | 0 | 0 |
| block_b_confirmation02 | BCONF02_L200_S5 | 14400 | 14400 | 14352 | 24 | 24 | 0 |
| block_b_confirmation02 | BCONF02_L208_S5 | 14400 | 14400 | 12383 | 1853 | 164 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_A1 | 7200 | 1440 | 1159 | 280 | 1 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_S1 | 7200 | 1440 | 1432 | 8 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_S2 | 7200 | 1440 | 1354 | 86 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_A2 | 7200 | 1440 | 1076 | 261 | 103 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_A3 | 7200 | 1440 | 1206 | 234 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_S3 | 7200 | 1440 | 1440 | 0 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_S4 | 7200 | 1440 | 1424 | 16 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_A4 | 7200 | 1440 | 1245 | 195 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_A5 | 7200 | 1440 | 1184 | 256 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E48_S5 | 7200 | 1440 | 1438 | 2 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E64_S1 | 7200 | 1920 | 1440 | 476 | 4 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E64_S2 | 7200 | 1920 | 1812 | 108 | 0 | 0 |
| edge_e48_confirmation01 | EDGE48C01_E64_S3 | 7200 | 1920 | 1875 | 45 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_BASE1 | 7200 | 1440 | 1047 | 325 | 68 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_REV1 | 7200 | 1440 | 1195 | 245 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_ROT1 | 7200 | 1440 | 1088 | 263 | 89 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_REV2 | 7200 | 1440 | 1202 | 238 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_ROT2 | 7200 | 1440 | 1174 | 266 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_BASE2 | 7200 | 1440 | 1148 | 264 | 28 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_ROT3 | 7200 | 1440 | 1201 | 238 | 1 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_BASE3 | 7200 | 1440 | 1035 | 380 | 25 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_REV3 | 7200 | 1440 | 1191 | 249 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_BASE4 | 7200 | 1440 | 1238 | 202 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_ROT4 | 7200 | 1440 | 1172 | 265 | 3 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_REV4 | 7200 | 1440 | 1203 | 237 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_ROT5 | 7200 | 1440 | 1138 | 253 | 49 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_REV5 | 7200 | 1440 | 1208 | 232 | 0 | 0 |
| edge_order_robustness01 | EDGEORDER01_E48_BASE5 | 7200 | 1440 | 1213 | 227 | 0 | 0 |

### Paper wording

“End-to-end latency is measured from the scheduled source time a_{k,n} to the completion time c_{k,n}.”

“All active streams in our evaluated workload share a common source phase. At each source slot, one frame from every active stream is assigned the same scheduled source timestamp.”

If implementation fidelity needs to be reported: “The host-side observation times of frames belonging to the same source slot differed by less than 0.1 ms at the 95th percentile in the Local-only K=8 runs and by approximately 3 ms at the 95th percentile in the campaigns that use the edge path.”

These statements do not imply synchronized physical cameras or simultaneous queue insertion/GPU execution. Host delay is not promoted as a research contribution. No main-paper LaTeX file was edited.

### Deadline audit input hashes

Raw and manifest identities already appear above; this list also identifies the saved summaries and final CSV outputs used for the independent comparison.

```text
a1cb0071641f8277f40006de5f33ece634ec731635d8e0dae34568550ce3892f  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/analysis01/per_run.csv
c8e467ddde57bc4e244e2991f15180bf518b075bd43df148b9631b4886ef2bf4  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/analysis01/per_stream.csv
92f3ab29f27a7fd054800987962ad709682913e7de0494ef874d233d7e8a6adf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/per_frame.csv.gz
8fa9d29f2dedc0d5795a5a8bae7d8279f08487803246c8af832a24f0ff3968bb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/summary.json
b561aae31d8925a388c431de464172c67a21aeb7f68dff7fa2405d2257134576  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R1/manifest.json
8d0899f57d06a9cad9802e940a64efd3fb10b6675ec1976ca15e2ea2239003cf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/per_frame.csv.gz
e924ccd5d0db7eac721fa6da4b2a6df52a37c28bd251453a8352a113de466d4b  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/summary.json
a9a2b76331fb2bd8d6b19362706e0ca602347cd9649172571b8304e0a058774f  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R1/manifest.json
e81efd7382eaec1b90b5e1d3810072cfbe8c20c0f9409a804b08df6226de9c2e  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/per_frame.csv.gz
6a9e6a825a086419a5e3de11c88912aeb5072123931fbb2a43236afc4c642603  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/summary.json
08df19fd34de4e0f980ad58a25888bcbc6fc86f08cae0b4591749f57c3545cab  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R1/manifest.json
2745b14682d2eb1c5f988bc4756f405c192894ec6ef5d62eaf6375cb37a80bff  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/per_frame.csv.gz
085c955e16574be32888031e61469a4a3d236ec31b07cc83ae9efb427cf3c13a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/summary.json
83bede9655ba696b5eee03e7cf2fe363e433eeb0188d98e3003fb9f8541a6c59  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R1/manifest.json
26be9b57006e17be36ea97eeb3a260de3c88121a6df18a048091d22b51df40a8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/per_frame.csv.gz
b5b1fd9b6247b96aa6e3f1e83b2a7c7c72acf123398936094d73ad3c3027a0dd  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/summary.json
2dca25da6595960934dcdf489c2f59726ea77df58d3d5deba412eb0fc46bf362  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R1/manifest.json
de3bb9cb31d658f8df22ed1451df31d6f803631a19c2c9c7514ca0f2b1fbd3d3  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/per_frame.csv.gz
11e388ef92f399af58ecc8f9d8e43f0ab8355a6a771e3fb7c3a0d5370e048dab  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/summary.json
bbfd85c27ab9928fff2c9c77a97fb60076cfe571784f7ac29dd5af1e4ad24938  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R1/manifest.json
c84650344cd0b84205cac92f6ef453d106b3ebc5d10dd819fa389df67a4ca218  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/per_frame.csv.gz
5919be39a5a38748244abd15aa7967b955097077ed50e4eef225a02c77469d1c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/summary.json
b23b5ff2a484baa070253161cb20b4a764a636ed4592163f9d4df25e8815242e  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R1/manifest.json
a76f8efe99590cd83b074e8d479ec3f57574c18233ef3e81a76781ee84ad8d91  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/per_frame.csv.gz
d5a0a48b941f91546b7e399e5f8e8a22c34ada8b80f3c9b02d81ab6bb6c939d5  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/summary.json
ef86f71c9dbebd29e54a58ac4715dd63705b15406e8fed1491be8614a2894c4b  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R1/manifest.json
e27d53b01a2dfd0b02403b423ef12c9dbc96385022926906e7ea975e61f8b268  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/per_frame.csv.gz
44793dd39e3acc11dfdf57946f17e682cc443d93fd84b3f0e4f189d9659b7f4a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/summary.json
e6be4b893b7a257f695c5d1e911fb0bf8f84fdefb63fc8a1a03c49b11d49c275  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R2/manifest.json
c06d309a5ad846902032268d95af407d29f2f53c828f07cd6932838c1c13469c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/per_frame.csv.gz
9d0f9733e0c086351c77ee750cd9342eb693eec1d47c09c75ce5aeb817e5133f  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/summary.json
260699e80ffcc764668398a5c5d7e6cd6ad9bc828cae2a14a304498fa764587d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R2/manifest.json
eaabc07f8744aa217dc8e8e53d6c70220f5cf5e6b1da43f05b0126dbfe3334f8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/per_frame.csv.gz
f7c9dd8d39316778beabef8a13513aa989186b35848e54b783fe24998fc4d77a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/summary.json
44f1b5a86bdf227353acb16c99fe7c5b3f024c3e8504f486e3be589a1b4ca6cb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R2/manifest.json
330a5dd31da8f1e51cfc4d502a07fa8f9e3c4c305e53f775708f5ff1bc7ab41d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/per_frame.csv.gz
54fc5d33e1dcb5ae12bc56d55379b61e250a09933f2a192aa32718630f3562d4  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/summary.json
c5f2dc5cfa64da280e29c7286eb819320c82e3b0f0868eae7ecb61feced5b8aa  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R2/manifest.json
062d8b8c80ab7c499f14b6bce370d630b1e2461c520818d0290b22e294e2150d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/per_frame.csv.gz
8b6f1b5de172ebea173e80338d7e9ee27d222633ffcaffd00a04dc3e231386fb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/summary.json
0bbd72c8680b0ad54d8f6408c46a256c709fff9b6d50eadda3bced8acc19930c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R2/manifest.json
2b071df339c3d1e332eec5cbe07a9d39d267b48f347dd8d0f60c97e69f3bf9bb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/per_frame.csv.gz
80c1ccf389f9e0c1e25a3a6bedf08bb41436a20ca6bc435b3f17cbd5f52e43d5  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/summary.json
1e80bad23740b1ff488c4f75ba7306ce0d2c64b0041bd615b21f28a2f48b2fe0  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R2/manifest.json
488445feb7fd62eb3cc5f682c524b012a352a9928ab79db828885570a0c8100a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/per_frame.csv.gz
783dfe41248020ca79ada25205c0c803e47601983effcc88b9bec9307ec76ac0  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/summary.json
e5d274ea0ac2464c443bfde83ff42e1bb2e64b6a87127abbaa89c0cf5ec624ba  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R2/manifest.json
dc9e7ad0b1b5b7415dcc6b5bc99417364aa681d82e0a15857563eaaba0db9209  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/per_frame.csv.gz
b78c10e2489bbb0cd15e398e4ee7383af61db054afc8b7cec932238a66f26985  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/summary.json
4a164772433bc62940cb89b7818cb2a99a9f2a8526b51cba66be3463a46ebc92  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R2/manifest.json
50d20e6908bb6f389f8bd5ebe1f57ea16deae91f3a6815d5851f24a2843c759d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/per_frame.csv.gz
cf00c5816d41126064f732e59c17d8753fb83ac3a870f4ca7b1243b5c3546cb7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/summary.json
653f4421e8059d55f72c8698e214a20ff5a4c93f83756ee92b1b6d06b79738bb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R3/manifest.json
f3941b789e2a64a4956b819bb27427c831394f5eaa4062d6ad81f05b6f75bc1e  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/per_frame.csv.gz
99e1079f35d936060ab86f099ef9b0df4c13b1feb9ceb78f51bb9b91783b84a2  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/summary.json
8627d189e926525f000780f79a21e3483b206abdffa3617d35563f02135ececb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R3/manifest.json
efa3ef71a28a8ec7a7844c608bea18f6c1f7ae41ff2882eb18615bf6ff881ff0  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/per_frame.csv.gz
2421b81d3ed7d7b73cb1538cd7e6cb6978dcd5906680bffae3bb548eb709f018  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/summary.json
783d19b046f14f43e062d12b2568ac7e82e8a1858a830f6cb1ef805ae99d1d08  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R3/manifest.json
5bff3cf7882f390620040bf8d0d65f19a4965eee98852fc24219c8d9462df408  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/per_frame.csv.gz
8b61ce87a408951ce4ce410cbae0a9a865c982fbbe6825eed1964d24c167d4d2  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/summary.json
05e48908e0f00ee73ee610c471777694ff3f3ea29fcb15a42714bf8bf953e797  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R3/manifest.json
9e626a215991e5bc54272aa4907c9bd7c80c8711925a2d980a7befb54fe4d1a8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/per_frame.csv.gz
76fada3b90ddf679374a6afcf8b8bda6a587ce1f4d36126742071ac21de7e130  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/summary.json
a5cce6deb57ef613023174949529165565ce91ebf5b0e4bbeb23f512d6fff5a3  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R3/manifest.json
00e1033b3d3842ba0faee1ee20d21e8e1ef7f29b2aada3ea6f8e870f5a7c29e5  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/per_frame.csv.gz
0c5d3a9248f143e528db67fba8fde9edc4d811b2119399d5a3544840d017bde6  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/summary.json
052d554d90125d0f8f8738e94de11f8c8470247d547daa62fc3d188780101ff3  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R3/manifest.json
c6d7251cae38ec9a7be2cbfb512695c31ca394b4e6f8df8705408d6246f56e0d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/per_frame.csv.gz
7c4c56e2169e90ad4224077d8cfb71b3b1b24983cd225b2604efc94ff52e625d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/summary.json
fb1eef265e1d3c86dda2d9e5ec3392b4d52d27b919057eb6979b79dd6ec2774c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R3/manifest.json
ded9ba4ba8a0abcc022437780542ba4b4996a791ec2e09118601c82967c24724  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/per_frame.csv.gz
6976c0df506a94896fd76ce74b81227ba7e58b0db19a69099d2b078cede18103  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/summary.json
9ab205da6e424c50bd42853f1d0ef5e0d9371324a7bfedd34f41a11708322a3a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R3/manifest.json
24f1670d02abb24763bbd0305706780a3dfd250e7441210ddf9e8e4d588abbb8  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/per_frame.csv.gz
a7565da25b89fbc4a2e67f2ba98a8c8e4cd1ee4286f0b1e158b32d7d65d93f81  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/summary.json
cb1d09c6b902a2d4714e62da9c9b89f955c602a6b6b9af5f20c7b086817012b7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R4/manifest.json
17b21388d79acaeddd8a62d3138507a99216cb8a3e25db1bf93326a1bfc096c9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/per_frame.csv.gz
ba9e8da154f2e3ef9d95eb9a0d69458a3ad12a8b6bc9b4a190de87da0e564943  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/summary.json
a5cb066128fa003be46c5d7543d029f8b9cfd7ea71fa443aa802570430e37f1d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R4/manifest.json
d22578b3eef4c24aeb9778e61a766fed21fcf6e41c75992f32a47367767b67c7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/per_frame.csv.gz
2a51527effadfdb814fec1a98ca7f7dd0d702358396d22b01dec6b263ff603fa  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/summary.json
f4bc40fc73e2ecc3bdc7e150e853a5e085c5c7063bb80201f2a66594b70d4f5a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R4/manifest.json
e19c88df0b33bf786f9e50364769b0426da3aa38395e332ed287dc7025f552c4  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/per_frame.csv.gz
9dc71992d5f5a140cb4971f48816ee5660efd2e9e6f9db9cbe52529d64facc0a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/summary.json
fd151ebf873bc2f0f6e96b87768ca2389d394baa6921745efd3fe26540b36edd  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R4/manifest.json
936351164c64c31c16e8617d7e5743f71ae1bbff68b2e114300aa2717b0b24a9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/per_frame.csv.gz
8e75309feef3ec1444f4a0059559a709e20db991ec29cf5b0ece39238bcfdf2f  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/summary.json
bc20a2d0e4ab461004ea0b7f959b04370d1473f95e6c0d9e8a0627031b45e118  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R4/manifest.json
8841162979cd2772510cf44eba9951dc3235962f41167ec098604522f9da6fca  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/per_frame.csv.gz
6cdcc564fe1794f5dd6a61a1329b2223ae04f1a0e7e0f7070f0523b5d9f91507  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/summary.json
7cb565748359c06f4bab7176bf22c15ccb2502569d4dc76595e33f9a84da02c9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R4/manifest.json
84b41b5992d29d8de8fe11861874780f68118d0d5650a447902fb7f6cde8bec4  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/per_frame.csv.gz
448d5e9948942f01e703a5d1a7679067a5b30928db1722e8afb0c246e288a9ec  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/summary.json
11722e9ac2753dd4f7a129c60644dc6e7495dcb63e42d8ef6ab10b96849cbe21  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R4/manifest.json
b5047d4fd5e77b8be82747bbbb0de12db360f382d00475acddfaf1f6f926b411  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/per_frame.csv.gz
73d2726f5f32c1f5218022961b089ad745c444fb7d196ee461bf6be223554636  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/summary.json
7409c1f7313df14dd0f1a87c4c9ad6a1de7c7f82e5ce27818012e8f9f36cf399  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R4/manifest.json
9fec054473b67fb407e1890bb10e083de8ebeb95da07454c29270b8e96f22999  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/per_frame.csv.gz
890e8f76c2a39c7a7cab4e16c38d5f41457193a21162a3ca0ad8d69287212adf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/summary.json
2dc1cb8b3f92b0a9f69850923153f8add3ad0b8e46a4c3e3ea9e0b255af97b39  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K1_R5/manifest.json
f55c8cbfd4590065082a9907c5835263e705fe0fc349f3ff560e5039c9f3c1ac  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/per_frame.csv.gz
7c0407a096e46bf6d1067fc5acc719f24c488f26f6e8a076fdad4184ef80df5d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/summary.json
9aa9abd6602264526fdf2adb4c3b0eea5cf5da2eac6b30363ad64b3548b8b1b5  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K2_R5/manifest.json
bca3296cea014f7529bcfd9ec0d123e8f267e5b87260ca1289df7d52356d76a7  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/per_frame.csv.gz
6a057d237b7a6f01aad2a0b8e944c8ab387321b8f71218ed13f4eae7f9cee00c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/summary.json
2ad19e8756f9a1d55204e635a3b251d75bd44cb5c9682d0c15d9860a22b1260c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K3_R5/manifest.json
e519673d216debe11dd651e7c75ffaa9c2f3aab83c25b577d62a6ec0c9014414  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/per_frame.csv.gz
838648fa6d11480ae7385a9ad91d93d0db93072853dcd75d76c1e57019e9c5c2  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/summary.json
64c262cdcc5f63e55a4e548b6c874280c96410fbd811d03e79c5fd267e0d923a  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K4_R5/manifest.json
55fc1b0e7d73ef623ef4f1adca2047ea3ca9e710721c2ef4b42e770d3986cf21  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/per_frame.csv.gz
660cb4be9ab66da2d62aafbd9faeb0359cacce68f12b493146d7cdb0a5111b5d  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/summary.json
526ea7fb09dc5ce83ab06b44cc246f394d365852b957755d78339d89d07ee8df  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K5_R5/manifest.json
869298d39c23eae71eceab04ac6281c15f4a2608381f930fab7c134bb0f0b10c  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/per_frame.csv.gz
7ea19281688806be2784bb00afc044dbaf695303021ce6ea654d76e64a0995f9  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/summary.json
5f9276e9ae942a27034a2c974f6e99d0619afa53767562dbda52faa75cc36b38  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K6_R5/manifest.json
59a2394052e71f0cbea7ffecaef67e5be888e6966184913167aa9c2a6724d769  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/per_frame.csv.gz
598d809dcd4164e259e83ef4f88709d61c27ef0939ae9395bc048e6d6e4a999f  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/summary.json
ec582171f0629101281c6703b9df78368440c30b88ba4fe59065994dfe060cdf  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K7_R5/manifest.json
bccd1a10e6785e1715e29d88b0934c79540496e557f988f6bc542b4125a56256  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/per_frame.csv.gz
c53c657949fb4e0fe5bcadbeb74816698c4dc28ecf9b2b26f11c81dc2b7f3d81  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/summary.json
11e299624cc764c66b1bfe04de01a8d5ef798e7ac5af4cd7ccacd0672b0c99eb  results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCALFINALKS01_K8_R5/manifest.json
46ad26be57d36717653531915627483fc071c0822dbda964de516a2a0d865356  results/timely_capacity_campaign/v2_2/block_b_grid02/analysis01/per_run.csv
d324280c01245df9ceb0c40afe28063095962dbccdca39ae0ab5fd5755005f56  results/timely_capacity_campaign/v2_2/block_b_grid02/analysis01/per_stream.csv
ede34631687a8e0a46451aac7a5ffd9fb480e9b8b65ee60ae8b2b83863406c24  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/per_frame.csv.gz
c6b0cdfad84e933b22ad827b5fc46091abdeefa1b5b3e0e22f580cce805925c3  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/summary.json
5dc8a68c9012a62885b590d5e869a9838197b7ec4b9823eab40125c9b452bf08  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A1/manifest.json
65da008fcbfa6b2e6f529dc6423f1904b00c3a5b198c487d0b21dbdee6b4d4b7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/per_frame.csv.gz
af7dddaaf2b6539cdc2f22e3ba891cfb4fbe9863588973879defc7d42f7b0ea7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/summary.json
d651b9b5d038513c8bb42d7fd39a08e871854998f960ca0154cbd0923e57c409  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S1/manifest.json
9a9cd6a2c1e6595d7b651a23fcf19b2f0aa40c0ca06e177958a277e8e9e04018  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/per_frame.csv.gz
99d344c4996fab6cbbfa211126463104d150eccd804d6e68499b12390e53c57a  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/summary.json
5b9c80efa007ec2a0a7cc4b584e4092888530105b84c5793dfacc3491c7a1d79  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S1/manifest.json
ab316a5ce1db555cdd7a80f8c86ef0cd0aa0bd74d5f8ff9e6af9525d3ada1c8a  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/per_frame.csv.gz
58e924c6194899a5ac6e534bdf0618227e4b832806075f3657e5ce6425364858  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/summary.json
d8dd7d060378a8f57a0c7639d36c9232c42cdc7557331ebb9781c6182a6c064e  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A1/manifest.json
47090ac9378cdb373459bb4781e1310f11cf77c15cf6e69a2193dece3e929264  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/per_frame.csv.gz
5ccc9a5c4e3178ff631fff223e120874a9dcd984a34730b8f988c347f3c6e006  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/summary.json
346026e76f3a123c0cc959a8c10d25c7ecbba0df5a5ef937eceee53141182c30  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A1/manifest.json
74477531c3ac159a17a9dded3e06db01f82c54044f1e9394aa2f15653bf4e3dc  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/per_frame.csv.gz
901a6b2b3889cd382959afac678031b1b0ed1527d7cfd8f147ed823155961644  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/summary.json
86cbe5ae46278f1b1453d60e0d585d02a471c7a21e1a68404659c7c03b4b6727  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S1/manifest.json
a87fc19d9091c40e2a2db0d7b519931f34a7d6b64d856fdf4f644c15ebdb40a9  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/per_frame.csv.gz
74bc07fb0c326e47daeeb6b71059773126b3f15b017fb402cdae20271fc18f1a  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/summary.json
b98067477e424dc55c3bde5ca3161639e47d2f1c2dde1f8b412da5ca83e8edb5  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A2/manifest.json
98d5358c1ed16d8074f2c63abd1792e8a4616ba1979d077fdd7a3c32d44e4725  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/per_frame.csv.gz
6be667316e1b34c13a6b4dbd64132b73209ea7173699c7bc5c499619cc7dee88  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/summary.json
54fd396867a053fd5c723ed2cf3123088f3fe63da64213a6bcee95e168879216  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S2/manifest.json
49730a7e8485d2c48e003291bdfe951fcff3b2d48ca2c1fd600fb4c148c77726  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/per_frame.csv.gz
39d317041f85a3f55a6be1847963bc58043cd71615ec09c26218305f98e3c3ae  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/summary.json
5964160f4e5651dadec47b68d4d11d7ddc083d5833061b395434cc3f5d6132f3  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A2/manifest.json
29eefe032e3ecf43a28b0a21f8c4946d8037142d2e3ca2bc79027bee4ae271fe  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/per_frame.csv.gz
7940b0b7c682d049c62ba5a4545532a7cf6ecbcf401c48bea64ec945e22a80b0  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/summary.json
70f48a1fae38804e3e4dacaca6cde659724d31394d4a5fab3415c6cec4037483  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S2/manifest.json
b9fbdff870c3eae20c85ca79d44c737aded81a2f3477351f4b1c0fd8e53b02c3  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/per_frame.csv.gz
bcf20eb4ae21c3a7caedd51f5d4c1a60f3b7c88601e9310b2111376f129c2034  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/summary.json
135668f8a93fe5a829a53f50fe001b5f78079d9e8b4aae3cb6e25067158265a4  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S2/manifest.json
4c1627381011d3d9979d488963b9006a68fb174bfae3e8567bd46bc24f5afcce  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/per_frame.csv.gz
4abc710a14d7f7d0483b275fdddd4bc2ffd1941111e9907f37f341af39a2b385  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/summary.json
9ae33dfdacf1ebf82f293cd4d9adff1f1d88ba77d85e9e1524863439588faa2f  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A2/manifest.json
e7f96266e104da3e4e2168b1d2b902ee62d62214e0afcdbb5448bdf68a2ed32b  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/per_frame.csv.gz
b74fd8e4035ce2ac826469f74262faa0844b6c0474a3f5bc86fdfc2fb03005d2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/summary.json
1dc146cc2d4dad8b81a88745acab752f8842ada4e5fedf0da52cf97fbdcaff4d  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S3/manifest.json
57a348959ae70012d4a8536c6a406f71d721efd4e31a0a6d438b8657e4602142  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/per_frame.csv.gz
18262d442aef334ba767df7b92fd8ee8b6c107f563baf22e5c92f2d7491679a6  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/summary.json
e3c40854cb7d69a3c968ceaf5f34b6b736a47b7c05070d7c841bcae85f54a1e5  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A3/manifest.json
ac68f2d502eb8f09284ef7d1ea68e1547c9f473f3838fbdfe3be9ca5b9afe6d6  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/per_frame.csv.gz
43607c1364c7de3d0e3c7f656a18abf185e7952041d4defb2b062e4a1cc938e8  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/summary.json
17a8dfbcbf1b6ee334567365b4b70f0638593bcbe5083580b48074d8567ad387  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S3/manifest.json
2e70e915692c2efe3ed7e533d8eb4c1bd2b09797814c8cf4fa2af1fe92fd0d68  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/per_frame.csv.gz
25469a45d6718d204a6508460980d0e7a19bcdf903c8ff5cfa6a19fc99af6b11  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/summary.json
a192dd830f9fb407794a5acab26b247f190263487f3fe8018ecb29a074fe2527  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A3/manifest.json
76566a0e3246434dc00d283e6affe59312e493cb4c02f57b4be2fcd8c809d672  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/per_frame.csv.gz
ee2a5a2afcda486b0534357e21402cc6c354ce8b9b8a00f1f8f78e9fe2497f92  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/summary.json
9963111f090a574594af481e95e561e1d514c6c766a09077888772e900ca4799  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A3/manifest.json
328c188b73d2678c2968842eadf2ffda8a67dbab0da33f880d6a8a704fb2ecd2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/per_frame.csv.gz
ee6b2553799171723013e16f41c984e5d2974d3aeb6502c9a9e6b024976946ee  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/summary.json
1c375afa3b094eee76f5fa7768f9f3a2e18dcf6b0e5178d9ede54b2761cf12ae  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S3/manifest.json
d34f77e0f499bce7c4c4282584dc6f0b7957183a3b0d50184fe471d9a9df7cd6  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/per_frame.csv.gz
e488d66ed6034838dbc8a16aec3c43ffeb617d360c5b52d7c03900036b3367fe  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/summary.json
44db1cfa4d07b4437f51380983df83198577d96843446fa9f85bd5fc14e222e7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A4/manifest.json
f4358f5f0363330f53cbdfecfc0f49a988e9765471b74906172f8d234dbaefb8  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/per_frame.csv.gz
021b1b28b85f8f58d1253c7104a65cd1cabc684ff51c5286576a56ab309f6f19  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/summary.json
b421bb220626571c955c21821e3a7c38fe24a128cb6ca099c70053057b779986  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S4/manifest.json
9b4cb1bdecd42b12266a2d920a37c56190e27f2d355f59efbc9ecda5eda03ea7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/per_frame.csv.gz
628fc053e8ae403a1456183d72d31887e78efff5976dcf7e06c7bc9eb11d1916  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/summary.json
a91864fb559ad5da331722b6a3749b30416459ecbe0457ab3498f83abee0d33f  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S4/manifest.json
c17c7148f341afb393ae016a022ecd1e715f02a237fc00d13cc102ac8a7e5d9b  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/per_frame.csv.gz
47af91a46f40ed62ff418472b9e1bd0a96720ec52ad99cdc53c7eb0073d1bca7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/summary.json
0b66093c996912e75d6c1779e81e97b79f81284bc3638bb329012207833485b9  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A4/manifest.json
cf42e4bcade34e3048fff0ee4483c01341a4c3f083ee5c5971438233878fe1c9  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/per_frame.csv.gz
75af3116b52cf5e0e5e53e761215c9d4057f89949467c2f667ea9e2ba1fa5224  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/summary.json
48b1d39c214b1ef6cf093078b5c4daf90be996399ae2cb707912dc3060e05fae  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S4/manifest.json
76538031d2a852530c36f25faf09628007c839dcb73e6ae7cbc4a005300f4ffa  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/per_frame.csv.gz
1cf69eef4f8463f7a486cacc9852304ca66014284d929e05a9d9690d067b3f80  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/summary.json
2ca2fd47753bb9722b9a72e36f0cdce8ef8f5c470147965bc8a60d6a6a1653c7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A4/manifest.json
42a27652588588b866ff4528e6548457d1ac122391354d390b59638dd50c05fb  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/per_frame.csv.gz
559653041731e772f9935b1aadbd038d243163eb3ce3f6318f23e4a1beac6a90  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/summary.json
5a18168e96ec0e8b8cbf771a1101690c3e241d1bb1e48e567553fd9a71a2f899  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_S5/manifest.json
14566f1cd93aa1a7b344920a53801752140cb0c8c0906d698de1d1dd668bf3e2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/per_frame.csv.gz
7fefebb11841d28dc1d0c2991c000c182038dad9853508b6b055889160b291e2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/summary.json
c6839927d52526f86860b06ee621fff1b271680a4e04872e3852a3bad7816530  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L208_A5/manifest.json
a4830b82bd52a4f7612a7ab8eb2715ec65e002392ea3fb8da02e091ee2df54cc  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/per_frame.csv.gz
cdf8b5591252b6215031b50abc4ea9fd6690547fa13af55854745f1ab562d73f  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/summary.json
cb4c0e01650a78c7d6e1ce0ed85f5a5d16ad3fb9b0303ea1525565d9688a7427  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_A5/manifest.json
29fa4b1bdcbbbf38265642d55e96d76e0641cdccfcac307d53cb17b93b7505b1  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/per_frame.csv.gz
271eed3262c0a1188268fefd102a76d2b0240ce9543b2190f00b088f34979022  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/summary.json
f422cee8aa314e6002b725731756ab383957d026f283bc1cdee86e11dd8b3901  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L216_S5/manifest.json
50fe980a566086f0ffd4659bd2585091750c43c043a85b7286baf07e5b09b449  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/per_frame.csv.gz
9d7af09680abb396ab9f8e9de0194083b9436263d9b11d30fd46215d3b44b163  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/summary.json
3eb29e1d7244e7508679e0e64a7a793463b1c36e13fbf980c14176ccf2a5e05e  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_A5/manifest.json
085f69b3d09f3a0a8af40c1c5f52def3e62fba166da3656942cf7b7b425802a5  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/per_frame.csv.gz
471b70e4ae910bd2ba07025a506ccecd522fa05b7e75edb321520add8d794dc2  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/summary.json
7f00c6760f23958345d5e4c2b2b9835aa7ba073ffaa2a4d3dc9b30f8334ecfd7  results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCKB02_L200_S5/manifest.json
3e5885412ff3ef2e4834c56889662c3c43287d05cbfba3b50ca257fa152051e4  results/timely_capacity_campaign/v2_2/block_b_confirmation02/analysis01/per_run.csv
fcad4de9af17ec4a4b58137260bda70318fc5ee7f1c67e8fd27e793cbb5d10f1  results/timely_capacity_campaign/v2_2/block_b_confirmation02/analysis01/per_stream.csv
55c1a26835f1dfd2d629476736dab2d9672fd2cff5c9d8915f9f30ac1d6bc051  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/per_frame.csv.gz
c4b1a8eea162ebf005599f1ede7b9caecbe1945fb24794f2fc412d555667fe0e  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/summary.json
915c73aec198dd0ae8c7b226d21331a846d26361e236fa0381f385b152307d5d  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A1/manifest.json
a856dddb10670f297e4434190db47cc2f73247a870d3ac074dfe2c6e6e17fc7d  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/per_frame.csv.gz
7255e0b887fe4d8c57e5f1f5995182403d2ceb7b6e58d32e533521beeef44db4  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/summary.json
0ba1d4feb81ac62e5462d8b7cded3d06a5c79d549eb5b22603deff99c92ca954  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A1/manifest.json
9ed299552fe7e06af354aef81a2321f5a64d6c36a92a3c89629425ffaea2138e  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/per_frame.csv.gz
395277da67de7fb24d73ee33094c29d429556296d076e5b3a2ed056f52cf9b28  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/summary.json
7f96ddf4abeb3b6754230ac37d1074b1be30890c00c7e8603c5f08271390fd18  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S1/manifest.json
d05578aea439a43de0fe46bd26dffc8a203e51a941b3c9f689fae9c67812f8e7  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/per_frame.csv.gz
1c67ab5f5b96ee9aeab27cdab6d878886f429a2e6870af62feee90e3cfb05cfb  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/summary.json
ee7b34cfddfeb838037f2b33da8f3d40b1aa91b506dd6ced001abf0d56d57b01  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S1/manifest.json
f29097df99ed4aff640c2c081f5ef525cdc95ea86ed442d97c2e932c3b247ff4  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/per_frame.csv.gz
87f976bdcc9f9fd6baa555f5f6a2b92155e34abd23fc08c77aa7716ba2ed838a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/summary.json
2ddc623744aa610844f412c241fe25563bc5422ccff8a9b69e693369ff0f4482  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S1/manifest.json
b4ecac47248bd8cd0b15fdeb7507f940b89d068e699d728525e75acc11249762  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/per_frame.csv.gz
98bf1a7a4cfec0ec1d274e8bcda1a038e8e49e2835f112781ff490c272a1d417  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/summary.json
70a56da1bfe54c268cb1690c10a5bb489e7e7c73d3a6c73a17a01d33fcac4b84  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A2/manifest.json
61e1462d61da9d422e35f25696f84b71809a926b140826f9d1561d692e0dfc43  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/per_frame.csv.gz
c79c00f9d0c356ad4aa89938b9e249c397405075a050c56514e379e40181e2d1  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/summary.json
0c49782717fc29a83b88a2fa0c8f85cde8f75b881dc925e6f7b246d5ce8b58ec  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S2/manifest.json
c4ca49982a8f0e2ac09c02ea1aadeec4b1936975945003b80f0c068d036ce25b  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/per_frame.csv.gz
f081cd2a75428bd2bde99d0bdeee6ae91babc17ed5d24bc11ec82f183152b36c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/summary.json
a61d7a6e12bf469425f055dc62f97183cc81d785872e527b9594b0c2702e4bab  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S2/manifest.json
c3d560b915d31c0f69f64972956ba343ff4795fb4a205bfcb30ef8156720145a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/per_frame.csv.gz
0481e8b23a19d523b00db0504d458c7d9c48cb38e23dfc1c805244b425a4450a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/summary.json
09231bb5858c789d688fcdf26ffe0f19a4ba39fb8bbe5b827890725ec0e9c6d0  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S2/manifest.json
748001705a33e91913590b54214d6103a695c2acde7c2d3257f5ede7739544b5  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/per_frame.csv.gz
8a04e706aa3700f93b0d84676b50fff153ebb4c5f13cf0f1712fe9bdc2195569  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/summary.json
6a61e228d641a86eaf916cd54416d3d52862b9c4ed660e924d0281ad954a7a58  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A2/manifest.json
ccfec5479883744d4149b47add5195a9f471048e89e1ba6bcfa642edaed155b8  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/per_frame.csv.gz
b20482ec2dad815d05d0838a7c85b8a8c9f0dd302ae35473fb9e50d73edebce5  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/summary.json
41b668d9d009526d756980e81a901a20c42d5231336e561ec8525c7435126f4a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S3/manifest.json
01a65f2ed1f639cc954cd8e5fa2ada6f47070c6318bcf781c8b0057b0db4ee44  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/per_frame.csv.gz
5742bac23caa52b9db8712958dc5471c574eef47d2eb660ec9842e9bcd4bfaa6  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/summary.json
6dd49919eaaa677a73860ceed22bcc17d6db5d94ef6dadaf3fe9de83c406b2ff  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S3/manifest.json
aea02020d1454273e64dba21edc2376c90108313e4659697d79fbd0e4e36e038  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/per_frame.csv.gz
521ac49e390b2785a8d6a3284c1b371324c5d6e308bbdc76c34406d9e75ecfaf  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/summary.json
8a743b9a2dc29621f6db5e25075bea9abe95f2329f872efd033fe1978c497f63  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S3/manifest.json
2d740507c38dcb82c79eb2c64d181b12e01f5dd2b4f824c2ad4d66b9b851384f  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/per_frame.csv.gz
fdb14c5e8488a5e6d178d1e52668259d3885ccc70bad5d6242bee690b9a9f11b  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/summary.json
5a328ca31ddb0c52395320da7ebb9b3fafe11d21341a12ee3c22c58e25c38508  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A3/manifest.json
d41dfb6202d6d3b028640957d9861fcdc4b3695b34741160f76ca8e834e7980c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/per_frame.csv.gz
fcd9a6b10d89c8b44fd8b457fc65ffe7664d7728de574d429d8e045b272c4968  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/summary.json
f765ea387f4add93eef646fb699890cfe100ee2c61ca09460a63376e0f0b1da9  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A3/manifest.json
532f3a64325cd1e480e22bfcedd6b379c354b12e9095c49f2ad4a7d28297adad  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/per_frame.csv.gz
830371f782c2974afafbecfdc19acb3a447caf252b1f80fdc0e6542db3a5ca8f  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/summary.json
fa6a93375bd46feeea3d7069d9d9ac4661d528549f47d78b3306c0873904dbdd  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S4/manifest.json
49f4aa0c485bd58cd82e49214cf49ae7207dad3f8954dcece12b71d9cee295cd  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/per_frame.csv.gz
1210312e013b4848b5435cebc8332b4e1c42b75cb8536e1e4cd101107d7868c2  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/summary.json
ea7389c8897fcb29b138d91eb342f8331dc2273f9fd8be9c3dde7b2dedf77230  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S4/manifest.json
1221f98b443ea215245fedfc051621af0dde82b719e99cc905acc9a18d660e97  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/per_frame.csv.gz
b65c1adbe8de022a16d3e917bce5084390bb567e28cce29da2d1196553f70163  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/summary.json
0f7a1c5bd0e666b97ead7c30c92375a9de83a4252d9f1ac11032674fcfa72a83  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A4/manifest.json
41c019b0108c0621e5efc9cc03cf83ef14c58ea3dcbf3d16dc2cbb247c30b185  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/per_frame.csv.gz
04e85aa665d3602dd67de5d2fae82b837f718564c0a823e32d04f396e88bb4ad  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/summary.json
c4df661dd87a19b084fb054bce3f7b68a3a27f305c631035a03aa167ba2a872c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A4/manifest.json
499e7a14e37d5c499c9416097445ec18803e9250249c14c1653e7975f7b4041a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/per_frame.csv.gz
1fb4667dac8d31415e3d022404cd4bc7eb92abc391b99e0154abb8261ece71be  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/summary.json
bf10d0863d9da5f2610cf394de74a822a328eda1320455953764ec9262396ccc  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S4/manifest.json
bd3d1222d1d03c0e068689a2410a89946f0c159a9817493b57440eeb57cf939e  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/per_frame.csv.gz
fcd3e6bd4feff7e71292fc18ae1c2eb5cca66c0feea214634b5e208ac3d1b393  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/summary.json
987ffa579c97e4f768f8555dc5512f3b1139cf2259b5cd0cd4bc937e6a3c7ac4  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L192_S5/manifest.json
23eae907bf568ad290486f8fc0f61e076a53eed0de1b394152a3b49ab00faa6a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/per_frame.csv.gz
463b1707a5a3bde28965a3a189543216ac4a0d4b9450e444198314aa8a8d7994  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/summary.json
b9a31ae7331939696aa9752af85252c861edc032c39dfe246bfea971b44d9084  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L216_A5/manifest.json
0833e4453636adbbc56a26769cc39e343be77f732b123a903bc25925b6f0310a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/per_frame.csv.gz
07797cc6d0ee46bf379d13366b2b80bcfac5400084acb8931e7e15aa8930de2a  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/summary.json
5700ce725e346cddaea8100711454d7f444549f69d68312068e7407a0aad2d9c  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_A5/manifest.json
ffa1be7c25e0353805ebfb1ea2c36df57f869c403594f8ffd159fc6b7e327895  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/per_frame.csv.gz
5ab6e8dee3882e188cf57a6ae4d6454027832fea58b2e19ad00038f1d7946aed  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/summary.json
9d2194ab41bf3cd90d77b5267f0c8ddd3a81b99b1deb7c219a7a4aaefc106437  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L200_S5/manifest.json
bcd2025ad97918dac255fcf47f0aca1c9c3cd9a21360553f79dbf2e9cfd83168  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/per_frame.csv.gz
b3eeea26b9a9eca20b67db3a227f3af7023e63f1ceb41fb9671eb20590f99fb1  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/summary.json
4527cb74c8bfe3748468b14e0ac5c00f7c30597a9b0ce8beb2a1058d045b156b  results/timely_capacity_campaign/v2_2/block_b_confirmation02/BCONF02_L208_S5/manifest.json
8edbf21e38bcd5044dabb3f87b9e577b67592feb8c060eba238c217d57099f1e  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/analysis01/per_run.csv
3b95f40e32d1b5f5738017c22f982ef571edfcdc3b373485f0d5a940a6b4905f  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/analysis01/per_stream.csv
67e71db0dd26223375c9846bef3d3db3615e015a9f66611628c49404950c296c  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/source_frames.csv
ff92163f29f47f96174691352ea6def89e23e635fe39b338b9d9edb95d58a1cf  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/summary.json
1a9f3708000c96c32482fa02060f53b829b4676862beeb83cba559a1223dd737  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A1/manifest.json
936703f3b9deb2bb33936edc18253a1f56efd6b59e359dbd703cae0570de763a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/source_frames.csv
2c007a75d9b1f10a01bdfbd1121abc8a5b062f9597a9a8b1c979d37d130a6fea  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/summary.json
e6a8b420223205a5d76c53820ea460bb3cd71d8a13c092e55f4901ba1cf946ac  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S1/manifest.json
53f785252e9473c46218c98f71487cbb2eb9034cd32654c7aa95784e7bccea76  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/source_frames.csv
1b6d53a7d969a67f0c21e595760f82b942d965c00c86ae18c8d6279fc0da03ac  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/summary.json
f3f915591cd22b557101e63889987b79af4b2e57926327c8d4d96edccbd06e16  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S2/manifest.json
c9ccaed92e53709dbf49c732113331d9f535d93ae7e1dc798b6e4a2b59379ebe  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/source_frames.csv
ac60b01408edc216c53776612a852e848ed764500b2f7652a220001c5664bc95  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/summary.json
5a5916fa764a93cd57613182f2c7f3e43404dff787c99d0efa79a429c4dc9f48  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A2/manifest.json
03c469f65ca44b0cf8609578f413e94d1802617123082a7621344fd58e06b679  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/source_frames.csv
3680c330db2ebab00ae2d646b88d4e15c1f62cdf76f8bd7db854ee4da8bf35e6  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/summary.json
15bc0d9ba9a0cc957d96f139e8686855b0a09803eae237aa1d4190e22d9486db  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A3/manifest.json
944e7aeeb85fad523203fb572801c3a8477b1db3b366dcc24af6a24368485678  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/source_frames.csv
1f376fcb5eb2d8f463536b264e46e7afd27c96a50606e23c9d1b4d2b6029a8f7  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/summary.json
9babfacc16bb8690f3d15c2da5b90a4b99c6531605a356d56a3c0823411c371a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S3/manifest.json
0ac0041f61e33a61d7da0704b0baad43c839a56dc8322777c768ad193e01c617  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/source_frames.csv
32819a967dc374c2fd455512139cac7213ccdc8b3993655004134ff274ffddae  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/summary.json
f6b2103619796d4357158f561572f03a7b2882fd49fa5b72b747dbf584dcdc0e  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S4/manifest.json
7ab0af428e6502d821f83adb42049f29a4075b330d5443ac7be22bf5e8888f9e  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/source_frames.csv
7b999a96fe733a09c0a0371d81c0a27dcf874d0ac3bab3d10d5427e044e4fe8b  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/summary.json
768733d11858d1c2c2db629a8b3060a5010c5f4c7bea47bb5aa3cf3654beafe5  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A4/manifest.json
36a740d54dabe7a362f703f65b9b88b1fae5439233ca9e6dad36a8ac5ffc0563  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/source_frames.csv
45fb6e3262384b107cf11e26c0e4462e88969ee35c68d16575e3da82fe96201a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/summary.json
e461ae5f38f113073baf10696885df452a1deed316f669ad80925469bc238364  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_A5/manifest.json
d08d96b5ccd92390fd7414f01af1f82feccd7973f027b313c75dceee5b273efb  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/source_frames.csv
5bbac39c93350adc5e0e7c1751bc2fd69e93971ad483aab50f44d07095fc3a38  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/summary.json
3a17e2c7db65fa904a5c39e195774c1d938c9e2f3ba57a81216419f1ed9fd7aa  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E48_S5/manifest.json
5422906745e7959aa8901b74b234aac33788f3e6294485a2228c9e60b4f6ac0b  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/source_frames.csv
ad7160a5462c6c179e1b3788018b9a41bcd9e9c814bd1d09a8f4b9173bddebaf  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/summary.json
0095e8a9d23e2d54b9ed129b9a9cb32778af43a16fc553418dc7fca0f1460bfd  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S1/manifest.json
1ca4205849716e1d597affa58521933222216aab8ed27fa4cb2a08af3c869011  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/source_frames.csv
d57aa3395fca528dab12434544ee49934371e829adb183040ef7ff775e00f229  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/summary.json
ede234927ef234abfca256b7b297071c406719a4625a2e4e716ceff7003f969a  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S2/manifest.json
17cd1f76687d84697ca7bb25529ee78275a06686f27b3b7401156c9e8e7343bc  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/source_frames.csv
4a94a86a1f29b6aa66887466307672f6f712a11e565d689069e18f5ea3ca85da  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/summary.json
2dd7696d6d440d5eb0ca9a399dcf90227f0116c8c796b330595e59644e04217b  results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/sessions/EDGE48C01_E64_S3/manifest.json
7301d9b45a11dac934837227ed754cd6863031b4d162e9c4a9628c0c92b67a26  results/timely_capacity_campaign/v2_2/edge_order_robustness01/analysis01/per_run.csv
8db3c961c813b3dfe1cca348f32d591d898b7b4d988bac55ab3951113ee6e0f5  results/timely_capacity_campaign/v2_2/edge_order_robustness01/analysis01/per_stream.csv
a4e94bdaa8352de5ee52ce2a8c6912198f311a4dfc49af52a4b41eb04bef5477  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/source_frames.csv
c971b94d3de427cd07b54b3b0a7f819599de4a68ecfe63a98d3481656b952c3b  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/summary.json
fb27c24e8c16d10a298c718517546b40e47dafc04f528b6a4c5af7916762a133  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE1/manifest.json
d5c5005a1d263789051c5ce1b653e55ff13b084b872bb8eb31140d95186cef81  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/source_frames.csv
5f7bbebb78bb1e8d0bdfb8ee255f37e0bf25e633387a8386a345ef3120a9743a  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/summary.json
2b7ff406827d0fc547f5da581d391b88064794416b92877b440c269ce8bc6001  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV1/manifest.json
2440a2d6f766ab22929718db10d94d39cb7977ecaac9d541bf82a293348a336a  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/source_frames.csv
07f6a6d3f4020a6c794a54400fafc51cbd45e9357057ee2801fb8b687bbb3f8a  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/summary.json
9f429df18d930c1b34c5316c47e3bd9e2275d986bd9724ae1ca6e89e7991f171  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT1/manifest.json
1ce3754f76b671343e946f2bdd425ea480ef0d4cb4c2a18c2d781017a47b20dd  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/source_frames.csv
52f481d941e8946f3cb0811f6be99a9fee74556ba7be687b14a035ed31b62396  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/summary.json
ffa5df3300a93a9f3dfbcd033b768f1decfa9c1b28ccf0b4f00499753e2b8425  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV2/manifest.json
f8026ee1ae72749b9c3791f4061d32f90a02d9c9188b45cbce548433688621bf  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/source_frames.csv
28e20c28e23ceae4e117d659379c85a601afef94df5d2868d4c6292e3bf82ce2  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/summary.json
927198c0dd1f7fc196d28dde6fad57198b8294321de6605b1457267ce99717af  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT2/manifest.json
7dc28de8e03682c0b84ea182d8135f3875194be220704a2925ffc827967898fc  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/source_frames.csv
b8f9c52075fab1891b46269955683eb85a752de15abf4ef5697e610736ffc5b5  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/summary.json
2b240c8b303d16f5940db1b26d3069308599f941e2caed97fc8746f092118e21  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE2/manifest.json
c278f79d6c0751a8fd6e5b960821ccbf51e713b62e2ca512e1004a61cf436364  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/source_frames.csv
0fc5399084e79cd8d617abdb22faa96b929258eef297b1b97aab9dbd5cbe7d2b  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/summary.json
52312661a9da8afc52a9472b64b823fac7b7be0e9c49d6005ea95aaf8624e4a0  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT3/manifest.json
688e6e856c84ac0f088fe20cabf6ffbf21448ebce98f91c5257c869b7eefced6  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/source_frames.csv
ae33c6443b19830cdea6b3d53fe1fd1c0e1202704f85310e8b25979da07392fe  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/summary.json
0db42ec8014c38cd9fd0bf91ab451b0f0730c009303d53da6731e0e69b0f4ffa  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE3/manifest.json
342159a39ed85eacff74ce7bd7e4acf4dbba217be0c2d0543b39ef7a36d34383  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/source_frames.csv
37b5ac62821ea2d43a1ee60b0d3f68575594d55045ab86d4398c755f894ffb42  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/summary.json
c597592464421a1a8d6223abf50eafff054eda8246f48eb88d9a59d904d7c04c  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV3/manifest.json
16da05a6f4c7b1ca1423a540e0da3994d86ccf3c6854c83c4cd5d27416c250d9  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/source_frames.csv
b7290e13cfd50e775efedff3489142ef673c440d805144316c1966893d250649  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/summary.json
9fee7769652905bde8358e0711ec93491a71c10a3d89088e37a2bc490632a976  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE4/manifest.json
43c474988cbfa8b696e0ff4e32f7aa80929a6fef6810c26c4b27a42c2d2e3d1e  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/source_frames.csv
bbda3eebe0477360e4571da19dd27126ca7787e12a780066756d68b9963cd2ce  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/summary.json
623aa2f2b95817a35c2f1734e8defa76e63320d796c1cc00e4001a52a40a1ebb  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT4/manifest.json
57738ebf0a9723aa4573eef14db6ebbc7f40d8211cf6988bc2a1929c43f56580  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/source_frames.csv
fe4b319af9818f79fe83d2258f52930bbe5c4130c7b2d548f412ea7d05586e7a  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/summary.json
9fcab1678393ae01ebf2c2783c730f5c70ce51520176174af689e1524b11f343  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV4/manifest.json
a12dd020f5dde14ae247cdbf021c548c1f4462e49d5b121c59aaf8888e065454  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/source_frames.csv
224ca037929c08249e988ca3e1fb2bc59c9d3ce3dc492eb9844fd901eecb43eb  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/summary.json
77716fa16b9e217b44cedbb986d6c42b71b605495da4f9cc92543d0895b6925f  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_ROT5/manifest.json
61ce0b7b0f64ce146c80ded11190e11f71dc163d6aa94d5cdee20c995d7564cf  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/source_frames.csv
0b9ad11dee471672093031450075b48f9cc478264f5743bb449724a5f6947085  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/summary.json
d3fb83ec990644601ad9db9562760b1c37712f40750fd37486aa8a054e9d9a08  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_REV5/manifest.json
4459b6b767fd9a1dd9a2f65476b3c6fedbf38375bd9c8b773a589dc075a028f5  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/source_frames.csv
e806adb8eb0cd3674502014c844f1739f705b0e52e51a0017a89c0056c7c92ac  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/summary.json
5f7b3e3e8726e9532017fb2683c803e846e02b05fb5bca89eda7f80365483289  results/timely_capacity_campaign/v2_2/edge_order_robustness01/sessions/EDGEORDER01_E48_BASE5/manifest.json
```
