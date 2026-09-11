# Experiment script layout

The canonical C2 checkpoint is `5a9ff673309bff280bbc94df5d19bb06d688adca`.
This layout change moves 27 of the 28 previously tracked scripts. It changes
module/source/invocation paths, not experimental definitions or measurements.

## Layout and roles

```text
scripts/
├── initial_profiling/
│   ├── check_env.sh
│   ├── profile_decode.py
│   ├── profile_decode_preprocess.py
│   ├── profile_preprocess.py
│   ├── run_decode_preprocess_profiling.sh
│   ├── run_preprocess_profiling.sh
│   ├── summarize_decode.py
│   ├── summarize_profiling.py
├── local/
│   ├── local_latency_breakdown_metrics.py
│   ├── profile_local_e2e.py
│   ├── profile_local_latency_breakdown.py
│   ├── profile_local_realtime.py
│   ├── run_local_latency_breakdown_formal.py
│   ├── test_local_latency_breakdown.py
│   ├── test_local_latency_breakdown_formal.py
├── concurrency/
│   ├── analyze_local_concurrency_formal_control.py
│   ├── canonical.py
│   ├── local_concurrency_control_metrics.py
│   ├── local_concurrency_tensorrt.py
│   ├── local_concurrency_validation.py
│   ├── profile_local_concurrency_control.py
│   ├── reproduce_canonical.py
│   ├── run_local_concurrency_control.py
│   ├── run_local_concurrency_formal_control.py
│   ├── run_local_concurrency_trtexec_probe.py
│   ├── test_local_concurrency_formal_control.py
│   ├── test_local_concurrency_validation.py
│   ├── verify_canonical.py
├── common/
│   ├── rtdetr_preprocess.py
│   ├── script_paths.py
├── network/
│   ├── README.md
├── edge/
│   ├── smoke_tensor_e2e_client.py
├── profile_local_e2e.py  # import compatibility shim
├── profile_tcp_throughput.py  # intentionally unmoved, modified
└── profile_edge_realtime.py  # intentionally unmoved, untracked
```

| Directory | Role and audited use |
|---|---|
| `initial_profiling` | Initial environment collection, hardware decode, preprocessing and their profiling summaries/runners. |
| `local` | Historical serialized Local E2E/realtime/latency-breakdown implementation, formal orchestration and CPU validation. |
| `concurrency` | Independent TensorRT context/stream runtime, C experiments, formal-control metrics/tests, and canonical replay entrypoints. |
| `common` | `rtdetr_preprocess` is shared by initial profiling and Local; `script_paths` resolves cross-directory imports and source hashing. |
| `network` | Reserved for future network profiling; no network experiment is launched by this refactor. |
| `edge` | The existing tensor HTTP inference smoke client belongs here because it posts a tensor and validates server outputs. |

The modified `profile_tcp_throughput.py` and untracked
`profile_edge_realtime.py` are intentionally not moved, edited or staged.
The root `profile_local_e2e.py` is only an import/CLI compatibility shim for the
unmoved edge script; its implementation lives in `local/`. There is no second
inference implementation in the shim.

## Import and invocation paths

Moved scripts still run directly from the repository root. Scripts that import
across roles bootstrap `common/script_paths.py` before importing experiment
modules. This keeps the existing module names, including the frozen canonical
snapshot's imports, without introducing a packaging/install requirement.
`script_path(name)` requires one matching file and is used for source-hash
metadata. Repository-root assumptions now account for the added directory level.
Shell runners, subprocess profile paths, CLI-source test paths and the competing
profile-process path check use the new layout. Direct repository-root Python
imports such as `import scripts.concurrency.local_concurrency_validation` work.

Safe entrypoint and parser checks:

```bash
python3 -B scripts/local/profile_local_latency_breakdown.py --help
python3 -B scripts/local/run_local_latency_breakdown_formal.py --help
python3 -B scripts/concurrency/profile_local_concurrency_control.py --help
python3 -B scripts/concurrency/run_local_concurrency_formal_control.py --help
python3 -B scripts/concurrency/run_local_concurrency_trtexec_probe.py --help
python3 -B scripts/concurrency/canonical.py profile --help
python3 -B scripts/concurrency/canonical.py run --help
```

`canonical.py` is a path adapter to the measured canonical source under
`results/local_canonical_c2/code/` and its analysis source. Those files are
immutable checkpoint provenance, so they were not moved or rewritten. The
canonical full-source profile uses its original termination contract and runtime.
The generic C1/C2 control profiler is a separate historical entrypoint, not a
substitute for the canonical full-source profile.

The `run` route also permits inspecting the original plan without `--execute`.
Historical orchestration and configs retain their exact campaign/source pins and
existing-output guards. Refactored whole-file source hashes are different; this
refactor does not update old pins or authorize replaying any GPU campaign into an
existing results root. A future campaign needs its own explicitly approved plan
and provenance. Historical command strings are not current invocation recipes.

## CPU-only canonical regression and reproduction

Run from the repository root, with new scratch output paths:

```bash
python3 -B scripts/concurrency/verify_canonical.py --output /tmp/canonical-replay.json
python3 -B scripts/concurrency/reproduce_canonical.py --output-dir /tmp/canonical-reproduction
```

The first command runs all 63 Local/concurrency/canonical/termination/event tests,
checks source raw hashes, revalidates every canonical run and compares its summary
against the committed per-run table: 35 runs and 252,000 frames. Raw artifacts must
be available locally; they are not added to Git by this refactor.

The second command copies the frozen analysis/plotting source byte-for-byte to a
new scratch tree, links raw inputs for reading, and redirects imports to the moved
modules. It regenerates six summary CSVs and two analysis JSONs, checks exact byte
identity, then regenerates all four PNGs from hash-pinned compact inputs and checks
exact PNG byte identity. All generated output and Matplotlib cache stay in the
scratch tree. It never launches a GPU workload or alters protected results.

The Local orchestration test fixtures now resolve their temporary output root
explicitly and use current source-file hashes only inside synthetic test config.
The original historical hashes must still be rejected; the original measurement
block hash remains checked. Production source guards were not weakened.

## Historical provenance

Old paths remain in Git history, `configs/` source pins and result reports,
metadata, raw commands, source snapshots and checksums. None of those historical
artifacts was rewritten for this layout. `docs/local_latency_breakdown_formal.md`
contains the updated active Local command paths. See
[scripts_layout_validation.json](scripts_layout_validation.json) for the CPU
regression, exact figure comparison and artifact-preservation record.

## Moved-file inventory

| Original basename under `scripts/` | New path |
|---|---|
| `check_env.sh` | `scripts/initial_profiling/check_env.sh` |
| `profile_decode.py` | `scripts/initial_profiling/profile_decode.py` |
| `profile_preprocess.py` | `scripts/initial_profiling/profile_preprocess.py` |
| `profile_decode_preprocess.py` | `scripts/initial_profiling/profile_decode_preprocess.py` |
| `run_decode_preprocess_profiling.sh` | `scripts/initial_profiling/run_decode_preprocess_profiling.sh` |
| `run_preprocess_profiling.sh` | `scripts/initial_profiling/run_preprocess_profiling.sh` |
| `summarize_decode.py` | `scripts/initial_profiling/summarize_decode.py` |
| `summarize_profiling.py` | `scripts/initial_profiling/summarize_profiling.py` |
| `profile_local_e2e.py` | `scripts/local/profile_local_e2e.py` |
| `profile_local_realtime.py` | `scripts/local/profile_local_realtime.py` |
| `profile_local_latency_breakdown.py` | `scripts/local/profile_local_latency_breakdown.py` |
| `local_latency_breakdown_metrics.py` | `scripts/local/local_latency_breakdown_metrics.py` |
| `run_local_latency_breakdown_formal.py` | `scripts/local/run_local_latency_breakdown_formal.py` |
| `test_local_latency_breakdown.py` | `scripts/local/test_local_latency_breakdown.py` |
| `test_local_latency_breakdown_formal.py` | `scripts/local/test_local_latency_breakdown_formal.py` |
| `analyze_local_concurrency_formal_control.py` | `scripts/concurrency/analyze_local_concurrency_formal_control.py` |
| `local_concurrency_control_metrics.py` | `scripts/concurrency/local_concurrency_control_metrics.py` |
| `local_concurrency_tensorrt.py` | `scripts/concurrency/local_concurrency_tensorrt.py` |
| `local_concurrency_validation.py` | `scripts/concurrency/local_concurrency_validation.py` |
| `profile_local_concurrency_control.py` | `scripts/concurrency/profile_local_concurrency_control.py` |
| `run_local_concurrency_control.py` | `scripts/concurrency/run_local_concurrency_control.py` |
| `run_local_concurrency_formal_control.py` | `scripts/concurrency/run_local_concurrency_formal_control.py` |
| `run_local_concurrency_trtexec_probe.py` | `scripts/concurrency/run_local_concurrency_trtexec_probe.py` |
| `test_local_concurrency_formal_control.py` | `scripts/concurrency/test_local_concurrency_formal_control.py` |
| `test_local_concurrency_validation.py` | `scripts/concurrency/test_local_concurrency_validation.py` |
| `rtdetr_preprocess.py` | `scripts/common/rtdetr_preprocess.py` |
| `smoke_tensor_e2e_client.py` | `scripts/edge/smoke_tensor_e2e_client.py` |
