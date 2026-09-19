# Rate / GPC frequency Gate V2 — SMOKE_PREPARATION

## 1. Local Pipeline Audit

**PIPELINE_AUDIT_FAIL — clean process shutdown not established.**
Both smoke raw replays pass source/admission/ready/completion accounting, physical
queue and concurrency checks. However, SMOKE01 child exited nonzero after writing
its pre-exit VALID summary. The original supervisor observed its nonzero branch
but did not persist the numeric exit code or finalize the summary accordingly.
No cause or particular signal can be inferred from that missing record. Kernel
journal query returned no entries and /var/crash was empty. SMOKE02 supervisor
observed successful exit. No primary run or retry has occurred.

V2 smoke observations (diagnostic only):

| Smoke | source FPS | admitted FPS | ready FPS | completed FPS | concurrency peak/mean | hardware |
|---|---:|---:|---:|---:|---|---|
| HIGH/r30 | 210 | 210 | 210 | 209.7 | 4 / 3.2667 | CLEAN |
| LOW/r21 | 210 | 147 | 147 | 146.2 | 4 / 3.1511 | CLEAN |

Both had 2100 source frames, respectively 2100/1470 admitted and completed after
drain, no unexplained source drop, empty premeasurement queue, no sustained
front-end bottleneck, and default GPC range restored. Their original five files
remain unchanged. The V2 aggregate index overlays SMOKE01 integrity=INVALID
using the supervisor observation recorded below; it never rewrites old summaries.

The supervisor implementation was corrected after this finding: future new runs
capture the child return code/output and finalize their manifest and summary
only after process exit. Primary guards now require a confirmed zero smoke exit.
No GPU run validates that correction yet, and no speculative native teardown
workaround was introduced. This is a smoke prerequisite failure, distinct from
the rule to continue after an ordinary INVALID primary repetition.

This document remains a blocked preparation plan, **not a final frozen primary
plan**. Thresholds/grids/order were not changed. The exact smoke code/preparation
plan and prior derived reports are retained in protocol_v2_smoke_snapshot.tar.gz;
its code hashes match the immutable smoke manifests. A diagnosed recovery
and fresh smoke IDs are needed before primary execution. No automatic retry.
Existing engine/video/frequency provenance and active switching evidence are
reused; those already-passed capability workloads are not repeated.

- Source pacing: existing scheduler issues logical arrivals a=t0+floor(n*1e9/30).
  A front-end thread only pulls a source frame after that arrival. Unchanged
  GStreamer appsink sync=false, max-buffers=1, drop=false provides bounded
  backpressure. Decode may prepare a bounded frame ahead; it cannot release an
  unpaced source workload to admission. Source identity/PTS and source-to-m lag
  are checked. Exact expected counts: primary 1800/stream, smoke 300/stream.
- Admission correction: V1 decided admission in the scheduler before decode.
  V2 scheduler only schedules the source. Front-end obtains a decoded sample,
  records availability, makes deterministic admission decision m, then invokes
  unchanged preprocess_bgr only for admitted frames. Skipped frames retain
  source/PTS/m/admitted=false and have no preprocessing-ready/service timestamps.
- Physical GPU queue correction: Q_k(t)=number of r<=t<s requests. r is the
  existing QueueAccounting.enqueue timestamp after preprocessing; s is the
  unchanged accounting.start timestamp immediately before ContextWorker.infer.
  Admission m and r remain separate. The shared ready FIFO is not rewritten.
- Front-end diagnostics: active source, admitted, ready and completed FPS;
  source-to-admission latency and the exact time-weighted slope of source pending
  [a,m) and preprocessing pending [m,r), each in the final half of smoke or final
  30 seconds of primary. PIPELINE_FRONTEND_BOTTLENECK if ready count lags active
  admitted count by >1% AND preprocessing-pending slope >0.5 aggregate or >0.2
  any stream; also if source-pending slope >0.5 aggregate or >0.2 any stream.
  These diagnostic engineering thresholds are fixed before V2 GPU results.
  A decoded frame arriving too late for admission before active end records a
  front-end failure, never becomes an unlogged drop or a fabricated GPU bottleneck.
- Concurrency: reuse unchanged TensorRT ContextWorker, independent contexts,
  nonblocking CUDA streams and private pinned/device buffers. Only queue accounting
  holds a brief lock; infer/stream synchronization executes outside the lock.
  One engine, B=1, no dynamic batching, no global cudaDeviceSynchronize. Reconstruct
  host in-service concurrency from [s,c), not claimed GPU-kernel overlap. Peak must
  not exceed C, and >100-frame tests with C>1 must show peak>1 (detect complete
  serialization). Record peak/mean; no requirement to keep C busy when demand is low.
- Warm-up: unchanged 30 actual-frame inferences per worker, stored phase=warmup,
  excluded from active metrics. Verify ready queue empty and enqueue/start counters
  zero before t0. Active phase has no carried warm-up backlog.
- Drain: stop source arrivals at 60 s (10 s smoke), complete admitted work, require
  natural EOS for full 60-s sources and clean pipeline NULL/worker shutdown.
  No new arrivals during drain and no drain samples in queue-stability regression.

Audit basis: current Gate runner and unchanged scripts/local/profile_local_e2e.py,
scripts/common/rtdetr_preprocess.py, scripts/concurrency/local_concurrency_tensorrt.py,
scripts/local/local_latency_breakdown_metrics.py. All exact hashes are frozen below.
V1 source/report snapshots: protocol_v1_snapshot.tar.gz, SHA256
70be92ac91f21210600ee7cc4133632c288f6d90dd58eda84f76c032e25f1619.
V1 original plan and all original run artifacts remain byte-for-byte untouched.

## 2. Frozen experiment design (unchanged by smoke outcomes)

Worktree /home/ainet/research/thor-mec-rate-dvfs-gate, branch rate-dvfs-gate.
MAXN fixed; do not change nvpmodel/governor/CPU/NVD/EMC/fan/thermal/network settings.
No jetson_clocks. Reuse verified RT-DETR Warehouse v1.0.2 canonical FP16 B1 engine,
CUDA Graph OFF, existing NVIDIA GStreamer decode and preprocessing (resize640x360,
zero pad640x640, RGB FP32 /255 NCHW). Canonical engine SHA256:
9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff.
Paths, verified video hashes and ffprobe observations are reused verbatim below.
No engine build or new dependencies. Source: 1920x1080 H.264, 30 FPS, 1800 frames.

K7/C4: r=21,24,27,30 FPS/stream; all streams equal r; source remains30 FPS.
K6/C2: r=30 only. No extra K or C adaptation. Phase accumulator starts at0 for
 each stream; on every decoded source frame acc+=r; admit if acc>=30 and subtract30.
No random or post-admission dropping; no queue caps/forced drops.

GPU GPC states LOW=945, MID=1260, HIGH=1575 MHz; supported available min54 MHz,
default allowed range315–1575 MHz. Pin min=max=target with safe write order in
/sys/class/devfreq/gpu-gpc-0. Restore min315/max1575 MHz after every run, including
exceptions/signals where possible. Actual cur_freq is recorded; idle0 is retained
and not treated alone as a failure. Prior switching observation13–57 ms is reused.

Per run active60 s plus drain. Primary36 runs (12 conditions x3); K6 sanity9
(3 frequencies x3). Exact previously balanced order is reused with fresh V2 IDs:
each primary repeat contains all12 conditions and is followed by3 K6 states;
frequency/rate positions rotate across repeats. No outcome-dependent reordering.
Smokes: K7/C4/r30/HIGH10 s, then K7/C4/r21/LOW10 s. Both require integrity VALID
and pipeline audit PASS. Their preparation-plan full text is retained in their
manifests so final freeze does not lose the plan referenced by smoke SHA256.

## 3. Integrity and hardware status are separate

integrity_status VALID/INVALID concerns only measurement integrity: crashes,
source failure, corrupt/missing trace, accounting/timestamp corruption, sysfs
write/pin failure, restore failure, shutdown, or inability to continue normally.
Every run preserves failure reasons. No automatic retry. An ordinary INVALID run
is retained and the next planned condition runs; fewer than2 valid repetitions
makes a condition INCONCLUSIVE. Recovery/replacement is a separate post-campaign
decision. A demonstrated pipeline bottleneck/implementation error stops Gate work
as PIPELINE_AUDIT_FAIL; an unrecoverable restored-range error prevents safe continuation.

hardware_status CLEAN iff OC3_delta=0; PROTECTION_LIMITED iff OC3_delta>0.
Counters before warm-up and after cleanup cover the entire run and all raw
samples are retained. OC3 and actual clock limitations DO NOT invalidate or
abort a run: finish60 s, drain and proceed. Pin bounds must still be correct.
Non-target actual clock observations are diagnostics, including their fraction;
no exact-clock-equality exclusion is applied. Every active second needs at least
one nonzero actual-frequency observation; missing readback is missing evidence.

V1 P01 is excluded only as PROTOCOL_V1_ABORT_ON_OC3 in the V2 aggregate index.
Its original INVALID status/failure files are historical and never rewritten.
V1 smokes remain historical PROTOCOL_V1_SMOKE and are not V2 evidence.

## 4. Measurements and classification

Power source unchanged: instantaneous first tegrastats VDD_GPU mW channel /1000,
GPU rail scope. GPU temperature gpu@C; OC3 soctherm_oc/oc3_event_cnt. Sampling100 ms,
monotonic host receive timestamp, preserve raw line and actual/requested clocks,
min/max. Do not claim exact internal sensor acquisition time or apply lag/model
corrections. Required trace brackets active endpoints, is monotonic/finite, has
no active gap>0.5 s; otherwise INVALID. Integrate measured power piecewise-linearly
with bracketed endpoint interpolation. E_run is active-only; average power=E/T.
E_frame=E_run/active completed frames only for queue-stable runs.

Primary R_k counts completions in [t0,t0+60s), eta_k=R_k/30. Report aggregate,
min/mean and all per-stream rates. Count source/admission/ready separately.
Per-frame data preserve a,m,r,s,c and source PTS; Q only r→s. Exact continuous-time
uniform least-squares slope of the step queue in t30..60s (smoke last5s, diagnostic
only). QUEUE_STABLE iff aggregate slope<=0.5 frames/s AND every stream<=0.2,
no cap saturation/forced drop and integrity VALID. Negative slope permitted.
OC3 does not invalidate stability. Report mean/p50/p95/p99 latency/service/wait
including drain completions as separately labeled descriptive statistics.

A condition needs>=2 integrity-valid planned repetitions. All valid repetitions
must agree on stability; mixed is INCONCLUSIVE, no majority vote. Numerical cells
are means of valid run metrics; condition median power is median of valid per-run
active average power. Every invalid/clean/protected count remains explicit.

ADMISSION_GATE: K7 same frequency, some higher r UNSTABLE and lower r STABLE;
best stable condition completed throughput >=95% of maximum observed condition
completed throughput at that frequency. Require all four rate cells interpretable
for its maximum comparison; use condition means and do not cherry-pick repeats.

FREQUENCY_CAPACITY_GATE: r_star(s)=highest stable tested r. PASS only if
r_star(HIGH)-r_star(LOW)>=3. No stable LOW point means boundary below tested grid,
not an invented r_star=0; unresolved boundary is INCONCLUSIVE. Protection-limited
runs remain empirical MAXN capacity evidence.

ENERGY_OPPORTUNITY_GATE: compare every lower/higher frequency pair at same K/C/r
where both stable, using K7 and K6. PASS if absolute completed throughput difference
/HIGHER-frequency throughput<=2%, lower-frequency median power<=90% higher, and
direction is consistent across>=2 matched repeat indices: each paired lower power
is lower and paired throughput is within2%. Report E_frame direction for each pair;
no three-parameter model fit. Matching by preassigned repeat prevents selective
pairing; all available valid matched repetitions must satisfy consistency.

Final requires PIPELINE_AUDIT_PASS plus all three control Gates PASS, with planned
campaign complete. Clear contradictory complete relevant evidence gives specific
FAIL; insufficient/mixed evidence gives INCONCLUSIVE. OC3 itself is never FAIL.
Report condition CLEAN/PROTECTION_LIMITED counts and OC3 occurrence rate over
integrity-valid repetitions; preserve invalid counts separately.

## 5. Outputs and exclusions

Each fresh RDVG_V2_* directory contains only manifest.json, per_frame.csv.gz,
power_trace.csv.gz, summary.json, stderr.log. Manifest records protocol_version2,
V2 plan SHA256, source hashes, current environment and restoration. Summaries
include rates, per-stream R/eta/g_Q, pipeline diagnostics, both status axes.
No queue_trace.csv; reconstruct from per-frame data. Only aggregate_summary.csv,
operating_map.csv, gate_verdict.md, final_git_status.txt updated at campaign level;
V1 versions were losslessly archived before replacement. No run artifact overwrite.
Temporary analysis stays /tmp. No new docs directory, workload/controller/energy fit.

## 6. Exact execution configuration

```json
{
  "inputs": [
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0000.mp4",
      "sha256": "7a56955a524e8454ba63df4878a1634fba6f8f59a6136fce9b7a35c2b54a8caa",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0001.mp4",
      "sha256": "bf1bb1fd71a811cfdab83bdad01c0c4cf426124f3e7e6635a77bbdc23f68cb45",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0002.mp4",
      "sha256": "29bc455831e1b80210307405601a4b33fbe00430eea8839b9c8ffd3eccfd526a",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0003.mp4",
      "sha256": "7deacc1aa539bb999ea16c0f656f52695b6fb034e6269bd80e670c090023766c",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0004.mp4",
      "sha256": "57934396f19a0b777da07c6171985bf861f546d42c2c0203b1a6f972a9c3a210",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0005.mp4",
      "sha256": "87d37341d65464f48d1d028f63b80279d302bf341d429d73df9bf55353bd1632",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0006.mp4",
      "sha256": "175816231eced5e215d1733640a65757ad9c0429b3c846966342d142aed54b1a",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    }
  ],
  "source_sha256": {
    "scripts/rate_dvfs_gate/gpu_frequency.py": "549b959aef4ad4d4033641cea852b6ca4d05e187cf203047c301eb2a8cc3d82b",
    "scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py": "20d25859abbc783db15dd3351dc150a69705591a3a0ec363051ffffa0c437068",
    "scripts/rate_dvfs_gate/run_rate_dvfs_gate.py": "d2cc553f439c27d196f96e34838b1a8d13a41d3a6f500d081d6e10e0ad1b46f5",
    "scripts/local/profile_local_e2e.py": "aa9ec99381e6936f843a0e1e0cf3b3cc7beb93778748d0a3fb34b9d9be2084dd",
    "scripts/common/rtdetr_preprocess.py": "48f510234b84e52db3fa7f102279fe778c9c929b80d71e6a34cf684f5a4f7d1e",
    "scripts/concurrency/local_concurrency_tensorrt.py": "863cdd468d8565efdf2a82435e667f9fce837d7d2013ff61ab4ab8fafa8ba140",
    "scripts/local/local_latency_breakdown_metrics.py": "4225d57739c29d18aef0e9e2d75bf4fc20f2407ffc50b603bcf8b8902aa08cce"
  },
  "smoke": [
    {
      "run_id": "RDVG_V2_20260919_SMOKE01",
      "kind": "smoke",
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 10
    },
    {
      "run_id": "RDVG_V2_20260919_SMOKE02",
      "kind": "smoke",
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 10
    }
  ],
  "order": [
    {
      "run_id": "RDVG_V2_20260919_P01",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P02",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P03",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P04",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P05",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P06",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P07",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P08",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P09",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P10",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P11",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P12",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S01",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S02",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S03",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P13",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P14",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P15",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P16",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P17",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P18",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P19",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P20",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P21",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P22",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P23",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P24",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S04",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S05",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S06",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P25",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P26",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P27",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P28",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P29",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P30",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P31",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P32",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P33",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P34",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P35",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_P36",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S07",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S08",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_V2_20260919_S09",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    }
  ],
  "protocol_version": 2,
  "freeze_status": "BLOCKED_SMOKE_PROCESS_EXIT",
  "pipeline_audit_result": "FAIL",
  "prepared_at_utc": "2026-09-19T11:44:22.490830+00:00",
  "process_outcome_annotations": {
    "RDVG_V2_20260919_SMOKE01": {
      "nonzero_exit_observed": true,
      "returncode": null,
      "reason": "NONZERO_PROCESS_EXIT_AFTER_SUMMARY: supervisor took its nonzero-returncode branch; numeric returncode was not persisted by that revision. Pre-exit VALID summary is not authoritative evidence of clean process shutdown."
    },
    "RDVG_V2_20260919_SMOKE02": {
      "nonzero_exit_observed": false,
      "returncode": 0,
      "reason": "Supervisor did not take nonzero branch and completed campaign; no retry."
    }
  },
  "post_smoke_source_sha256": {
    "scripts/rate_dvfs_gate/run_rate_dvfs_gate.py": "a4788ced032a11f4a521a6bbb1aa916848b613bdce388b04175500f6fea5d419",
    "scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py": "bee1a91e6a032bded7ca000ec2fbbee1aeb13d97f06a8fa5242969a18f4df9e7",
    "scripts/rate_dvfs_gate/gpu_frequency.py": "549b959aef4ad4d4033641cea852b6ca4d05e187cf203047c301eb2a8cc3d82b"
  }
}
```


## Protocol Amendment — Unified Backlog B(t)

This user-authorized amendment supersedes the earlier ready-queue definition and source-lag abort rule above. The preceding V2 text is preserved verbatim; its original SHA256 and archived copy are recorded below. No V3 plan is created.

Reason: historical RDVG_V2_20260919_P02 at K7/C4/r24/945 MHz was aborted by the old source-lag rule (scheduled 12600, decoded 12242, admitted/ready/started/completed 9785). Preserve its artifacts and exclude it from amended primary evidence with exclusion_reason=OLD_PROTOCOL_ABORT_ON_SOURCE_LAG. All amended runs use new IDs, including this condition. All prior runs remain historical and excluded from the amended matrix.

Primary state: B(t) = count of logically admitted source frames by t minus inference completions by t. Decode waiting, preprocessing, ready waiting and GPU execution all contribute until completion. There is one shared system backlog. Per-stream R_k and eta_k=R_k/30 remain measured; per-stream queue slopes are not primary stability criteria.

Logical arrivals are frame_index/30 on each stream, 1800 source frames in 60 s. Admission uses the unchanged deterministic phase accumulator, equivalently floor((n+1)*r/30)>floor(n*r/30). Admission timestamps equal the scheduled logical arrivals; actual scheduler observation is recorded separately. Decoder progress cannot reduce logical source or admission counts. Decode continues for skipped frames, which do not preprocess or enter inference. All admitted frames are drained after the active interval, with no new logical arrivals. Missing frames after drain, unexpected EOS, decoder/pipeline crashes or corrupt accounting remain real integrity errors.

Source/decode/preprocess lag never aborts or invalidates a run by itself. Stage timestamps and scheduled-minus-decoded, admitted-minus-ready, ready-minus-started, started-minus-completed counts remain diagnostic. Existing stage-lag diagnostics annotate supply_status=NORMAL or FRONTEND_LIMITED; FRONTEND_LIMITED is not INVALID. A stalled process unable to complete still has the pre-existing drain/EOS watchdog; it is not an active source-lag budget. Genuine integrity failures are preserved and the next planned run proceeds, without automatic retries. Restoration failure blocks further clock-dependent execution.

Stability: exact continuous-time OLS slope g_B over active t=30..60 s; stable iff integrity is VALID, g_B<=0.5 frames/s, and no cap saturation/forced drop. Negative slopes are allowed. For diagnostic 10-s smoke only, use the last 5 s. Drain never contributes to primary slope, throughput, power or energy. The aggregate numerical threshold is unchanged; the former per-stream ready-queue slope criterion is superseded by the explicitly authorized single-backlog definition.

Grid and run count are unchanged: K7/C4 r={21,24,27,30} at {945,1260,1575} MHz, three repetitions (36); followed by K6/C2 r30 at the same frequencies, three repetitions (9). Each primary/sanity active interval is 60 s. Reuse the prior balanced order within these phases exactly, as enumerated below. No new K/C/admission/frequency points or repeats. Both 10-s amendment smokes must exit 0 and pass source/admission/ready/completion accounting, drain, B>=0 and B-after-drain=0, power trace and restore before primary. Smoke A is r30/HIGH; B is r24/LOW. Both use K7/C4.

MAXN remains fixed, B=1, CUDA Graph OFF, canonical engine/preprocessing/decode/workers unchanged. Independent TensorRT contexts/CUDA streams/private buffers and existing queue accounting are reused. Warm-up is separate and queues are empty before measurement. Governor, CPU/NVD/EMC are unchanged. GPC min=max=requested per run, safe write order; restore min315/max1575 MHz. The previously verified frequency capability and engine provenance are reused, not reprofiled.

Power remains measured VDD_GPU rail power from tegrastats at 100 ms, with GPU temperature, actual sysfs GPC frequency and OC3 count. Integrate power over active time only; energy/frame is reported only for stable conditions. Actual frequency is distinct from requested bounds. OC3=0 means CLEAN; OC3>0 means PROTECTION_LIMITED and is not an invalidation/abort, including actual clock protection behavior. Integrity and hardware status remain separate; child PID/actual returncode/signal/times and lifecycle checkpoints are retained, with final validity decided only after process exit.

Gate numeric criteria are unchanged: ADMISSION_GATE requires a higher-to-lower-r unstable-to-stable transition at a frequency with best stable throughput >=95% of that frequency's maximum observed throughput. FREQUENCY_CAPACITY_GATE requires r_star(HIGH)-r_star(LOW)>=3 FPS/stream; r_star is the highest stable tested admission, and an unobserved boundary is unknown, not extrapolated. ENERGY_OPPORTUNITY_GATE compares stable equal K/C/r between frequencies: throughput difference <=2%, lower median per-run average power <=90% of higher, and consistent direction in matched repetitions (at least two). Report energy/frame direction too. At least two integrity-valid repetitions per condition; disagreement in stability is MIXED/INCONCLUSIVE. Invalid repetitions are retained, not retried automatically. No thresholds are changed after amended results.

Interpret capacities as whole Local SYSTEM capacity. FRONTEND_LIMITED is SYSTEM_CAPACITY_LIMITED_BY_FRONTEND evidence, not a claim that the GPU alone failed the offered FPS. A frequency-dependent stable boundary is SYSTEM_CAPACITY_GPU_SENSITIVE evidence. No energy model fitting, C sweep, controller, Edge or new optimization is implemented.

Output policy remains five files per run (manifest.json, per_frame.csv.gz, power_trace.csv.gz, summary.json, stderr.log) and canonical aggregate_summary.csv, operating_map.csv, gate_verdict.md. Historical root reports are archived before canonical regeneration. No stage/queue CSV is added. Frozen source hashes and this amended plan SHA256 are recorded in every new run manifest. The single GPU-free lag fixture below is explicitly synthetic and is not performance evidence.

Frozen executable configuration and fixture result:

```json
{
  "freeze_status": "FROZEN_UNIFIED_BACKLOG",
  "protocol_version": 2,
  "protocol_amendment": "UNIFIED_BACKLOG_B",
  "frozen_at_utc": "2026-09-19T12:29:30.484136+00:00",
  "prior_v2_plan_sha256": "4e4479312df2acd469b402074862a3f458f06e9db338e4674d889c5971476938",
  "prior_record_archive": "pre_backlog_amendment_snapshot.tar.gz",
  "inputs": [
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0000.mp4",
      "sha256": "7a56955a524e8454ba63df4878a1634fba6f8f59a6136fce9b7a35c2b54a8caa",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0001.mp4",
      "sha256": "bf1bb1fd71a811cfdab83bdad01c0c4cf426124f3e7e6635a77bbdc23f68cb45",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0002.mp4",
      "sha256": "29bc455831e1b80210307405601a4b33fbe00430eea8839b9c8ffd3eccfd526a",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0003.mp4",
      "sha256": "7deacc1aa539bb999ea16c0f656f52695b6fb034e6269bd80e670c090023766c",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0004.mp4",
      "sha256": "57934396f19a0b777da07c6171985bf861f546d42c2c0203b1a6f972a9c3a210",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0005.mp4",
      "sha256": "87d37341d65464f48d1d028f63b80279d302bf341d429d73df9bf55353bd1632",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    },
    {
      "path": "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/W027_Camera_0006.mp4",
      "sha256": "175816231eced5e215d1733640a65757ad9c0429b3c846966342d142aed54b1a",
      "ffprobe": {
        "programs": [],
        "stream_groups": [],
        "streams": [
          {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "duration": "60.000000",
            "nb_frames": "1800"
          }
        ]
      }
    }
  ],
  "source_sha256": {
    "scripts/rate_dvfs_gate/gpu_frequency.py": "549b959aef4ad4d4033641cea852b6ca4d05e187cf203047c301eb2a8cc3d82b",
    "scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py": "724e981fe6a74ebfb788dbe587d23f47ad7904351f5b8e9ad42ec31595919d6f",
    "scripts/rate_dvfs_gate/run_rate_dvfs_gate.py": "290db909f9570b321c4d4340f10b17fe31c4239cf5e475a426d2e92ec6a3ac7c",
    "scripts/local/profile_local_e2e.py": "aa9ec99381e6936f843a0e1e0cf3b3cc7beb93778748d0a3fb34b9d9be2084dd",
    "scripts/common/rtdetr_preprocess.py": "48f510234b84e52db3fa7f102279fe778c9c929b80d71e6a34cf684f5a4f7d1e",
    "scripts/concurrency/local_concurrency_tensorrt.py": "863cdd468d8565efdf2a82435e667f9fce837d7d2013ff61ab4ab8fafa8ba140",
    "scripts/local/local_latency_breakdown_metrics.py": "4225d57739c29d18aef0e9e2d75bf4fc20f2407ffc50b603bcf8b8902aa08cce"
  },
  "smoke": [
    {
      "run_id": "RDVG_B_20260919_SMOKE_A",
      "kind": "smoke",
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 10
    },
    {
      "run_id": "RDVG_B_20260919_SMOKE_B",
      "kind": "smoke",
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 10
    }
  ],
  "order": [
    {
      "run_id": "RDVG_B_20260919_P01",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P02",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P03",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P04",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P05",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P06",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P07",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P08",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P09",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P10",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P11",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P12",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P13",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P14",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P15",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P16",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P17",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P18",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P19",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P20",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P21",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P22",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P23",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P24",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P25",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P26",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P27",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P28",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P29",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P30",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P31",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P32",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P33",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P34",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P35",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_P36",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S01",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S02",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S03",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S04",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S05",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S06",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S07",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S08",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_B_20260919_S09",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    }
  ],
  "fixture": {
    "provenance": "synthetic fixture only; not GPU evidence",
    "result": "PASS",
    "integrity_status": "VALID",
    "supply_status": "FRONTEND_LIMITED",
    "logical_admitted": 10080,
    "g_B": 55.99949684149165,
    "backlog_at_active_end": 3360,
    "backlog_after_drain": 0,
    "stage_diagnostics": {
      "scheduled": 12600,
      "decoded": 8400,
      "admitted": 10080,
      "ready": 6720,
      "started": 6720,
      "completed": 6720,
      "scheduled_minus_decoded": 4200,
      "admitted_minus_ready": 3360,
      "ready_minus_started": 0,
      "started_minus_completed": 0
    },
    "source_lag_abort": false
  }
}
```
