# Proposed Git actions — DO NOT EXECUTE

These commands are a reviewable proposal only. This closeout did not run `git add` or `git rm --cached`. The current `.gitignore` already covers `results/**` and `__pycache__/`; no addition is proposed.

## A. Explicit TRACK paths (282)

The exact paths are the `TRACK` array in [GIT_ACTION_INVENTORY.json](GIT_ACTION_INVENTORY.json). They include the plan/preregistration/analyzer/final-summary/provenance chain for every promoted experiment and all final-study documents. No full raw result tree is included.

## B. Proposed `git rm --cached` (12 explicit paths)

Each entry is generated CPython bytecode. The matching `.py` source is tracked, so removing its index entry does not break the scientific source chain. Local files would remain. No other untrack action is proposed.

```bash
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/analyze_joint.cpython-312.pyc
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/build_dataset.cpython-312.pyc
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/fit_joint.cpython-312.pyc
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/frozen_models.cpython-312.pyc
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/make_figures.cpython-312.pyc
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/reproduce_old.cpython-312.pyc
git rm --cached -- results/local_structural_stage_joint_gate/_scripts/__pycache__/verify_integrity.cpython-312.pyc
git rm --cached -- results/local_structural_stage_model_gate/_scripts/__pycache__/analyze_models.cpython-312.pyc
git rm --cached -- results/local_structural_stage_model_gate/_scripts/__pycache__/build_dataset.cpython-312.pyc
git rm --cached -- results/local_structural_stage_model_gate/_scripts/__pycache__/fit_models.cpython-312.pyc
git rm --cached -- results/local_structural_stage_model_gate/_scripts/__pycache__/make_figures.cpython-312.pyc
git rm --cached -- results/local_structural_stage_model_gate/_scripts/__pycache__/verify_preservation.cpython-312.pyc
```

## C. Proposed `git add` (281 explicit paths)

Use `-f` only for selected ignored `results/**` reproducibility assets. Review content, size, secrets, and repository policy before any later execution. Nothing below was executed.

```bash
git add -- final_study_v1/00_runtime_configuration/FINAL_RUNTIME_CONFIGURATION.md
git add -- final_study_v1/00_runtime_configuration/PAPER_RUNTIME_CONFIGURATION.tex
git add -- final_study_v1/00_runtime_configuration/evidence_index/README.md
git add -- final_study_v1/01_local_scaling/LOCAL_FINALCONFIG_KSWEEP01/README.md
git add -- final_study_v1/01_local_scaling/README.md
git add -- final_study_v1/02_grid03/README.md
git add -- final_study_v1/03_confirmation03/README.md
git add -- final_study_v1/04_mechanism_analysis/README.md
git add -- final_study_v1/05_additional_validation/README.md
git add -- final_study_v1/10_prior_confirmed_evidence/README.md
git add -- final_study_v1/10_prior_confirmed_evidence/configuration_A/README.md
git add -- final_study_v1/10_prior_confirmed_evidence/edge_preflight/README.md
git add -- final_study_v1/10_prior_confirmed_evidence/motivating_measurements/README.md
git add -- final_study_v1/90_paper_exports/README.md
git add -- final_study_v1/90_paper_exports/figures/README.md
git add -- final_study_v1/90_paper_exports/latex/README.md
git add -- final_study_v1/90_paper_exports/tables/README.md
git add -- final_study_v1/98_provenance/FINAL_STUDY_MANIFEST.json
git add -- final_study_v1/98_provenance/README.md
git add -- final_study_v1/98_provenance/SHA256SUMS
git add -- final_study_v1/98_provenance/build_index.py
git add -- final_study_v1/99_legacy_index/FUTURE_CLEANUP_CHECKLIST.md
git add -- final_study_v1/99_legacy_index/GIT_ACTION_INVENTORY.json
git add -- final_study_v1/99_legacy_index/GIT_TRACKING_POLICY.md
git add -- final_study_v1/99_legacy_index/LEGACY_EXPERIMENTS.md
git add -- final_study_v1/99_legacy_index/PROPOSED_GIT_ACTIONS.md
git add -- final_study_v1/README.md
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/analysis01/D100_pairs.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/analysis01/analysis_provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/analysis01/per_condition_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/analysis01/pilot_gate.json
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/block_a_phase_pilot02/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/CONFIRMATION_PREREGISTRATION.md
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/analysis01/confirmation_rounds.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/analysis01/confirmation_summary.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/mechanism_secondary01/backlog_recovery_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/mechanism_secondary01/state_dependent_local_service.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_confirmation02/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/BLOCK_B_PLAN.md
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/analysis01/H1_summary.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/analysis01/policy_four_cell_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/mechanism_audit01/backlog_recovery_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/mechanism_audit01/confirmation_selection_candidate.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/mechanism_audit01/finish_audit.py
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/mechanism_audit01/mechanism_verdict.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/mechanism_audit01/run_audit.py
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/block_b_grid02/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/EDGE_E48_CONFIRMATION_PLAN.md
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/analysis01/paired_E48.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/analysis01/paired_descriptive_summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/EDGE_INFLIGHT_PREREGISTRATION.md
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/EDGE_PREFLIGHT_READY.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/edge_C_robustness.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/paired_aligned_comparison.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/placement_robustness_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/edge_preflight_evidence/edge_preflight_CE1.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/edge_preflight_evidence/edge_preflight_CE2.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/ORDER_ROBUSTNESS_PLAN.md
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/analysis01/order_mechanism_summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/analysis01/order_rounds.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/analysis01/per_dispatch_position.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_order_robustness01/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/EDGE_PREFLIGHT_FINAL02_PLAN.md
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/analysis01/capacity_by_pattern.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/analysis01/condition_classification.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_A1/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_A1/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_A2/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_A2/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_S1/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_S1/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_S2/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E72_S2/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_A1/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_A1/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_A2/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_A2/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_S1/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_S1/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_S2/manifest.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/base/EDGEF02_E80_S2/summary.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/edge_preflight_final02/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/ANALYSIS_SPECIFICATION.md
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/LOCAL_FINALCONFIG_KSWEEP01_PREREGISTRATION.md
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/analysis01/per_K_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/analysis01/per_stream.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/CALIBRATION_PREREGISTRATION.md
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/analysis01/c2_justification.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/analysis01/per_C_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/analysis01/per_run.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration03/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/CALIBRATION_PREREGISTRATION.md
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/analysis01/extension_verdict.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/analysis01/per_C_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/analysis01/tradeoff_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration04/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/CALIBRATION_PREREGISTRATION.md
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/final_C_selection.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/per_C_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/tradeoff_summary.csv
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/session_plan.json
git add -f -- results/timely_capacity_campaign/v2_2/local_inflight_calibration05/source_sha256.json
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/analysis_revision01_result/analysis_provenance.json
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/analysis_revision01_result/deadline_boundary_summary.json
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/analysis_revision01_result/per_rate_timely.csv
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/analysis_revision01_result/per_run_timely.csv
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/plan.json
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/plan.sha256
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/preservation.json
git add -f -- results/timely_capacity_campaign/v2_2/timely_capacity_scan02/source_sha256.json
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/analyze_pilot02.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/block_a_summary.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/pilot02_config.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/prepare_pilot02.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/replay_pilot01_s1.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/run_pilot02.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/test_pilot02_cpu.py
git add -- scripts/timely_capacity_campaign/block_a_phase_pilot/pilot02/test_supervisor_pilot02_cpu.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/analyze.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/block_b_summary.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/confirmation_rules.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/edge_server_grid02.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/grid_config.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/mechanism_after.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/prepare.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/run_thor.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/select_candidate.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/test_cpu.py
git add -- scripts/timely_capacity_campaign/block_b_confirmation02/validate.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/analyze.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/block_b_summary.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/edge_server_grid02.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/grid_config.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/prepare.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/replay_grid01.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/run_thor.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/test_cpu.py
git add -- scripts/timely_capacity_campaign/block_b_grid02/validate.py
git add -- scripts/timely_capacity_campaign/edge_e48_confirmation01/analyze.py
git add -- scripts/timely_capacity_campaign/edge_e48_confirmation01/config.py
git add -- scripts/timely_capacity_campaign/edge_e48_confirmation01/edge_server_confirmation01.py
git add -- scripts/timely_capacity_campaign/edge_e48_confirmation01/prepare.py
git add -- scripts/timely_capacity_campaign/edge_e48_confirmation01/run_thor.py
git add -- scripts/timely_capacity_campaign/edge_e48_confirmation01/test_cpu.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/analyze.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/audit_existing.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/config.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/edge_local_preflight.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/edge_server.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/prepare.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/regression_cpu.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/run_thor.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/test_analysis_synthetic.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/verify_edge_preflight.py
git add -- scripts/timely_capacity_campaign/edge_inflight_robustness02/verify_preparation.py
git add -- scripts/timely_capacity_campaign/edge_order_robustness01/analyze.py
git add -- scripts/timely_capacity_campaign/edge_order_robustness01/config.py
git add -- scripts/timely_capacity_campaign/edge_order_robustness01/edge_server_order01.py
git add -- scripts/timely_capacity_campaign/edge_order_robustness01/prepare.py
git add -- scripts/timely_capacity_campaign/edge_order_robustness01/run_thor.py
git add -- scripts/timely_capacity_campaign/edge_order_robustness01/test_cpu.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/analyze.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/config.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/edge_server_final02.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/prepare.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/rebuild_endpoint.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/run_thor.py
git add -- scripts/timely_capacity_campaign/edge_preflight_final02/test_cpu.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/analyze.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/config.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/integrity.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/ksweep_schedule.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/parent_validation.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/regression_cpu.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/run_ksweep.py
git add -- scripts/timely_capacity_campaign/local_finalconfig_ksweep01/summary_adapter.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/accounting.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/analyze_scan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/config.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/integrity.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/parent_validation.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/prepare.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/regression_cpu.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/run_scan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/selection.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/summary_adapter.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/test_cpu.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration03/verify_preparation.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/accounting.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/analyze_scan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/config.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/integrity.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/parent_validation.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/prepare.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/refreeze_selection_rule.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/regression_cpu.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/run_scan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/selection.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/selection_plan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/summary_adapter.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/test_cpu.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration04/verify_preparation.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/accounting.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/analyze_scan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/config.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/integrity.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/parent_validation.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/prepare.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/refreeze_validation_fix.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/regression_cpu.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/run_scan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/selection.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/selection_plan.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/summary_adapter.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/test_cpu.py
git add -- scripts/timely_capacity_campaign/local_inflight_calibration05/verify_preparation.py
git add -- scripts/timely_capacity_campaign/timely_capacity_scan/analysis_revision01/analyze_revision.py
git add -- scripts/timely_capacity_campaign/timely_capacity_scan/attempt02/analyze_attempt02.py
git add -- scripts/timely_capacity_campaign/timely_capacity_scan/attempt02/attempt02_config.py
git add -- scripts/timely_capacity_campaign/timely_capacity_scan/attempt02/gpu_precheck.py
git add -- scripts/timely_capacity_campaign/timely_capacity_scan/attempt02/run_attempt02.py
git add -- scripts/timely_capacity_campaign/timely_capacity_scan/attempt02/test_attempt02.py
```

## D. Proposed `.gitignore` additions

None. Existing rules already ignore generated results and `__pycache__/`.

## E. Dependency check

Every promoted experiment's plan, available preregistration or scientific plan, analyzer source, selected paper summary, and provenance are in TRACK. The 12 bytecode candidates have tracked `.py` counterparts. All tracked compressed raw CSVs and logs remain REVIEW_BEFORE_UNTRACK. No failed-history, Configuration A/B, motivating, preflight, or robustness evidence is proposed for untracking or deletion. Resolve missing historical preregistration metadata by retaining actual plan documents, never inventing a record.
