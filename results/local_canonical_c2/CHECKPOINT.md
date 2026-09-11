# Canonical C2 Local checkpoint

This checkpoint preserves the validated fixed static Local baseline: B=1, C=2, K=1–7, five full-source 60-second/1800-frame runs per K, 35 runs and 252000 frames. C2 is a fixed baseline choice, not a claim of universally best concurrency. No workload was rerun for this figure/checkpoint revision.

The canonical measured entry point is `code/run_fullsource.py`, with `code/profile_fullsource.py` and the local `screening_*`/termination modules. Despite their historical filenames, these are the exact canonical runtime dependencies. `source_snapshot/` and `source_sha256.json` record the shared scripts used during measurement. The top-level `scripts/*concurrency*.py` files preserve the earlier validated C1/C2 control and TensorRT probe workflow. No script was moved or reorganized.

Primary artifacts are `formal_plan.json`, `formal_integrity_report.json`, the root summary CSVs, `analysis_report.md`, and `analysis/`. Five separate run statistics are retained; no historical campaign is pooled. The full-source runtime continues to require genuine natural EOS, clean joins/NULL shutdown and complete drain. Bounded completion cannot replace natural EOS.

## Figure reproduction from compact committed artifacts

On the recorded Python/NumPy/Matplotlib environment, run from the repository root:

```sh
/usr/bin/python3 -B results/local_canonical_c2/analysis/plot_figures.py --replace-generated --from-derived
```

This explicit plotting-only mode checks SHA256 pins in `analysis/plot_inputs_sha256.json` and the recorded 35-run/252000-frame formal PASS. It does not claim to revalidate raw files that are absent from Git. Its PNG output was verified byte-identical to the default full-raw-gated rendering on the measured host.

The default plot mode still verifies every raw hash before rendering. The cosmetic revision removes individual scatter points and fixed-C title text, moves latency legends below the axes, and pins the original numeric axis limits. Means, SD, bars, lines, reference deadline, scales, K5/K6 selection and C2-safe Figure 4 metrics remain unchanged. Individual run values remain in the tables. PNG only; no PDF.

## Full validation with external local artifacts restored

```sh
/usr/bin/python3 -B results/local_canonical_c2/verify_checkpoint.py --output /tmp/canonical_checkpoint_verification.json
```

The output path must be new. This CPU-only verifier runs Local/concurrency/termination tests, imports the runtime without executing inference, checks syntax, and replays all 35 raw runs against the committed summaries. It needs the externally retained engine and raw artifact tree. The measured engine SHA256, video paths and source/measurement hashes are recorded in the runtime document, formal plan and integrity report. Video, engine, correctness input binaries, per-frame CSV/JSON dumps, full stdout/stderr, environment process dumps and orchestration logs are intentionally excluded from Git.

`analysis/analyze.py`, `temporal.py` and `verify_analysis.py` retain full-analysis provenance. Detailed `temporal_periods.csv` (27000 rows) is a local derived intermediate excluded from the compact checkpoint; it can be regenerated from external raw artifacts. Full regeneration scripts deliberately refuse overwriting primary results. The independent analysis verification report records 252000 statistical samples and 27000 temporal rows checked.

Historical selection evidence is kept separately under `results/local_inference_concurrency/`: identical-path C1/C2 control; C1–7 trtexec micro-probe; the completed `application_c247_screening_v2/bounded_contract_campaign/`; C2/C4 full-source validation; C3/C5/C6 sanity screening; bounded/full-source termination documentation. The incomplete original screening and its raw evidence remain local and untouched. Its missing bus-EOS root cause remains UNKNOWN. Earlier UNDECIDED/micro-probe recommendations are historical stages; the final user-selected C2 configuration is documented in `canonical_runtime_configuration.md`.

The current result supports a K5→K6 deadline transition and stronger K6→K7 queue/tail degradation in this startup-inclusive workload. It does not establish physical GPU kernel overlap or sustained steady-state throughput collapse. Dynamic C, graph partition, script directory refactoring and push are outside this checkpoint.
