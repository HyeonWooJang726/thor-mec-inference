# Residual exploration evidence

| Campaign | Existing physical path | Availability |
|---|---|---|
| Residual feasibility | `results/local_residual_feasibility/` | Local-only; no tracked target files. |
| Independent reproducibility | `results/local_residual_reproducibility/` | Local-only; no tracked target files. |
| Decision-utility shadow replay | `results/local_residual_decision_replay/` | Local-only; no tracked target files. |

These results are retained as negative/ablation evidence even though residual
prediction is not currently adopted as a core scheduler state. Frozen models,
code/configuration, predictions, reports, and raw traces remain unchanged at
their original physical paths. No symlinks or Markdown links to these local-only
directories are committed.
