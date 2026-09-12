# Research results layout

| Directory | Purpose |
|---|---|
| `results/active/` | Current research inputs, including the K1–7 static-concurrency range discovery. |
| `results/reference/` | Canonical Local reference evidence; `local_canonical_c2` remains a current reference. |
| `results/archive/early_characterization/` | Earlier pipeline and characterization evidence; some artifacts remain validation/input dependencies. |
| `results/archive/concurrency_discovery/` | Pilot and range-extension evidence supporting the formal concurrency range. |
| `results/archive/residual_exploration/` | Residual feasibility, independent reproducibility, and decision-replay evidence retained for negative results and ablations. |

Raw data, frozen source snapshots, manifests, and historical path strings retain
their original contents. Archiving does not invalidate or delete research
evidence. Existing tracked artifacts remain tracked; new raw results and logs
remain ignored. No empty formal-experiment placeholders are required.

## Navigation without physical relocation

The classification tree is a navigation layer. All existing result directories,
including their frozen code/configuration and raw files, remain at their original
physical paths directly under `results/`. No result file was moved or rewritten.

Relative directory symlinks are committed only when the target contains files
already tracked by Git, so the target directory also exists in a fresh checkout.
Such directories can contain additional local-only raw data; the symlink does
not add that data to Git. The canonical reference has a link under `reference/`;
the five early-characterization candidates have links under their archive index.
These are classifications, not declarations that their dependencies are unused.
In particular, `local_realtime_baseline` still supplies canonical input checks.

The active range-discovery campaign, concurrency pilot/range extension, and three
residual campaigns have no tracked target files. Their indexes record physical
paths as plain text and explicitly mark them local-only. No symlink or Markdown
link to those absent-on-GitHub targets is committed.

Start with the [results index](../results/INDEX.md). Historical path strings and
source/checkpoint hashes remain unchanged. Frozen execution entrypoints retain
their existing paths; this cleanup did not run experiments, regenerate results,
or modify execution scripts.

## Empty placeholders and script candidates

Only top-level `analysis/`, `benchmarks/`, and `src/` were removed: each contained
only its one-byte `.gitkeep`, with no untracked content or root-path consumer.
Occurrences of `analysis/` within result directories refer to those nested
directories, which remain intact. `logs/`, `configs/`, `docs/`, `scripts/`, and
`server/` remain intact.

`results/local_realtime_validation/final_k1/` is another empty directory, recorded
as a DELETE CANDIDATE only and retained.

Possible future script-archive candidates (no move/delete performed):

- `scripts/initial_profiling/run_decode_preprocess_profiling.sh`
- `scripts/initial_profiling/run_preprocess_profiling.sh`
- `scripts/initial_profiling/summarize_decode.py`
- `scripts/initial_profiling/summarize_profiling.py`

The audit found no other script calling these entrypoints. This alone does not
prove they are unused externally. Their worker scripts still have callers;
`check_env.sh` remains useful for environment inspection. Any later reorganization
needs a separate dependency review and authorization.
