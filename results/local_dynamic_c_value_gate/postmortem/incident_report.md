# Fail-stop incident: smoke postprocessing

## Facts

Campaign HALTED after smoke_fixed_c4. The real GPU child exit code was 0 and all 780 planned requests completed. The adapter produced 120 source samples per base stream and 60 for the seventh stream. All source sample IDs, exact timestamps/decomposition, FIFO and cap reservations, counters, drain, worker joins and pipeline NULL passed the separate CPU forensic check. Actual EOS was false on all seven sources, correctly consistent with the explicit bounded trace termination contract. No CUDA/TensorRT/GStreamer/worker error or watchdog was recorded.

## Implementation error and ownership

The newly written analyzer constructed `dict(**row, ..., expected_frames=len(plan.jobs), ...)`, but `row` already contained `expected_frames`. Python raised `TypeError: dict() got multiple values for keyword argument 'expected_frames'` after checking the raw records and event accounting. This is an agent implementation error in postprocessing, not evidence of GPU runtime instability or a Dynamic-C performance result. The pre-GPU CPU tests covered admission/trace state but did not exercise this wrapper metadata-to-summary path; that validation coverage was insufficient.

The frozen implementation, failed acquisition, exit/status and manifest are preserved. No correction was inserted into the running plan, no acquisition was retried, and the first row remains FAIL. The forensic audit does not promote it to campaign PASS and does not authorize resume.

## Accounting and research conclusions

GPU attempted=1: FIXED_C4 4-second smoke, completed=780, actual child exit=0. Campaign smoke PASS=0, FAIL=1, UNATTEMPTED=1. Primary attempted=0, completed frames=0, UNATTEMPTED=30. Automatic retries=0. No lookup GPU smoke or dynamic primary was executed. Therefore Δ2/Δ4, repeat consistency and transition-window policy differences are N/A. Verdict=INCONCLUSIVE_VALIDITY. No inference about Dynamic-C advantage or disadvantage is supported. Do not use this smoke as primary performance evidence.

## Minimal next engineering work (not executed)

Fix duplicate summary metadata in a separately reviewed version and add a CPU fixture that traverses command metadata, raw/event validation and final summary/report construction. Any proposal to resume or use existing smoke evidence must explicitly preserve this historical FAIL and frozen-plan distinction; this task performed no new GPU run after HALT.

## Figure organization

28 original figure/caption files were moved from `analysis_valid5/figures/original_static_formal/` to `analysis_valid5/figures/supporting_static/`, with filenames, sizes and SHA256 unchanged. The approved path was adapted to the actual initial location rather than assuming files remained directly under figures/. No duplicate copy or overwrite occurred. `figures/README.md` supplies the current locations. Historical reports/captions and frozen reproduction scripts were not rewritten; render.py still targets figures/. Existing representative artifacts remain intact.

## Preservation scope

All frozen Formal source/engine pins and currently pinned input videos were re-hashed and matched after HALT. Relocated files were checked before/after. Tracked representative artifacts were compared byte-for-byte with HEAD. No raw Formal campaign/status/replacement files were written; no system power, clocks, package, service, network or runtime configuration was changed. Unrelated scripts remain outside this task and staging.
