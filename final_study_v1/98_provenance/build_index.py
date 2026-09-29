"""Build the small final-study evidence/Git proposal indexes; never mutate sources."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "final_study_v1"
V2 = Path("results/timely_capacity_campaign/v2_2")
SCRIPTS = Path("scripts/timely_capacity_campaign")
PROMOTED = {
    "timely_capacity_scan02": ("motivating Local deadline/capacity evidence", "timely_capacity_scan/attempt02", "timely_capacity_scan/analysis_revision01/analyze_revision.py", "analysis_revision01_result", ["per_run_timely.csv", "per_rate_timely.csv", "deadline_boundary_summary.json"], ["VI-A", "Motivation"]),
    "block_a_phase_pilot02": ("foundational Local temporal-phase evidence", "block_a_phase_pilot/pilot02", "block_a_phase_pilot/pilot02/analyze_pilot02.py", "analysis01", ["per_condition_summary.csv", "D100_pairs.csv", "pilot_gate.json"], ["VI-A", "Motivation"]),
    "edge_e48_confirmation01": ("foundational E48 temporal-placement confirmation", "edge_e48_confirmation01", "edge_e48_confirmation01/analyze.py", "analysis01", ["per_run.csv", "paired_E48.csv", "paired_descriptive_summary.json"], ["VI-A", "Robustness"]),
    "edge_order_robustness01": ("foundational E48 dispatch-order robustness", "edge_order_robustness01", "edge_order_robustness01/analyze.py", "analysis01", ["order_mechanism_summary.json", "order_rounds.csv", "per_dispatch_position.csv"], ["VI-A", "Mechanism"]),
    "edge_preflight_final02": ("E72/E80 Edge preflight capacity evidence", "edge_preflight_final02", "edge_preflight_final02/analyze.py", "analysis01", ["capacity_by_pattern.json", "condition_classification.csv", "per_run.csv"], ["Runtime preflight", "Motivation"]),
    "block_b_grid02": ("Configuration A exploratory split/placement and mechanism evidence", "block_b_grid02", "block_b_grid02/analyze.py", "analysis01", ["H1_summary.json", "per_run.csv", "policy_four_cell_summary.csv"], ["Configuration A", "Mechanism"]),
    "block_b_confirmation02": ("Configuration A independent confirmation and secondary mechanism evidence", "block_b_confirmation02", "block_b_confirmation02/analyze.py", "analysis01", ["confirmation_summary.json", "per_run.csv", "confirmation_rounds.csv"], ["Configuration A", "Confirmation"]),
    "local_inflight_calibration03": ("historical Local concurrency calibration", "local_inflight_calibration03", "local_inflight_calibration03/analyze_scan.py", "analysis01", ["c2_justification.json", "per_C_summary.csv", "per_run.csv"], ["VI-B Runtime configuration"]),
    "local_inflight_calibration04": ("historical C3-C5 Local throughput characterization", "local_inflight_calibration04", "local_inflight_calibration04/analyze_scan.py", "analysis01", ["extension_verdict.json", "per_C_summary.csv", "tradeoff_summary.csv"], ["VI-B Runtime configuration"]),
    "local_inflight_calibration05": ("formal final C_L=3 selection", "local_inflight_calibration05", "local_inflight_calibration05/analyze_scan.py", "analysis01", ["final_C_selection.json", "per_C_summary.csv", "tradeoff_summary.csv"], ["VI-B Runtime configuration"]),
    "edge_inflight_robustness02": ("formal ambiguous Edge verdict and prospective C_E=2 queue rationale", "edge_inflight_robustness02", "edge_inflight_robustness02/analyze.py", "analysis01", ["edge_C_robustness.json", "per_run.csv", "paired_aligned_comparison.csv", "placement_robustness_summary.csv"], ["VI-B Runtime configuration", "Robustness"]),
    "local_finalconfig_ksweep01": ("final-configuration Local-only K=1..8 scaling baseline", "local_finalconfig_ksweep01", "local_finalconfig_ksweep01/analyze.py", "analysis01", ["per_K_summary.csv", "per_run.csv", "per_stream.csv"], ["Local scaling", "Grid03 baseline"]),
}
FAILED = {"block_b_grid01", "block_b_confirmation01", "local_inflight_calibration01", "local_inflight_calibration02", "edge_inflight_robustness01"}
PRELIM = {"block_a_phase_pilot01", "edge_preflight_final01", "raw_capacity_scan01", "timely_capacity_scan01", "validation01"}
PREREG = {
    "block_b_confirmation02": "CONFIRMATION_PREREGISTRATION.md",
    "local_inflight_calibration03": "CALIBRATION_PREREGISTRATION.md",
    "local_inflight_calibration04": "CALIBRATION_PREREGISTRATION.md",
    "local_inflight_calibration05": "CALIBRATION_PREREGISTRATION.md",
    "edge_inflight_robustness02": "EDGE_INFLIGHT_PREREGISTRATION.md",
    "local_finalconfig_ksweep01": "LOCAL_FINALCONFIG_KSWEEP01_PREREGISTRATION.md",
}
PLAN_DOC = {
    "block_b_grid02": "BLOCK_B_PLAN.md",
    "edge_e48_confirmation01": "EDGE_E48_CONFIRMATION_PLAN.md",
    "edge_order_robustness01": "ORDER_ROBUSTNESS_PLAN.md",
    "edge_preflight_final02": "EDGE_PREFLIGHT_FINAL02_PLAN.md",
}
ADDITIONAL_ANALYSIS = {
    "block_b_grid02": ("mechanism_audit01", ["mechanism_verdict.json", "confirmation_selection_candidate.json", "backlog_recovery_summary.csv"], ["run_audit.py", "finish_audit.py"]),
    "block_b_confirmation02": ("mechanism_secondary01", ["backlog_recovery_summary.csv", "state_dependent_local_service.csv"], []),
}
RUNTIME = {
    "timely_capacity_scan02": "Historical Local-only: C_L=2, B=1, K=8; no Edge network connection",
    "block_a_phase_pilot02": "Historical Local-only: C_L=2, B=1, K=8; no Edge network connection",
    "edge_e48_confirmation01": "Historical Edge E48: C_E=1, B=1, K=8",
    "edge_order_robustness01": "Historical Edge E48: C_E=1, B=1, K=8",
    "edge_preflight_final02": "Historical Edge E72/E80: C_E=1, B=1, K=8",
    "block_b_grid02": "Configuration A: C_L=2, C_E=1, B=1, K=8",
    "block_b_confirmation02": "Configuration A: C_L=2, C_E=1, B=1, K=8",
    "local_inflight_calibration03": "Local-only: C_L=1,2,3,4, B=1, K=8 (measured per-run C_L)",
    "local_inflight_calibration04": "Local-only: C_L=3,4,5, B=1, K=8 (measured per-run C_L)",
    "local_inflight_calibration05": "Local-only: C_L=3,4,5,6, B=1, K=8 (measured per-run C_L)",
    "edge_inflight_robustness02": "Edge E48 sensitivity: C_E=1,2, B=1, K=8; Local C_L=3 frozen for later primary study",
    "local_finalconfig_ksweep01": "Configuration B Local-only baseline: C_L=3, B=1, Edge OFF, K=1..8",
}


def sha(rel: str | None) -> str | None:
    if rel is None or not (ROOT / rel).is_file():
        return None
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def existing(rel: Path | str | None) -> str | None:
    if rel is None:
        return None
    value = str(rel)
    return value if (ROOT / value).exists() else None


def file_entry(rel: str | None) -> dict | None:
    return {"path": rel, "sha256": sha(rel)} if rel else None


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True)


def main() -> None:
    names = {p.name for p in (ROOT / V2).iterdir() if p.is_dir()}
    expected = set(PROMOTED) | FAILED | PRELIM
    if names != expected:
        raise RuntimeError(f"Unexpected v2_2 inventory: missing={sorted(expected-names)}, extra={sorted(names-expected)}")
    entries = []
    track = set()
    for name in sorted(PROMOTED):
        role, src_dir, analyzer, analysis_dir, summaries, sections = PROMOTED[name]
        base, src = V2 / name, SCRIPTS / src_dir
        prereg = existing(base / PREREG[name]) if name in PREREG else None
        plan_doc = existing(base / PLAN_DOC[name]) if name in PLAN_DOC else None
        plan = existing(base / "plan.json")
        plan_sha_file = existing(base / "plan.sha256")
        analysis = existing(base / analysis_dir)
        analyzer_path = existing(SCRIPTS / analyzer)
        provenance = [existing(base / "source_sha256.json"), existing(base / "preservation.json"), existing(base / analysis_dir / "provenance.json"), existing(base / analysis_dir / "analysis_provenance.json")]
        if name == "edge_inflight_robustness02":
            provenance += [existing(base / "EDGE_PREFLIGHT_READY.json"), existing(base / "edge_preflight_evidence/edge_preflight_CE1.json"), existing(base / "edge_preflight_evidence/edge_preflight_CE2.json")]
        provenance = [p for p in provenance if p]
        extras = {}
        if name in ADDITIONAL_ANALYSIS:
            extra_dir, extra_summaries, extra_scripts = ADDITIONAL_ANALYSIS[name]
            extras = {
                "path": existing(base / extra_dir),
                "summary_files": [file_entry(existing(base / extra_dir / n)) for n in extra_summaries],
                "analyzer_sources": [file_entry(existing(base / extra_dir / n)) for n in extra_scripts],
            }
        final_files = [file_entry(existing(base / analysis_dir / s)) for s in summaries]
        missing = [s for s, f in zip(summaries, final_files) if f is None]
        if missing or not plan or not analyzer_path or not analysis:
            raise RuntimeError(f"Missing promoted asset for {name}: summary={missing}, plan={plan}, analyzer={analyzer_path}, analysis={analysis}")
        analysis_spec = existing(base / "ANALYSIS_SPECIFICATION.md")
        e = {
            "experiment_name": name,
            "scientific_role": role,
            "classification": "FINAL_STUDY_PROMOTED_EVIDENCE",
            "runtime_configuration": RUNTIME[name],
            "canonical_source_path": str(src),
            "canonical_result_path": str(base),
            "plan_path": plan,
            "plan_sha256": sha(plan),
            "plan_sha256_file": file_entry(plan_sha_file),
            "preregistration_path": prereg,
            "preregistration_sha256": sha(prereg),
            "scientific_plan_document": file_entry(plan_doc),
            "analyzer_source_path": analyzer_path,
            "analyzer_source_sha256": sha(analyzer_path),
            "analysis_specification": file_entry(analysis_spec),
            "final_analysis_path": analysis,
            "final_summary_outputs": final_files,
            "additional_analysis": extras or None,
            "hash_provenance_paths": [file_entry(p) for p in provenance],
            "paper_sections": sections,
            "git_tracking_recommendation": "TRACK small reproducibility assets; raw traces REVIEW_BEFORE_UNTRACK",
            "cleanup_protection_status": "PROTECTED_NOT_SAFE_FOR_LEGACY_CLEANUP",
            "metadata_gap": ("No separately named preregistration document found; frozen plan document is indexed" if not prereg and plan_doc else "No separately named preregistration or plan document found; frozen plan.json is indexed" if not prereg else None),
        }
        if name == "edge_preflight_final02":
            run_dirs = sorted((ROOT / base / "base").glob("EDGEF02_E72_*")) + sorted((ROOT / base / "base").glob("EDGEF02_E80_*"))
            if len(run_dirs) != 8:
                raise RuntimeError(f"Expected eight E72/E80 preflight run directories, found {len(run_dirs)}")
            e["e72_e80_run_evidence"] = []
            for run_dir in run_dirs:
                summary = existing(run_dir.relative_to(ROOT) / "summary.json")
                run_manifest = existing(run_dir.relative_to(ROOT) / "manifest.json")
                if not summary or not run_manifest:
                    raise RuntimeError(f"Incomplete preflight run evidence: {run_dir}")
                e["e72_e80_run_evidence"].append({"run_id": run_dir.name, "summary": file_entry(summary), "manifest": file_entry(run_manifest)})
                track.update((summary, run_manifest))
        if name == "block_b_confirmation02":
            e["additional_analyzer_sources"] = [file_entry(existing(SCRIPTS / "block_b_confirmation02/mechanism_after.py"))]
        entries.append(e)
        for p in [plan, plan_sha_file, prereg, plan_doc, analyzer_path, analysis_spec, existing(base / "session_plan.json"), *provenance]:
            if p and (ROOT / p).is_file():
                track.add(p)
        for f in final_files:
            track.add(f["path"])
        if extras:
            for f in extras["summary_files"] + extras["analyzer_sources"]:
                if f:
                    track.add(f["path"])
        for p in (ROOT / src).rglob("*.py"):
            if "__pycache__" not in p.parts:
                track.add(str(p.relative_to(ROOT)))
    for name in sorted(FAILED | PRELIM):
        base = V2 / name
        entries.append({
            "experiment_name": name,
            "scientific_role": "failed/invalid historical evidence; no performance result" if name in FAILED else "preliminary or exploratory historical evidence",
            "classification": "FAILED_OR_INVALID_RETAIN" if name in FAILED else "PRELIMINARY_OR_EXPLORATORY_RETAIN",
            "runtime_configuration": "Historical experiment-specific runtime; see frozen plan",
            "canonical_source_path": existing(SCRIPTS / name),
            "canonical_result_path": str(base),
            "plan_path": existing(base / "plan.json"),
            "plan_sha256": sha(existing(base / "plan.json")),
            "plan_sha256_file": file_entry(existing(base / "plan.sha256")),
            "preregistration_path": next((str(p.relative_to(ROOT)) for p in sorted((ROOT / base).glob("*PREREGISTRATION.md"))), None),
            "preregistration_sha256": next((sha(str(p.relative_to(ROOT))) for p in sorted((ROOT / base).glob("*PREREGISTRATION.md"))), None),
            "analyzer_source_path": None,
            "final_analysis_path": None,
            "final_summary_outputs": [],
            "hash_provenance_path": existing(base / "source_sha256.json"),
            "paper_sections": ["Failed-attempt provenance"] if name in FAILED else [],
            "git_tracking_recommendation": "REVIEW_BEFORE_UNTRACK; preserve locally",
            "cleanup_protection_status": "PROTECTED_NOT_SAFE_FOR_LEGACY_CLEANUP" if name in FAILED else "UNDECIDED_RETAIN",
            "performance_evidence_status": "NO_PERFORMANCE_EVIDENCE" if name == "edge_inflight_robustness01" else None,
        })
    active = [
        {"experiment_name": n, "scientific_role": role, "classification": "FINAL_STUDY_ACTIVE", "runtime_configuration": "Forward Configuration B: C_L=3, C_E=2, B=1", "canonical_source_path": None, "canonical_result_path": None, "plan_path": None, "plan_sha256": None, "preregistration_path": None, "preregistration_sha256": None, "analyzer_source_path": None, "final_analysis_path": None, "hash_provenance_path": None, "paper_sections": [section], "git_tracking_recommendation": "TRACK once created", "cleanup_protection_status": "PROTECTED_NOT_SAFE_FOR_LEGACY_CLEANUP"}
        for n, role, section in [
            ("Grid03", "future final primary split/placement evaluation", "Grid03"),
            ("Confirmation03", "future independent Configuration B confirmation", "Confirmation03"),
            ("Final mechanism analysis", "future secondary mechanism analysis", "Mechanism"),
            ("Additional validation", "future validation if separately required", "Validation"),
        ]
    ]
    top = sorted(p.name for p in (ROOT / "results").iterdir() if p.is_dir())
    other_campaign = sorted(p.name for p in (ROOT / "results/timely_capacity_campaign").iterdir() if p.is_dir() and p.name != "v2_2")
    manifest = {
        "schema": "final_study_v1/1",
        "basis": "read-only existing evidence; no scientific result copied or changed",
        "final_primary_runtime": {"C_L": 3, "C_E": 2, "B": 1, "C_L_status": "FORMAL_SELECTION", "historical_Edge_formal_verdict": "EDGE_C_REPEAT_AMBIGUOUS", "historical_C_E_selected": None, "forward_C_E_status": "PROSPECTIVE_CONSERVATIVE_RUNTIME_CONFIGURATION"},
        "classification_counts_v2_2": {"FINAL_STUDY_PROMOTED_EVIDENCE": len(PROMOTED), "FAILED_OR_INVALID_RETAIN": len(FAILED), "PRELIMINARY_OR_EXPLORATORY_RETAIN": len(PRELIM), "LEGACY_NOT_REQUIRED_FOR_FINAL_PAPER": 0},
        "experiments": entries + active,
        "other_result_root_inventory": [{"path": f"results/{n}", "classification": "UNDECIDED_RETAIN", "cleanup_protection_status": "NOT_ASSESSED"} for n in top if n != "timely_capacity_campaign"],
        "other_timely_capacity_campaign_inventory": [{"path": f"results/timely_capacity_campaign/{n}", "classification": "UNDECIDED_RETAIN", "cleanup_protection_status": "NOT_ASSESSED"} for n in other_campaign],
    }
    out = STUDY / "98_provenance/FINAL_STUDY_MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    runtime_names = ["local_inflight_calibration03", "local_inflight_calibration04", "local_inflight_calibration05", "edge_inflight_robustness02"]
    runtime_lines = ["# Runtime configuration evidence index", "", "Canonical paths and SHA-256 values for the C_L calibration history and Edge robustness evidence. These are links to existing files; no raw results are duplicated.", "", "| Experiment | Plan SHA-256 | Preregistration SHA-256 | Selection/robustness output |", "| --- | --- | --- | --- |"]
    for name in runtime_names:
        e = next(x for x in entries if x["experiment_name"] == name)
        decisive = next(f for f in e["final_summary_outputs"] if f["path"].endswith(".json"))
        runtime_lines.append(f"| {name} | `{e['plan_sha256']}` | `{e['preregistration_sha256']}` | `{decisive['path']}` (`{decisive['sha256']}`) |")
    runtime_lines += ["", "Calibration05 alone formally selects C_L=3. Robustness02's historical TIR verdict is `EDGE_C_REPEAT_AMBIGUOUS` and C_E selected is null; its queue evidence supports a separate prospective C_E=2 choice before Grid03.", "", "Provenance note: Calibration04/05 inherited a generic `plan.runtime.C_L` template string that names the older C1–C4 range. Their frozen session plans and actual `analysis01/per_run.csv` identify the tested sets as C3–C5 and C3–C6, respectively. This index uses those measured per-run cardinalities and leaves the historical plans untouched."]
    runtime_index = STUDY / "00_runtime_configuration/evidence_index/README.md"
    runtime_index.parent.mkdir(parents=True, exist_ok=True)
    runtime_index.write_text("\n".join(runtime_lines) + "\n")
    tracked = set(command("git", "ls-files").splitlines())
    pyc = sorted(p for p in tracked if p.endswith(".pyc"))
    review = sorted(p for p in tracked if p.startswith("results/") and (p.endswith(".csv.gz") or p.endswith(".log")))
    for p in pyc:
        source = str(Path(p).parent.parent / Path(p).name.split(".cpython-")[0]) + ".py"
        if source not in tracked:
            raise RuntimeError(f"No tracked source for proposed pyc untrack: {p} -> {source}")
    track.update(str(p.relative_to(ROOT)) for p in STUDY.rglob("*") if p.is_file())
    track.add("final_study_v1/98_provenance/SHA256SUMS")
    track.add("final_study_v1/99_legacy_index/GIT_TRACKING_POLICY.md")
    track.add("final_study_v1/99_legacy_index/PROPOSED_GIT_ACTIONS.md")
    track.add("final_study_v1/99_legacy_index/FUTURE_CLEANUP_CHECKLIST.md")
    track.add("final_study_v1/99_legacy_index/LEGACY_EXPERIMENTS.md")
    track.add(".gitignore")
    if (ROOT / "README.md").is_file():
        track.add("README.md")
    git_inventory = {"TRACK": sorted(track), "UNTRACK_KEEP_LOCAL": pyc, "REVIEW_BEFORE_UNTRACK": review, "proposed_git_rm_cached_commands": [f"git rm --cached -- {p}" for p in pyc], "proposed_git_add_commands": [f"git add {'-f ' if p.startswith('results/') else ''}-- {p}" for p in sorted(track) if p not in tracked]}
    (STUDY / "99_legacy_index/GIT_ACTION_INVENTORY.json").write_text(json.dumps(git_inventory, indent=2) + "\n")
    # Add this inventory to the TRACK proposal itself, without making the list circular.
    inventory_path = "final_study_v1/99_legacy_index/GIT_ACTION_INVENTORY.json"
    if inventory_path not in git_inventory["TRACK"]:
        git_inventory["TRACK"].append(inventory_path)
        git_inventory["TRACK"].sort()
    add_inventory = f"git add -- {inventory_path}"
    if inventory_path not in tracked and add_inventory not in git_inventory["proposed_git_add_commands"]:
        git_inventory["proposed_git_add_commands"].append(add_inventory)
        git_inventory["proposed_git_add_commands"].sort()
    (STUDY / "99_legacy_index/GIT_ACTION_INVENTORY.json").write_text(json.dumps(git_inventory, indent=2) + "\n")
    policy = f"""# Git tracking policy — review only\n\nThis audit did not change the Git index. The explicit path lists and exact future commands are in [GIT_ACTION_INVENTORY.json](GIT_ACTION_INVENTORY.json) and [PROPOSED_GIT_ACTIONS.md](PROPOSED_GIT_ACTIONS.md). Counts are explicit path entries, not directories: TRACK {len(git_inventory['TRACK'])}, UNTRACK_KEEP_LOCAL {len(pyc)}, REVIEW_BEFORE_UNTRACK {len(review)}.\n\n## TRACK\n\nTrack small reproducibility assets for all {len(PROMOTED)} promoted campaigns: frozen plans and hashes, preregistration or extant scientific plan documents, session plans, analyzer and source code, analysis specifications, selected final summary CSV/JSON, and provenance/hash manifests. Track all final-study index documents. These assets are mandatory even though `results/**` currently ignores the v2_2 result tree; future explicit `git add -f -- <path>` commands are proposed, not run. A missing historical preregistration is recorded as null rather than fabricated. Keep `.gitignore` and repository README files tracked.\n\n## UNTRACK_KEEP_LOCAL\n\nThe {len(pyc)} already-tracked CPython `.pyc` files listed in the inventory are generated bytecode. Each has a tracked `.py` source counterpart. Proposed `git rm --cached` would remove only the Git index entry, retaining the local file; no command was executed. No scientific campaign directory is classified wholesale as untrackable.\n\n## REVIEW_BEFORE_UNTRACK\n\nThe {len(review)} tracked `results/**/*.csv.gz`/`*.log` files listed in the inventory may be raw or diagnostic scientific evidence. Their references and retention requirements require a separate dependency review; no untrack command is proposed for them. Other raw inputs referenced by analyses, mechanism traces, preflight evidence, failed-history evidence, and any plan/manifest/paper references are likewise REVIEW_BEFORE_UNTRACK when considered. When uncertain, retain and review.\n\nCurrent `.gitignore` already contains `results/**` and `__pycache__/`; it does not remove previously tracked files. No `.gitignore` addition is proposed in this task. This proposal does not authorize physical deletion.\n"""
    (STUDY / "99_legacy_index/GIT_TRACKING_POLICY.md").write_text(policy)
    lines = ["# Proposed Git actions — DO NOT EXECUTE", "", "These commands are a reviewable proposal only. This closeout did not run `git add` or `git rm --cached`. The current `.gitignore` already covers `results/**` and `__pycache__/`; no addition is proposed.", "", f"## A. Explicit TRACK paths ({len(git_inventory['TRACK'])})", "", "The exact paths are the `TRACK` array in [GIT_ACTION_INVENTORY.json](GIT_ACTION_INVENTORY.json). They include the plan/preregistration/analyzer/final-summary/provenance chain for every promoted experiment and all final-study documents. No full raw result tree is included.", "", f"## B. Proposed `git rm --cached` ({len(pyc)} explicit paths)", "", "Each entry is generated CPython bytecode. The matching `.py` source is tracked, so removing its index entry does not break the scientific source chain. Local files would remain. No other untrack action is proposed.", "", "```bash", *git_inventory["proposed_git_rm_cached_commands"], "```", "", f"## C. Proposed `git add` ({len(git_inventory['proposed_git_add_commands'])} explicit paths)", "", "Use `-f` only for selected ignored `results/**` reproducibility assets. Review content, size, secrets, and repository policy before any later execution. Nothing below was executed.", "", "```bash", *git_inventory["proposed_git_add_commands"], "```", "", "## D. Proposed `.gitignore` additions", "", "None. Existing rules already ignore generated results and `__pycache__/`.", "", "## E. Dependency check", "", "Every promoted experiment's plan, available preregistration or scientific plan, analyzer source, selected paper summary, and provenance are in TRACK. The 12 bytecode candidates have tracked `.py` counterparts. All tracked compressed raw CSVs and logs remain REVIEW_BEFORE_UNTRACK. No failed-history, Configuration A/B, motivating, preflight, or robustness evidence is proposed for untracking or deletion. Resolve missing historical preregistration metadata by retaining actual plan documents, never inventing a record."]
    (STUDY / "99_legacy_index/PROPOSED_GIT_ACTIONS.md").write_text("\n".join(lines) + "\n")
    checksum_lines = []
    for p in sorted(STUDY.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            rel = p.relative_to(STUDY)
            checksum_lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}")
    (STUDY / "98_provenance/SHA256SUMS").write_text("\n".join(checksum_lines) + "\n")
    print(json.dumps({"promoted": len(PROMOTED), "failed": len(FAILED), "preliminary": len(PRELIM), "legacy": 0, "track": len(git_inventory["TRACK"]), "untrack": len(pyc), "review": len(review), "rm_cached_commands": len(pyc), "add_commands": len(git_inventory["proposed_git_add_commands"]), "missing_preregistrations": [e["experiment_name"] for e in entries if e["classification"] == "FINAL_STUDY_PROMOTED_EVIDENCE" and e["preregistration_path"] is None]}, indent=2))


if __name__ == "__main__":
    main()
