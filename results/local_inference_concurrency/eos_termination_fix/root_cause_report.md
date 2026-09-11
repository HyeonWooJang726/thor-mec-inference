# EOS termination failure forensics

Classification: **UNKNOWN**. No production EOS fix applied; post-fix targeted gate and v2 screening are blocked.

## Contract established before any corrective change

Original videos contain 1800 frames / 60 seconds. The old bounded screening calls `build_pipeline(video,900)`, leaves decode/conversion/appsink settings intact, and inserts `identity eos-after=901` before appsink. Each front-end loop pulls exactly 900 samples. Success requires both total completions and `all(eos)`, with `eos[i]` assigned only in the GStreamer bus EOS callback. This is **BOUNDED EOS**, not natural full-file EOF and not application frame completion. The requirement cannot be removed simply because only half the file is used.

## Original failed run: C2-K7-run01

All seven streams have arrivals=source samples=preprocessed=completions=900 and last frame_id=899. The aggregate 6300 rows have exact IDs, ordered integer timestamps and exact decomposition. Waiting and active inference both drain to zero. Camera_0004 last c is 30.089015366 seconds after t0; the last c across all streams is 30.093500786 seconds. The original process exits 1 after 183.342537173 seconds due to the unchanged 180-second watchdog and missing stream-4 EOS flag.

Camera_0004 bus EOS callback flag is false; the other six are true. This proves non-observation by the application, not whether the EOS event was generated, where it stopped, or whether a queued bus message was missed. stderr is empty. No CUDA/TensorRT or pipeline cleanup error was recorded.

The original code constructs pipelines, registers bus watches before PLAYING, starts front-end and inference threads, then schedules phase-aligned arrivals. Front-end processing returns after 900 iterations. EOS callback flag changes use the state_lock; the callback calls maybe_finish after releasing that lock. Inference completion schedules maybe_finish on GLib. No competing bus pop consumer exists in this runner. Main-loop finish checks frame completion plus every EOS flag. Cleanup requests NULL on all pipelines, joins started threads, then closes TensorRT resources.

The old artifacts do not record source sample PTS, per-thread return/join times, state at watchdog, EOS pad events, EOS generation/acknowledgement or final get_state. Therefore these cannot be reconstructed as observed facts. All Python join calls must have returned before validation was written, so source workers were terminated by process exit; whether each was already terminated at watchdog is unrecorded. NULL was requested without a reported failure, but actual completed final state was not queried. Per-stream a/b/r/s/c evidence is saved in `failed_run_forensics.json`.

## Confirmed mechanism distinction, not a proven historical root cause

Installed coreelements is GStreamer 1.24.2. A local CPU pad-push test returned `ok,ok,ok,eos` at the identity limit. It produced no bus EOS until a real downstream EOS event was explicitly pushed, after which event acknowledgement and bus EOS were both observed. This demonstrates that a flow return is not itself an EOS event. `identity_flow_vs_event_test.json` preserves this result.

The upstream 1.24 identity implementation returns GST_FLOW_EOS from its eos-after branch; it does not directly issue a downstream EOS event there. Reference: [GStreamer identity source](https://raw.githubusercontent.com/GStreamer/gstreamer/1.24/subprojects/gstreamer/plugins/elements/gstidentity.c). The local installed-binary test, rather than assuming branch/version identity, establishes the behavior on this host.

This is a plausible failure mechanism: upstream flow-return handling may not have resulted in a downstream event. However the old run has no pad/sink/bus tracing, so that mechanism cannot be declared the exact cause. Appsink-side EOS waiting, message delivery and lifecycle races remain alternatives requiring a reproduced failure trace. No NVIDIA driver defect is asserted.

## Read-only evidence and isolated diagnostic reproduction

The original campaign is untouched. An isolated diagnostic copy adds EVENT_DOWNSTREAM-only probes, EOS callback records and post-completion state/thread snapshots. It leaves arrival, frame-processing, inference and pipeline-construction functions AST-identical and leaves TensorRT byte-identical. All diagnostic data are excluded from C selection and from the requested post-fix targeted gate.

Two standalone C2-K7/900-frame diagnostics completed normally. A further diagnostic sequence recreated the immediate historical predecessor C7-K6 followed by C2-K7; both completed normally. Thus three C2-K7 diagnostics and one C7-K6 diagnostic passed, but no missing-EOS failure was reproduced.

In each observed normal trace, EOS reaches bounded-source:sink, bounded-source:src and appsink:sink, then the pipeline bus callback. Post-drain snapshots show 900 identity buffers, 900 samples/completions per stream, source threads no longer alive, appsink EOS true, sticky EOS present and pipeline state PLAYING before cleanup. These normal-run observations cannot be backfilled into the original failed run.

## Decision

Root cause remains UNKNOWN, as distinct from the confirmed contract and flow/event distinction. Per the explicit gate, no speculative operational fix, no post-fix targeted validation and no v2 performance campaign is launched. EOS remains mandatory; completed frames are never converted to an EOS flag and the watchdog is not increased. The next required evidence is a missing-EOS reproduction with limiter/sink sticky events, bus callback and worker/state snapshots. Only then can a termination-only corrective change be justified and tested.
