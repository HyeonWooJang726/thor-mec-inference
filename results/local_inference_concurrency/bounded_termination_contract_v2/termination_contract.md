# Bounded termination contract v2

Original C2-K7-run01 Camera_0004 missing bus EOS direct root cause remains **UNKNOWN**. This is a contract separation authorized by the user, not a demonstrated repair of the historical EOS delivery mechanism. Historical facts remain: each stream acquired and completed 900 frames, Camera_0004 final ID 899, all 6300 frames and timing/decomposition/queue checks passed, waiting/active zero, source joins returned; Camera_0004 EOS callback absent and watchdog fired. The original artifacts remain unchanged.

## Bounded 30-second / 900-frame mode

`eos[i]` means an actual GStreamer bus EOS message was handled by `on_message`. Only that handler assigns it. Already queued EOS/ERROR messages are handled during cleanup as genuine messages; there is no synthetic EOS, waiting for missing EOS, or timeout-to-EOS conversion.

The acquisition loop is unchanged. After its normal return, `source_loop_normal[i]` is recorded. When all these returns and accepted-frame completions are present, the main loop can end independently of EOS. This is permission to enter cleanup, **not yet run PASS**.

After cleanup, `bounded_complete[i]` requires exact source sample count and frame IDs, normal acquisition loop return, no source exception/GStreamer ERROR, successful source worker join, successful NULL request and actual pipeline NULL state confirmation. Global PASS additionally requires exact arrivals/samples/preprocessed/completed/CSV counts, exact IDs, integer timestamp ordering and decomposition, zero waiting/active after drain, no negative queue depth, all source/inference/scheduler joins, no runtime/cleanup error and no watchdog. Disk-artifact replay independently rechecks these and the unchanged frame/queue/concurrency validators.

A missing bus EOS remains `eos_observed=false` with explicit stream IDs in run metadata. It does not invalidate an otherwise complete bounded run. `bounded_complete` never writes `eos`.

## Full-source mode

Existing 60-second/1800-frame full-source runners are untouched and retain their actual EOS requirement. The pure validation contract also explicitly fails `full_source` without EOS; its regression checks this. The new executable accepts only 900-frame bounded stress/screening, so it cannot accidentally apply the relaxed observation requirement to full-source formal. A future K1..7 formal runner must keep the full-source EOS requirement and perform its own preflight; none is run here.

## Frozen performance path

Identity `eos-after=frames+1` remains 901, with unchanged topology/properties. Pipeline construction, arrival scheduler, inference worker and statistics are AST-identical; the entire front-end acquisition loop is AST-identical; TensorRT implementation and resource validation files are byte-identical. Existing preprocessing/queue/timing dependencies remain untouched and hash-pinned. Changes are post-budget termination bookkeeping, bus/cleanup observation, validation, and isolated campaign orchestration. Added lifecycle work is per-source completion or after drain, not per-frame profiling. This proves unchanged performance-path code/semantics, not identical wall-clock results under unlocked DVFS.

The original v2 root contained eight NOT_RUN/BLOCKED reports. They are protected unchanged. Fresh screening output is `application_c247_screening_v2/bounded_contract_campaign/`. Stress output is separate under this design root and never included in C-selection statistics.
