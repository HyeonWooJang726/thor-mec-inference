# Rate/DVFS Gate V2 verdict

Final: **PIPELINE_AUDIT_FAIL**

V1 plan/runs are historical, untouched and excluded. V1 P01 exclusion_reason=PROTOCOL_V1_ABORT_ON_OC3. V1 root reports/code are preserved in protocol_v1_snapshot.tar.gz.

| Gate | Verdict |
|---|---|
| PIPELINE_AUDIT | FAIL |
| ADMISSION_GATE | INCONCLUSIVE |
| FREQUENCY_CAPACITY_GATE | INCONCLUSIVE |
| ENERGY_OPPORTUNITY_GATE | INCONCLUSIVE |

Pipeline: decode available → admission → admitted-only preprocess → shared ready queue → independent B1 workers. Physical Q uses r→s. Source logical cadence is 30 FPS; appsink drop=false/max-buffers=1; actual pacing, source PTS, front-end rates, concurrency and empty warm-up boundary are replay-audited.

Observed r_star (FPS/stream): {'LOW': None, 'MID': None, 'HIGH': None}. None means no stable tested point; no extrapolation below the grid.

Condition means below use integrity-valid repetitions; at least two required, all valid repeats must agree on stability. Median power is the median of per-run active average power. OC3 does not exclude a valid repetition.

| K | MHz | r | completed FPS | min stream FPS | g_Q | state | avg GPU W | J/frame | clean/protected | valid/attempted |
|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|
| 6 | 1575 | 30 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 6 | 945 | 30 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 6 | 1260 | 30 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1575 | 21 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/1 | 1/1 |
| 7 | 1575 | 24 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1575 | 27 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1575 | 30 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 945 | 21 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 945 | 24 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/1 |
| 7 | 945 | 27 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 945 | 30 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1260 | 21 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1260 | 24 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1260 | 27 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |
| 7 | 1260 | 30 | unavailable | unavailable | unavailable | INCONCLUSIVE | unavailable | unavailable | 0/0 | 0/0 |

ADMISSION_GATE witnesses:
- None.

FREQUENCY_CAPACITY_GATE witnesses:
- None.

ENERGY_OPPORTUNITY_GATE witnesses:
- None.

All same-service energy comparisons (including nonqualifying pairs):

Invalid V2 runs (preserved; no retries):
- RDVG_V2_20260919_P02: front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; front end: Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 399, in front
    raise RuntimeError('PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end')
RuntimeError: PIPELINE_FRONTEND_BOTTLENECK: frame unavailable before active end
; Traceback (most recent call last):
  File "/home/ainet/research/thor-mec-rate-dvfs-gate/scripts/rate_dvfs_gate/run_rate_dvfs_gate.py", line 480, in run_one
    if errors:raise RuntimeError('run stopped after recorded failure')
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: run stopped after recorded failure
; stream 0: deterministic admission mismatch; stream 1: deterministic admission mismatch; stream 2: deterministic admission mismatch; stream 3: deterministic admission mismatch; stream 4: deterministic admission mismatch; stream 5: deterministic admission mismatch; stream 6: deterministic admission mismatch; decode/admission timing corruption; source frame decode record missing; measurement trace: power trace does not bracket active interval or is nonmonotonic; PROCESS_EXIT_FAILURE: returncode=1, signal=None; lifecycle incomplete: active_phase_completed; lifecycle incomplete: drain_completed; lifecycle incomplete: cleanup_completed

Planned campaign observed: primary 2/36; K6 sanity 0/9.
Integrity-valid campaign runs: 1; PROTECTION_LIMITED valid runs: 1.
Power scope: measured GPU rail VDD_GPU. Energy is active-interval only; J/frame only for stable runs. Actual frequency means exclude recorded idle zeros; non-target clocks are retained, not invalidated due to OC3.
No energy fitting/controller or additional workloads. MAXN fixed; default GPC range restored after each run. See per-run manifests for exact restoration and errors.
