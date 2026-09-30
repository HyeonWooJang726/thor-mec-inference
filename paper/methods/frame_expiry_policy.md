# Frame-expiry policy used by Grid03-mini

This document records the existing measured implementation, without changing
its runtime, results, plans, or preregistration. Grid03-mini used C_L=3, C_E=1,
B=1, K=8, F=30 FPS per stream, D=100 ms, and deadline-based pruning enabled.
Configuration A and final Configuration B retain their separate scientific
status. No workload, TensorRT load, server, or network probe was run for this
documentation.

## Source time and deadline

For active frame i=(k,n), a_i is `logical_arrival_ns`, the scheduled source
time, not video PTS, queue insertion, or a host wake-up observation. The source
writer in the frozen generated `run_one.arrivals` sets
`target=active_start_ns+frame_id*10**9//30` and assigns that same target to
`logical_arrival_ns` and `admission_timestamp_ns` for each stream. It separately
records `admission_observed_ns` from the host monotonic clock. See
`results/timely_capacity_campaign/v2_2/validation01/effective_runtime.txt`,
lines 266–282.

The mini-grid's actual `grid_config.decorate` checks this source time and sets
`absolute_deadline_ns=due+100_000_000` (lines 68–78). Thus d_i=a_i+D. All active
source frames are admitted and assigned to one path. Assignment phase shifts
alter the destination mask, not a_i. Common replay phase does not establish
synchronized physical camera capture.

## Verified checkpoints

| Path | Checkpoint actually used | Predicate and outcome | What the timestamp represents |
| --- | --- | --- | --- |
| Local | After `ready_queue.get`, under the accounting lock, before `worker.infer` | `stamp >= job['absolute_deadline_ns']` produces `EXPIRED_DROP` with stage `LOCAL_BEFORE_TRT`; otherwise execution proceeds | Host monotonic time sampled by `PruningAccounting.begin`, not GPU kernel start |
| Edge | Thor sender, after taking the ordered pending request and waiting for its release target, immediately before the socket REQUEST submission path | `stamp >= row['absolute_deadline_ns']` produces `EXPIRED_DROP` with stage `EDGE_BEFORE_SUBMISSION`; otherwise the request is sent | Host monotonic time at the pre-submission check, not wire arrival or server/GPU start |

Local evidence: generated `run_one.infer`, lines 175–205, calls
`accounting.begin(job,time.monotonic_ns)` after queue acquisition. The predicate
and host start assignment are in `PruningAccounting.begin`,
`scripts/expired_work_pruning/pruning_common.py`, lines 69–78. The expired branch
deletes the prepared tensor, records the terminal outcome, and continues without
calling TRT (generated lines 186–203). `expire`, lines 44–49 of pruning_common,
rejects early pruning and rejects rows already started, submitted, or completed.

Edge evidence: `pruning_common.EdgeLink.sender` is built from the inherited
sender using the source replacement at lines 108–117. It inserts the exact
`>=` predicate before `p.send_message(..., p.REQUEST, ...)` in
`scripts/hybrid_capacity_extension/edge_link.py`, `EdgeLink.sender`, lines
78–93 (submission anchor at 88–89). Expired request IDs are recorded separately
and never submitted. The END/FINAL ledger distinguishes assigned, submitted,
and client-expired IDs; it does not claim server-side removal of those IDs.

Both checks are **expired-only**, with no service-time forecast, safety margin,
or test of whether the remaining budget can accommodate estimated inference.
A request that passes a check can subsequently miss its deadline. In particular,
t_check is distinct from actual GPU start and, for Edge, from completion of
socket transmission. No equality between those times is assumed.

## Actual runtime binding and generated implementation

The following source path establishes that the checkpoints above belong to the
mini-grid execution, rather than merely to an unused predecessor:

- Mini `run_thor.Context.bindings`, lines 144–168, binds the frozen V2.2 worker
  with mini `decorate` and the mini summary/finalizer validation.
- `common/v2_2/run_validation.Context.bindings`, lines 35–38, supplies
  `v22_builder.run_source`. Its lines 51–77 preserve the execution body while
  binding `v22_accounting.make_accounting` and preallocated storage.
- `common/service_phase_b1/run_b1.Context.bindings`, lines 22–29, clones the
  V2 binding. `block_b_split/v2/run_v2.Context.bindings`, lines 28–38, supplies
  `EdgeLink=self.edge_link`.
- `common/run_campaign.Context.edge_link`, lines 65–71, derives the actual
  active link from `pruning.EdgeLink`, changing only its HELLO binding.
- `v22_accounting.method_source` and `make_accounting`, lines 11–35, remove
  detailed event-list appends while preserving the ON predicate. Only the OFF
  branch replaces the predicate with `False`; mini `supervisor_source`,
  `run_thor.py` lines 114–124, explicitly sets `pruning_enabled=True`.
- `common/service_phase_v1/build_adapter.runtime_source`, lines 16–35, and
  `run_source`, lines 38–81, add phase/CUDA-event records around the same
  inference and expiry paths. They do not add a prediction-based drop rule.

The measured Thor manifest
`results/timely_capacity_campaign/v2_2/grid03_mini01/GRID03M_L224_DISP_R1/manifest.json`
records `execution_runtime.version=V2.2_CONTROLLED`, the mini plan SHA, and the
generated worker SHA shown below. The current inspected sources match their
recorded hashes in the mini plan/source manifest or that measured manifest's
`execution_runtime.source_sha256`. The saved generated worker also matches the
recorded `worker_source_sha256`. No discrepancy in expiry semantics was found
between the inherited code and the actual bound implementation.

## No deadline-driven cancellation after start or submission

After the Local check passes, `ContextWorker.infer` performs H2D,
`execute_async_v3`, D2H, and stream synchronization; it has no deadline argument
or deadline-driven cancellation path
(`scripts/concurrency/local_concurrency_tensorrt.py`, lines 116–132). The generated
worker records `c_ns` after inference returns and marks the row `COMPLETED`
(lines 204–209). It does not turn a late completion into an expired drop.

The Thor Edge receiver likewise preserves late responses: it records the Thor
monotonic response-observation time in `response_completion_ns` and `c_ns`
(`edge_link.EdgeLink.receiver`, lines 95–123, especially 100–121), and the pruning
adapter adds `terminal_state='COMPLETED'` (pruning_common lines 118–126).
There is no post-submission deadline cancellation or late-response discard.
Fault handling and shutdown remain separate from expiry policy.

The actual server bundle is the unchanged Grid02 bundle at
`results/timely_capacity_campaign/v2_2/block_b_grid02/edge_bundle/`.
`edge_server_grid02.main`, lines 47–61, calls
`pruning_edge_server.serve_session` with `formal_server.Backend`.
`pruning_edge_server.adapted_session_source`, lines 24–36, changes only END
accounting, using `partition_end` (14–21) to validate the Thor-expired IDs.
It does **not** add an Edge queue expiry check.

In bundled `formal_server.serve_session`, the queue is unbounded FIFO
(lines 63–77); received requests are enqueued (148–168), processed without a
deadline check (worker 101–127; `Backend.process` 36–45), and naturally drained
(171–191). No server-queue deadline removal, execution cancellation, or
deadline-based response discard exists in this path. The received measured
manifest at
`results/timely_capacity_campaign/v2_2/grid03_mini01/received_edge/GRID03M_L224_DISP_R1/manifest.json`
records `queue_policy='unbounded FIFO; no cap/drop'` and matching formal server
source provenance. The three bundle files listed below match the mini
`runtime_manifest.json` hashes; the pruning and entry-point copies also match
their Thor source counterparts byte for byte.

## Completion, TIR, and terminal accounting

For Local, c_i is the host `completion_timestamp_ns` saved from `c_ns` after
inference/stream synchronization returns; for Edge it is the Thor response
observation, not a server-clock timestamp. The inherited `save_records` maps
`c_ns` to that field (`scripts/rate_dvfs_gate/run_rate_dvfs_gate.py`, lines
301–310). The mini analyzer clones Grid02 `per_run` with mini paths/validation
(`scripts/timely_capacity_campaign/grid03_mini01/analyze.py`, lines 12–22).
The exact inherited timely formula is:

```python
completion_timestamp_ns - logical_arrival_ns <= 100_000_000
```

See `block_b_grid02/analyze.py`, `timely`, lines 51–54. Completion exactly at
d_i is timely (`<=`), whereas a not-yet-started/submitted request checked
exactly at d_i is expired (`>=`). These are different outcomes at different
checkpoints.

The denominator contains **all generated active source frames**: 14,400 per
60-second measured run, and 1,800 per stream. It is not restricted to survivors,
TRT starts, successful Edge submissions, or completions. In this campaign
every active generated frame is admitted, so the analyzer's `admitted` count
equals the full active source cohort. Warm-up is excluded. Overall and
per-stream TIR count only timely completions in the numerator; late completions
and expired drops remain in the denominator. Path-assigned TIR uses all frames
assigned to that path. The numerator is evaluated for the active source cohort
after drain; a late drained completion is retained as late.

Grid02 `per_run`, lines 137–168 and 181–218, requires the complete active cohort
and the exclusive partition
`timely + late + expired == generated`. Mini `validate_rows`, lines 100–116,
rejects a completed/drop overlap, unfinished row, missing source identity, and
incorrect split count. Valid runs therefore close as `TIMELY_COMPLETED`,
`LATE_COMPLETED`, or `EXPIRED_DROP` (the first two are classified from the
stored `COMPLETED` state). Unfinished/failed records remain integrity failures;
they are not silently removed from the denominator or relabeled as successful
outcomes. Existing invalid attempts and their records remain preserved.

The plotting checks retain all 24 measured VALID runs and verify the saved
per-stream/per-path partition and ratios. This documentation does not rerun
inference, reclassify historical runs, or introduce a new scientific threshold.

## Cost and observation limits

Expiry removal avoids the subsequent Local inference or Edge submission at the
verified checkpoint. It does not erase costs already incurred: the frozen
`run_one.front` waits for decoded samples and resizes both paths; Local also
performs remaining preprocessing before queue insertion (generated lines
239–263). Those costs have already occurred when the worker checks expiry.
Edge preprocessing after server receipt is not avoided by a Thor check that
has already passed.

All eight requested policy questions are resolved by the inspected code and
provenance. The exact delay from t_check to a GPU kernel's actual start is not
established by this code-only policy audit. Local `s_ns` is a host execution-path
timestamp; `admission_observed_ns` is not an exact queue insertion timestamp.
No physical capture synchronization, simultaneous queue insertion, GPU idle,
or causal performance mechanism is inferred here.

## SHA-256 references

Paths are canonical repository-relative paths. Hashes identify the bytes read,
not new copies or modified runtime assets. Full hashes are generated directly
from those files.

| Path | SHA-256 |
| --- | --- |
| `scripts/timely_capacity_campaign/grid03_mini01/grid_config.py` | `f0dfb3aff83346a053a397c7a6822b7c9307387e8269a1ee5c213bbe6e7bdeda` |
| `scripts/timely_capacity_campaign/grid03_mini01/run_thor.py` | `98042e0a4209eea1f3ba1bbbff0fbd9f260e98a0a11a697f8b1d9beb33d3f545` |
| `scripts/timely_capacity_campaign/grid03_mini01/analyze.py` | `03765e185c9c442b4b7f08b6dda6ee8927c39b81430cc06247e65942f7d57237` |
| `scripts/timely_capacity_campaign/grid03_mini01/validate.py` | `831770a1691e94bbe4638a806eaf569692997b95d38772edfc29cfbc70bfbfa2` |
| `scripts/timely_capacity_campaign/common/v2_2/run_validation.py` | `78e0a10a0f02f24eb586cb9f3cdae58cc7da6c2d7019518a64affb2dae8a83a5` |
| `scripts/timely_capacity_campaign/common/v2_2/v22_builder.py` | `7a8ef602df2f957366e2d41cdb358a60ae0d7fee5e599a6d5273b302c6fe580c` |
| `scripts/timely_capacity_campaign/common/v2_2/v22_accounting.py` | `2c60b61ef8ae9f573c43728a1d48094254baa77daca088092fa359a0d0d2226f` |
| `scripts/timely_capacity_campaign/common/service_phase_b1/run_b1.py` | `6b31469a371d0e0b400546f4541c8c5ca888094e73f7adebff7de1831b30945e` |
| `scripts/timely_capacity_campaign/common/service_phase_v1/build_adapter.py` | `2fc3bb7bb9c094c9abde1897896c743634ff845a736b982a23aaab5565cd542a` |
| `scripts/timely_capacity_campaign/block_b_split/v2/run_v2.py` | `003ed5d741d9ffde9862282c38b13360b9a029a39caf200a77a16e5daaa681fc` |
| `scripts/timely_capacity_campaign/common/run_campaign.py` | `1b7c5b58f6973a2e5a2b7a5d734f654b39793263a309b237e59048e8d1dcfeaf` |
| `scripts/expired_work_pruning/pruning_common.py` | `b31ad8a84623f2c11c7dc0eeaddcc9449d67efdc84a5d6666ca8199f23784d29` |
| `scripts/expired_work_pruning/edge_server.py` | `8f1c133ba2f901f79efc10aa5b5ba48805946958794db5681eafd9521d2a68db` |
| `scripts/hybrid_capacity_extension/edge_link.py` | `d300ad5586d6425a3e1568fac2b5e3d7f6e9c2f6c01644b9a79eb306d27f626d` |
| `scripts/concurrency/local_concurrency_tensorrt.py` | `863cdd468d8565efdf2a82435e667f9fce837d7d2013ff61ab4ab8fafa8ba140` |
| `scripts/rate_dvfs_gate/run_rate_dvfs_gate.py` | `290db909f9570b321c4d4340f10b17fe31c4239cf5e475a426d2e92ec6a3ac7c` |
| `scripts/timely_capacity_campaign/block_b_grid02/analyze.py` | `ed173139a25e72b0846359a7607dc43e1b262bf81d2d806012f00ffff18bfebb` |
| `scripts/timely_capacity_campaign/block_b_grid02/edge_server_grid02.py` | `7e57a9471ff3f12e4676a8a5af225ed9a32a1fd7a98ecc3997169588de5c3b0d` |
| `results/timely_capacity_campaign/v2_2/validation01/effective_runtime.txt` | `6bf2c6dcce91b0d986480e7e82104dbc6310e6516482134062c8c9a1a04a7b6b` |
| `results/timely_capacity_campaign/v2_2/block_b_grid02/edge_bundle/edge_server_grid02.py` | `7e57a9471ff3f12e4676a8a5af225ed9a32a1fd7a98ecc3997169588de5c3b0d` |
| `results/timely_capacity_campaign/v2_2/block_b_grid02/edge_bundle/pruning_edge_server.py` | `8f1c133ba2f901f79efc10aa5b5ba48805946958794db5681eafd9521d2a68db` |
| `results/timely_capacity_campaign/v2_2/block_b_grid02/edge_bundle/formal_server.py` | `e4d2218fca52b4c79cc9c768d9cbeee241645b8d7d2756c14d502ba91a28201d` |
| `results/timely_capacity_campaign/v2_2/grid03_mini01/plan.json` | `3dedb14b3cabad2564965460d159506537df83aed65020ee5d8461e03f601e29` |
| `results/timely_capacity_campaign/v2_2/grid03_mini01/source_sha256.json` | `425a87fc5d1f05d9e249b4db367521fb0f1e969801722bc3edc88b1b6ab51d68` |
| `results/timely_capacity_campaign/v2_2/grid03_mini01/runtime_manifest.json` | `8ee015884dfff18f7bf8a7d8cc1fa6a73e410990c946a9037cb6c3f802d3cf7e` |
| `results/timely_capacity_campaign/v2_2/grid03_mini01/GRID03M_L224_DISP_R1/manifest.json` | `258a41c9131cd3acfcd57c945b2b78299cccad1c26fe4e1f836c34ef95aa1fe3` |
| `results/timely_capacity_campaign/v2_2/grid03_mini01/received_edge/GRID03M_L224_DISP_R1/manifest.json` | `2c2314b3fad2169e959be2d3cb56296456fb79a596f8d5c001f641a0c9325d8b` |
