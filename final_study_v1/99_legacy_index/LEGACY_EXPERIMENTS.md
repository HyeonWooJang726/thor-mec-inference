# Scientific campaign inventory and retention classification

The [machine-readable manifest](../98_provenance/FINAL_STUDY_MANIFEST.json) inventories every immediate campaign under `results/timely_capacity_campaign/v2_2/` and lists other top-level result roots as `UNDECIDED_RETAIN`. Classification is about the final-paper evidence chain, not deletion permission. No directory was moved, deleted, or rewritten.

| Classification | Canonical v2_2 campaigns | Count |
| --- | --- | ---: |
| `FINAL_STUDY_PROMOTED_EVIDENCE` | `timely_capacity_scan02`, `block_a_phase_pilot02`, `edge_e48_confirmation01`, `edge_order_robustness01`, `edge_preflight_final02` (E72/E80), `block_b_grid02`, `block_b_confirmation02`, `local_inflight_calibration03`, `local_inflight_calibration04`, `local_inflight_calibration05`, `edge_inflight_robustness02`, `local_finalconfig_ksweep01` | 12 |
| `FAILED_OR_INVALID_RETAIN` | `block_b_grid01`, `block_b_confirmation01`, `local_inflight_calibration01`, `local_inflight_calibration02`, `edge_inflight_robustness01` | 5 |
| `PRELIMINARY_OR_EXPLORATORY_RETAIN` | `block_a_phase_pilot01`, `edge_preflight_final01`, `raw_capacity_scan01`, `timely_capacity_scan01`, `validation01` | 5 |
| `LEGACY_NOT_REQUIRED_FOR_FINAL_PAPER` | None classified | 0 |

The three named concurrency failed-history attempts remain preserved. In particular, `edge_inflight_robustness01` has `NO_PERFORMANCE_EVIDENCE`; its invalid run is never a C_E performance observation. Grid01 and Confirmation01 are also preserved as invalid/setup-aborted scientific history. An initial or superseded preparation is not silently deleted because a corrected campaign exists.

Configuration A (`block_b_grid02` and `block_b_confirmation02`, including mechanism analyses) is valid for C_L=2, C_E=1 and is promoted evidence. Configuration B is the prospective final runtime C_L=3, C_E=2, B=1; its current Local scaling baseline is `local_finalconfig_ksweep01`. A contains single-worker Edge serialization; Robustness02 shows the size of C_E=1→2 sensitivity. Do not pool A and B repeats or call A a failed configuration.

Future `Grid03`, `Confirmation03`, mechanism analysis, and additional validation are `FINAL_STUDY_ACTIVE` placeholders, not measured outcomes. Top-level results outside v2_2 and the older `timely_capacity_campaign` subdirectories remain `UNDECIDED_RETAIN` pending a separate dependency audit; zero campaigns are presently marked safe for physical cleanup.
