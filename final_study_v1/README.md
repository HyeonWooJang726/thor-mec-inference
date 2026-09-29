# Final study v1 — evidence index

This workspace indexes canonical experiments by path and SHA-256. It does not move or duplicate raw measurements. The [manifest](98_provenance/FINAL_STUDY_MANIFEST.json) is the machine-readable evidence chain.

| Sequence | Role | Status |
| --- | --- | --- |
| [00 Runtime Configuration Closeout](00_runtime_configuration/FINAL_RUNTIME_CONFIGURATION.md) | C_L=3 formal selection; historical Edge verdict `EDGE_C_REPEAT_AMBIGUOUS`, C_E selected = null; prospective C_E=2 before Grid03; B=1 fixed | Frozen forward runtime: C_L=3, C_E=2, B=1 |
| [01 Local Final-Config Scaling](01_local_scaling/README.md) | LOCAL_FINALCONFIG_KSWEEP01, actual K=1..8 | Final-configuration baseline |
| [02 Grid03](02_grid03/README.md) | Final primary workload-split and temporal-placement evaluation | Future active study; no results indexed yet |
| [03 Confirmation03](03_confirmation03/README.md) | Independent confirmation under Configuration B | Future active study |
| [04 Mechanism Analysis](04_mechanism_analysis/README.md) | Explain observed behavior without changing primary rules | Future active study |
| [05 Additional Validation](05_additional_validation/README.md) | Validation only if separately specified | Conditional future study |
| [10 Prior Confirmed Evidence](10_prior_confirmed_evidence/README.md) | Motivating/foundational measurements, Configuration A, and Edge E72/E80 preflight | Promoted evidence, not cleanup candidates |
| [90 Paper Exports](90_paper_exports/README.md) | Small reproducible tables, figures, and LaTeX | Output staging |
| [98 Provenance](98_provenance/README.md) | Paths and SHA-256 | Evidence traceability |
| [99 Legacy Index](99_legacy_index/LEGACY_EXPERIMENTS.md) | Retention and proposed Git policy | No Git index changes made |

Configuration A (C_L=2, C_E=1) remains valid under its preregistered conditions. Configuration B is the forward primary runtime (C_L=3, C_E=2, B=1). Their repeats must remain separate. The C_E=2 choice is a prospective conservative runtime choice, not the outcome of the historical TIR-based formal Edge rule.

Paper-facing terms are **temporally concentrated placement** (implementation label `ALIGNED`) and **temporally dispersed placement** (implementation label `STAGGERED`). The manipulated variable is the temporal distribution of Local/Edge assignments at a fixed mean split; camera-source synchronization is not claimed to change, and placement is more than execution order.
