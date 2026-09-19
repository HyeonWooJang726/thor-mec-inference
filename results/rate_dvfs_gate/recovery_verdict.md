# Process lifecycle recovery

Outcome: **RECOVERY_PASS**

Existing V2 pipeline semantics evidence remains PASS. Process lifecycle is assessed independently; historical verdicts/plans/runs are unchanged.

| Recovery | returncode | signal | integrity | OC3 delta / hardware | restore |
|---|---:|---|---|---|---|
| A1 | 0 | none | VALID | 1 / PROTECTION_LIMITED | True |
| A2 | 0 | none | VALID | 0 / CLEAN | True |
| B | 0 | none | VALID | 0 / CLEAN | True |

PIPELINE_SEMANTICS = PASS
PROCESS_LIFECYCLE = PASS
PIPELINE_AUDIT = PASS

Primary authorization: all three recovery results must be finalized VALID with exit 0. No recovery retries are performed by this command.


## Primary progression after recovery PASS

All three recovery children exited 0. The previous unexplained post-summary
abnormal exit was not reproduced in these three observations; its historical
cause remains unknown. No deterministic teardown fix is claimed. Changes were
lifecycle instrumentation and supervisor finalization, with source/admission/
preprocess/inference function ASTs verified unchanged.

The user-authorized primary campaign then started with the existing V2 conditions.

- RDVG_V2_20260919_P01: K7/C4/r21/HIGH, child_returncode=0, signal=null,
  integrity VALID, OC3_delta=4 (PROTECTION_LIMITED), restore=true. Full 60-second
  source count12600; admitted/ready/started/completed8820, all accounted. Active
  completed rate146.95 FPS. OC3 did not abort or invalidate this run.
- RDVG_V2_20260919_P02: K7/C4/r24/LOW, child_returncode=1, signal=null,
  integrity INVALID, OC3_delta=0 (CLEAN), restore=true. The actual recorded error
  is the existing front-end guard: decoded source frame unavailable before active
  end. Last accounting: scheduled12600, decoded12242, admitted/ready/started/
  completed9785. Final-window source-pending [a,m) slope3.802114 frames/s exceeds
  the pre-existing V2 diagnostic criterion; [m,r) slope=-0.001683 frames/s and
  ready deficit0.0001022 show that this is not an admitted-to-ready backlog claim.
  Some source frames were not decoded/admitted before the active boundary.
  Active/drain/cleanup completion flags accurately remain false; cleanup started
  and frequency restore=true. This known Python exception is distinct from the
  historical unknown post-summary exit, and is not PROCESS_EXIT_REPRODUCED in
  the recovery experiment.

The unchanged V2 PIPELINE_FRONTEND_BOTTLENECK stop rule terminated the campaign.
K7 attempted2/36 (1 VALID,1 INVALID); K6 attempted0/9. No retries, replacements,
new conditions, threshold changes, or pipeline redesign. Raw failures are retained.
The physical cause of the source-availability slowdown is not established.
Read-only kernel query around P02 completed successfully with no matching
segfault/OOM/GPU-Xid/process-kill entries. No privileged log access was attempted.

Recovery-specific PIPELINE_SEMANTICS=PASS, PROCESS_LIFECYCLE=PASS,
PIPELINE_AUDIT=PASS remain valid statements about A1/A2/B. The later primary
matrix is incomplete and encountered a separate front-end audit failure; it
cannot establish RATE_DVFS_GATE_PASS. See gate_verdict_recovery.md and the two
new *_recovery.csv indexes. Older reports and run files were not overwritten.

Exact executed sources and recovery execution metadata are preserved in
recovery_source_snapshot.tar.gz. A later analysis-only comparison fix tolerates
ordering of identical error multisets between child analysis and supervisor
finalization; no samples, statuses or numerical criteria were changed.
