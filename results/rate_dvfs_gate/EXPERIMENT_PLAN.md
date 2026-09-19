# Rate / GPC frequency Gate — FROZEN

Frozen before any smoke or primary result. Engine provenance and active-load
frequency switching have PASS evidence in frequency_capability.json. The earlier
blocked draft is superseded by this plan; no primary outcome has been observed.

## Workspace and inputs

Worktree `/home/ainet/research/thor-mec-rate-dvfs-gate`, branch `rate-dvfs-gate`.
No other worktree is modified. RT-DETR Warehouse v1.0.2, TensorRT FP16, B=1,
CUDA Graph OFF. Engine `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`
is a symlink to the existing main-worktree artifact, never rebuilt.
SHA256 `9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff`
matches formal metadata at
`results/local_concurrency_formal_full/replacements/c1/k2/replacement01/metadata.json`.

The seven exact video paths, current SHA256 values, and ffprobe observations are
in the machine-readable frozen configuration below. Each is H.264, 1920x1080,
30 FPS, 1800 frames, 60 seconds. Stream i maps to video i; K6 uses the first six.

Reuse `build_pipeline` from scripts/local/profile_local_e2e.py, with NVIDIA
GStreamer decode and existing BGR conversion/appsink path. Reuse
scripts/common/rtdetr_preprocess.py: resize 640x360, pad to 640x640, BGR→RGB,
FP32 /255, contiguous NCHW. Reuse ConcurrentTensorRT and ContextWorker from
scripts/concurrency/local_concurrency_tensorrt.py: one shared engine, C independent
contexts, private pinned/device buffers, nonblocking CUDA streams. C4 adds two
instances of the unchanged ContextWorker to the existing C2 factory. Existing
QueueAccounting supplies ready enqueue/service start timestamps. Historical
sources remain unchanged; all relevant source hashes are pinned below.

## Fixed settings and frequency control

MAXN stays fixed. No nvpmodel/governor/CPU/NVD/EMC changes; jetson_clocks is never
invoked. Record before/after environment and CPU/GPU/NVD/EMC governors/bounds.
Source load is 30 FPS/stream; primary K=7/C=4, sanity K=6/C=2. These are workload
configurations, not a dynamic C policy or a universal C(K) rule.

Supported GPC table: 54–1575 MHz, 9 MHz steps. Available minimum 54 MHz differs
from the default allowed minimum 315 MHz. Default allowed range 315–1575 MHz.
Frozen supported targets: LOW=945, MID=1260, HIGH=1575 MHz, exactly 60/80/100% max.
Set `/sys/class/devfreq/gpu-gpc-0/min_freq` and `max_freq` in Hz to the same target;
expand the old range before contraction and verify both endpoints. Read actual
clock from cur_freq during active inference. Idle zero is not a frequency failure.
Restore 315000000/1575000000 on normal exit, exceptions and SIGINT/SIGTERM as far
as process execution permits; verify restored endpoints. Do not alter governor.

Completed microcheck: LOW→MID→HIGH→LOW, 1 second/state, 10 ms polling, at least
three active inference target samples/state, 100 ms tegrastats sampling. Synthetic
zero input is explicitly labeled ONLY for capability; no microcheck throughput
is primary evidence. Every state matched cur_freq, OC3 delta zero, range restored.
Command-to-first-observed delays include host command and polling delay; they
are not isolated hardware switching latency. Tegrastats did not expose a GPC
clock field in the observed lines; actual clock validation uses cur_freq.

## Power and warm-up

Power source: tegrastats instantaneous first VDD_GPU mW field /1000, labeled
GPU rail VDD_GPU power. Do not use VIN or module power as GPU-only power.
GPU temperature: tegrastats gpu@...C. OC3: hwmon with name soctherm_oc,
oc3_event_cnt. Tegrastats interval 100 ms; timestamp each received measurement
using monotonic_ns, alongside actual cur_freq, min/max, requested frequency,
temperature, OC3 and the complete raw line. Host receive timestamps are telemetry
observation times, not exact internal sensor acquisition times. No unmeasured
sensor-lag correction or power calibration model is applied.

Before each run: 30 warm-up inferences per worker at the selected frequency using
the first actual decoded frame from stream 0, repeated. Preserve each warm-up
sample with phase=warmup and stream_id=-1. Reopen all source pipelines from their
start for active arrivals. No warm-up samples enter primary metrics. No deliberate
cooldown or thermal/fan modifications. Record temperature/time order rather than
selecting runs based on outcome.

## Admission, physical queue, measurement and drain

Active interval [t0,t0+60 s) for primary/sanity; [t0,t0+10 s) for each smoke.
Phase-aligned logical arrivals t0+floor(frame_id*1e9/30). Per-stream accumulator
starts at zero, adds r per source frame, admits if >=30 then subtracts 30.
Primary r in {21,24,27,30}; all streams use the same r. Decode and record every
30-FPS source frame, including skips. Never slow playback to the admission rate.
Skip frames never enter inference queues. No random or post-admission dropping.

Admission/enqueue timestamp is sampled by the source scheduler when an admitted
request enters the front-end FIFO. A separate ready timestamp records entry to
the unchanged shared GPU-ready FIFO. Q_k counts ALL admitted requests that have
not started inference, including pending decode/preprocessing. It excludes
in-service work, and is reconstructed from admission and service timestamps;
no queue_trace.csv is written. The shared ready queue remains intact.

Only active-interval completions count toward R_k and R_sum; eta_k=R_k/30.
Count active admitted demand separately. Record min/mean R_k. Arrival/admission
ends at t0+duration; then drain every admitted request with no new arrivals.
Drain is integrity-only. Full 60-second sources require natural EOS on every
stream; smoke is bounded to 300 source frames/stream. Drain watchdog 180 seconds
beyond active duration; any timeout fails the run and preserves incomplete raw
records. Unbounded queues; no queue cap, eviction, forced drop or saturation.

Elapsed timing uses monotonic_ns. Store phase, identity, source PTS, logical
arrival, admission flag, admission/enqueue, front-end start, ready enqueue,
service start, completion, worker, and existing service instrumentation per frame.
Report mean/p50/p95/p99 queue wait, service and latency from raw admitted samples;
these descriptive latency statistics include drain completions and are explicitly
separate from active throughput/energy and stability metrics.

## Queue and validity rules

For primary/sanity use ONLY t=30..60 seconds. Compute continuous-time uniform
least-squares slope of the piecewise-constant Q trajectory, integrating exact
request waiting intervals; event-frequency weighting is not used. Smoke may
report its last 5 seconds descriptively and supplies no primary evidence.
QUEUE_STABLE iff aggregate g_Q <=0.5 frames/s AND every g_Q,k <=0.2 frames/s,
with no queue saturation, overflow or forced drop. Negative slopes are allowed.
These are this Gate's engineering thresholds, not universal stability theorems.

Power trace must bracket active endpoints; integrate piecewise-linear measured
power with trapezoids and interpolate only the bracketed interval boundaries.
No inferred samples replace missing telemetry. Any active trace gap >0.5 s is
invalid. Every active second must have nonzero actual-frequency readback; every
nonzero active readback must equal the requested supported point exactly, and
min/max must equal the target. Idle zeros are retained and excluded from actual
frequency mean; they do not independently establish a mismatch. This finite
sampling does not claim detection of sub-sampling clock excursions.

Any OC3 event across warm-up/active/drain, frequency mismatch, source/pipeline
failure, missing trace, identity/timestamp/count mismatch, forced drop, failed
drain or failed restoration invalidates the run. Stop the campaign at first
invalid run; preserve it, never automatically retry or increase repeats. A later
retry needs a separate ID and documented diagnosed reason. Failed measurements
are never silently excluded from denominators or replaced by synthetic values.

Active E_run=integral P(t) dt and average power=E_run/duration. Only stable valid
runs get E_frame=E_run/active completed frames. Unstable E_frame is null, not a
comparable energy-efficiency statistic.

## Frozen matrix, repeat interpretation and verdict

Primary: K7/C4, 4 rates x 3 frequencies x 3 repeats = 36 runs, 60 s each.
Sanity: K6/C2/r30, 3 frequencies x 3 repeats = 9 runs, 60 s each.
Two smokes first, exactly K7/C4/r30/HIGH then K7/C4/r21/LOW, 10 s each.
Both must be integrity VALID before any primary run. The exact order below
interleaves each 12-condition primary repeat with a 3-frequency sanity block.
Rate positions and frequency sequence rotate across repeats; every primary
repeat contains each condition exactly once. No outcome-dependent reordering.

Condition throughput/power metrics are arithmetic means of the three valid
repeats. A stable condition requires all three stable; unstable requires all
three unstable. Mixed, missing or invalid repeat conditions are INCONCLUSIVE;
no majority vote or selective repeat removal. Raw individual runs remain visible.

ADMISSION_GATE PASS: same frequency, r30 UNSTABLE and a lower-r stable condition
with completed FPS >=95% of r30. FREQUENCY_CAPACITY_GATE PASS: same r LOW
UNSTABLE/HIGH stable, OR the highest observed stable grid point moves upward by
at least 3 FPS/stream from LOW to HIGH. Do not infer a boundary below an entirely
unstable grid or outside the tested grid. ENERGY_OPPORTUNITY_GATE PASS: same-r
LOW/HIGH both stable, absolute throughput difference / HIGH throughput <=2%,
LOW mean power <=90% HIGH. If K7 has no witness, K6 sanity may supply it.

No witness with complete, valid, consistent relevant matrices is FAIL;
insufficient/conflicting evidence is INCONCLUSIVE. A measured witness can support
an individual Gate even if other conditions are incomplete, but final
RATE_DVFS_GATE_PASS additionally requires completion of the planned matrices,
valid consistent repeat classifications, and all three Gates PASS. Explicit
contrary Gates terminate with their specific *_FAIL. No threshold/grid changes.

No controller, Lyapunov/virtual queue, Dynamic-C, batching, resolution/model
changes, networking or energy power-law fitting. Even PASS does not authorize
automatic follow-on profiling or controller implementation.

## Artifacts

Each RDVG run contains only manifest.json, per_frame.csv.gz, power_trace.csv.gz,
summary.json, stderr.log. Preserve failures. Aggregate only aggregate_summary.csv
(one row per run, smoke distinctly labeled) and operating_map.csv (condition
means of primary/sanity, including invalid/incomplete flags). No intermediate
CSV, queue_trace, redundant per-stream/run summary CSV, or new docs directory.
All raw results and engine artifacts remain ignored by existing Git policy.

## Exact frozen execution configuration

```json
{
  "frozen_at_utc": "2026-09-19T11:21:07.451703+00:00",
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
    "scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py": "92e8c7b2970020f6802aee51432155467e11b8a5783c19d4ed97cfbe13b9fe49",
    "scripts/rate_dvfs_gate/run_rate_dvfs_gate.py": "2ed86157bcfcd7dc1e94f0b9c69b5eb4b8f54afb1262d237b44598053876e438",
    "scripts/local/profile_local_e2e.py": "aa9ec99381e6936f843a0e1e0cf3b3cc7beb93778748d0a3fb34b9d9be2084dd",
    "scripts/common/rtdetr_preprocess.py": "48f510234b84e52db3fa7f102279fe778c9c929b80d71e6a34cf684f5a4f7d1e",
    "scripts/concurrency/local_concurrency_tensorrt.py": "863cdd468d8565efdf2a82435e667f9fce837d7d2013ff61ab4ab8fafa8ba140",
    "scripts/local/local_latency_breakdown_metrics.py": "4225d57739c29d18aef0e9e2d75bf4fc20f2407ffc50b603bcf8b8902aa08cce"
  },
  "smoke": [
    {
      "run_id": "RDVG_20260919_SMOKE01",
      "kind": "smoke",
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 10
    },
    {
      "run_id": "RDVG_20260919_SMOKE02",
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
      "run_id": "RDVG_20260919_P01",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P02",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P03",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P04",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P05",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P06",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P07",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P08",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P09",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P10",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P11",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P12",
      "kind": "primary",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S01",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S02",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S03",
      "kind": "sanity",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P13",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P14",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P15",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P16",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P17",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P18",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P19",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P20",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P21",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P22",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P23",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P24",
      "kind": "primary",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S04",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S05",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S06",
      "kind": "sanity",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P25",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P26",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P27",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P28",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P29",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P30",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P31",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P32",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P33",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P34",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P35",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 21,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_P36",
      "kind": "primary",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 24,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S07",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S08",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "LOW",
      "seconds": 60
    },
    {
      "run_id": "RDVG_20260919_S09",
      "kind": "sanity",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    }
  ]
}
```
