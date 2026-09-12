# Early pipeline and characterization evidence

Each navigation entry below is a relative symlink. The target already contains
tracked files and therefore exists in a fresh checkout. Original physical paths
and file contents are unchanged.

| Entry | Relative target | Existing tracked files |
|---|---|---:|
| `decode_profiling` | `../../decode_profiling` | 4 |
| `local_realtime_baseline` | `../../local_realtime_baseline` | 275 |
| `local_latency_breakdown` | `../../local_latency_breakdown` | 22 |
| `local_inference_concurrency` | `../../local_inference_concurrency` | 30 |
| `figures` | `../../figures` | 3 |

These entries classify historical evidence; they do not declare it unused.
`local_realtime_baseline` remains an input to canonical input checks.
`local_inference_concurrency` provides termination-regression and figure inputs;
other existing analysis/configuration consumers also retain their original
paths. Some target files, particularly raw traces, are local-only. Existing
tracked raw/log files remain tracked as before; no additional raw files are added.
