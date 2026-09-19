# C robustness / offline execution configuration Gate — frozen plan

Worktree: /home/ainet/research/thor-mec-rate-dvfs-gate. Branch: rate-dvfs-gate. No new branch/worktree. Existing rate-DVFS results, raw data, reports, plans and source files are read-only references and remain unchanged. This is an explicitly authorized new C configuration experiment, not Dynamic-C.

Operating points: A=K6/r30/180 FPS/1260 MHz; B=K7/r27/189 FPS/1260 MHz; C=K7/r30/210 FPS/1575 MHz. C={1,2,4}, three repetitions each, total 27 fresh primary runs. Existing matching cells are reference-only and never pooled with the new repetitions.

Execution reuses the frozen rate-DVFS run_one pipeline, supervisor, summary calculation and gpu_frequency helper. A bounded in-memory AST adapter changes only the initial TensorRT context count from 2 to min(C,2), maps the two capability reads to historical read-only metadata, and maps two plan reads to this plan. The existing append of workers 2..C-1 is retained for C4. Five adapted nodes are verified explicitly (2 capability, 2 plan, 1 constructor); the historical source is never rewritten. Source/admission/preprocess/ready queue/inference/timestamp/telemetry/cleanup code otherwise remains identical. The supervisor launches this wrapper, annotates operating_point/configured_C and finalizes status only after actual child exit. On abnormal child exit the parent attempts default frequency restoration while retaining INVALID status; an unrecoverable frequency-control block precludes further GPU execution. Other individual invalid runs are retained and the next planned run proceeds without retry.

Independent contexts, CUDA streams and private pinned/device buffers per worker; B=1, FP16 canonical RT-DETR, CUDA Graph OFF. Canonical engine path/hash/provenance and all source video paths/hashes are below. The existing 1920x1080 H.264 30-FPS files have 1800 frames; videos and engine are not rebuilt or reprofiled. Existing GStreamer decode, BGR→RGB/resize640x360/pad640/FP32 normalization/NCHW preprocessing are unchanged.

MAXN fixed. GPC min=max=requested (1260 or1575 MHz) throughout each run, using the existing safe write order. Restore min315/max1575 MHz after each run. No governor/CPU/NVD/EMC/nvpmodel changes; no jetson_clocks. Actual GPC clock and requested bounds are logged separately; prior active clock capability is reused without a new microcheck.

Each stream's logical source timeline is 30 FPS independent of decoder progress. Admission is deterministic by logical frame index; only admitted frames preprocess. Primary B(t)=cumulative logical admissions minus completions, including all unfinished stages. There is one primary backlog; internal stage counts remain diagnostic. Source/decode/ready lag never reduces logical admission counts or aborts by itself, and is annotated FRONTEND_LIMITED. Such measurements describe the complete Local system, not GPU-only capacity.

Warm-up: 30 inferences per context with the existing actual first decoded input; excluded from measurements. Verify empty queue/accounting before active phase. Each primary active interval is60s, followed by drain without new logical arrivals. Primary throughput, power, energy and slope exclude drain. Full-source EOS/accounting must pass. Existing bounded drain/lifecycle watchdogs catch inability to finish, not ordinary under-delivery.

Telemetry: tegrastats 100ms, instantaneous VDD_GPU rail W, gpu temperature, actual GPC cur_freq, requested min/max, and soctherm OC3 counter. Trapezoidal active energy integral with interval endpoints interpolated between bracketing telemetry samples; missing/gapped traces follow the unchanged integrity checks. Stable energy/frame=active energy/active completions. OC3>0 means PROTECTION_LIMITED, never invalid/abort by itself; zero means CLEAN. Frequency deviations attributable to hardware protection remain observations, while actual sysfs pin/write or restore failures are integrity errors.

Integrity failures include pipeline/source crash, unexpected EOS/corruption, accounting/timestamp corruption, missing/corrupt trace, frequency control/restore failure, system shutdown, or nonzero process exit. Preserve five artifacts and exact child PID/returncode/signal/timestamps and lifecycle flags. No automatic retry. Conditions with fewer than two valid repetitions are INCONCLUSIVE. With at least two valid reps, unanimous stability determines STABLE/UNSTABLE; disagreement is MIXED and configuration interpretation is INCONCLUSIVE. OC3 and frontend limitation do not exclude valid repetitions.

Stability is unchanged: exact continuous-time OLS g_B over active t30..60s <=0.5 frame/s, integrity VALID, no forced drop/cap saturation. Negative slopes are allowed. Ten-second smoke uses the existing last5s diagnostic slope but increasing B itself does not fail smoke.

Preflight: one GPU-free check of the actual adapted context initialization verifies C1/2/4 creates worker IDs [0], [0,1], [0,1,2,3]. This is parameterization verification only, not a simulated performance result. Then exactly one10s smoke, point B/C1: configuredC1 and actual peak<=1 (observed peak must be1 to establish execution), process exit0, complete active/drain, B>=0 and drain B=0, source/admission/completion accounting, power trace and restore PASS. OC3/backlog growth are permitted. Primary requires this smoke PASS.

The exact order below is frozen before smoke/primary. A three-repeat Latin rotation balances point and C: every (point,C) appears once per repeat and across repeats occupies each early/middle/late block and each within-block position once. No deliberate cooldown or new control variable is added. Natural setup/warmup/drain costs remain unchanged. No post-result order or repeat changes.

Comparisons use the nine new-campaign condition means (valid reps only), retaining per-stream FPS vectors and all per-repeat measurements. SERVICE_EQUIVALENT requires both conditions STABLE and abs(Ra-Rb)/max(Ra,Rb)<=1%. This symmetric1% denominator is fixed before measurement. Among these pairs compare mean power, energy/frame and protection counts; report repeat direction consistency.

Material effect descriptions: (A) stable versus unstable at equal point; (B) completed throughput max/min-1>=5%; (C) service-equivalent power or energy saving1-min/max>=5%; (D) report repeated protection contrasts, including all matched repeats CLEAN versus PROTECTION_LIMITED and the actual OC3 counts. No invented universal numeric OC3 threshold. Differences below these criteria and repeat variability remain visible; no significance or theorem is claimed.

Descriptive configuration decision order is fixed: if data/stability are insufficient or conflicting, INCONCLUSIVE. If all C are stable and no material A/B/C/repeated clean-vs-protected contrast exists, C_EFFECT_SMALL. Otherwise compute the non-dominated stable configurations at each point: within1% equivalent service, a dominates b if mean power, energy/frame and mean OC3 are all no greater and at least one lower. This is an empirical partial ordering, not fitted optimization or statistical significance. If a common non-dominated stable C exists at all three points, STATIC_C_SUFFICIENT; choose the lowest such C as a simple offline tie break. If there is no common C but each point has one unambiguous non-dominated stable C, OFFLINE_C_MAP_SUFFICIENT. Otherwise C_COUPLING_MATERIAL_BUT_UNRESOLVED. Report frontier trade-offs and repetition consistency; no arbitrary weights resolve them. Any static/offline conclusion applies only to these three fixed points and does not prove dynamic-trace robustness.

Answer whether mu(s,C) changes materially through completion/B/power, not by ready-queue waiting alone; retain r_k(t),s(t) as proposed runtime actions if an offline configuration is supported. No Dynamic-C, controller, new workload/frequency/admission sweep, fitting, Edge or Lyapunov implementation.

Output: exactly manifest.json, per_frame.csv.gz, power_trace.csv.gz, summary.json, stderr.log per CRG run. Root EXPERIMENT_PLAN.md, aggregate_summary.csv, c_configuration_table.csv, gate_verdict.md, final_git_status.txt. No additional stage CSV. All new manifests record this full plan SHA256 and frozen source hashes; old artifacts remain byte-identical.

```json
{
  "freeze_status": "FROZEN_C_ROBUSTNESS",
  "frozen_at_utc": "2026-09-19T13:54:41.602158+00:00",
  "worktree": "/home/ainet/research/thor-mec-rate-dvfs-gate",
  "branch": "rate-dvfs-gate",
  "operating_points": [
    {
      "name": "A",
      "K": 6,
      "r": 30,
      "MHz": 1260,
      "frequency": "MID"
    },
    {
      "name": "B",
      "K": 7,
      "r": 27,
      "MHz": 1260,
      "frequency": "MID"
    },
    {
      "name": "C",
      "K": 7,
      "r": 30,
      "MHz": 1575,
      "frequency": "HIGH"
    }
  ],
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
    "scripts/local/local_latency_breakdown_metrics.py": "4225d57739c29d18aef0e9e2d75bf4fc20f2407ffc50b603bcf8b8902aa08cce",
    "scripts/c_robustness_gate/analyze_c_robustness_gate.py": "4fa7e8d59056ee3f89572c736d7c8dc3e9642a16f61acaa5f6ca774d1ab93046",
    "scripts/c_robustness_gate/run_c_robustness_gate.py": "c3bcffacecb9f0e7edb819f78875aabace6f1763d0f05bc1800dd7a1a6aeebd6"
  },
  "smoke": [
    {
      "run_id": "CRG_20260919_SMOKE",
      "kind": "smoke",
      "operating_point": "B",
      "K": 7,
      "C": 1,
      "r": 27,
      "frequency": "MID",
      "seconds": 10
    }
  ],
  "order": [
    {
      "run_id": "CRG_20260919_P01",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 1,
      "K": 6,
      "C": 1,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P02",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 1,
      "K": 7,
      "C": 2,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P03",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P04",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 1,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P05",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 1,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P06",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 1,
      "K": 7,
      "C": 1,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P07",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 1,
      "K": 6,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P08",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 1,
      "K": 7,
      "C": 1,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P09",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 1,
      "K": 7,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P10",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P11",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 2,
      "K": 7,
      "C": 1,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P12",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 2,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P13",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 2,
      "K": 7,
      "C": 1,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P14",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 2,
      "K": 7,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P15",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 2,
      "K": 6,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P16",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 2,
      "K": 7,
      "C": 2,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P17",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 2,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P18",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 2,
      "K": 6,
      "C": 1,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P19",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 3,
      "K": 7,
      "C": 2,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P20",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 3,
      "K": 6,
      "C": 4,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P21",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 3,
      "K": 7,
      "C": 1,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P22",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P23",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 3,
      "K": 6,
      "C": 1,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P24",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 3,
      "K": 7,
      "C": 2,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P25",
      "kind": "primary",
      "operating_point": "C",
      "repeat": 3,
      "K": 7,
      "C": 1,
      "r": 30,
      "frequency": "HIGH",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P26",
      "kind": "primary",
      "operating_point": "A",
      "repeat": 3,
      "K": 6,
      "C": 2,
      "r": 30,
      "frequency": "MID",
      "seconds": 60
    },
    {
      "run_id": "CRG_20260919_P27",
      "kind": "primary",
      "operating_point": "B",
      "repeat": 3,
      "K": 7,
      "C": 4,
      "r": 27,
      "frequency": "MID",
      "seconds": 60
    }
  ],
  "historical_reference": [
    {
      "operating_point": "A",
      "C": 2,
      "run_ids": [
        "RDVG_B_20260919_S02",
        "RDVG_B_20260919_S04",
        "RDVG_B_20260919_S09"
      ]
    },
    {
      "operating_point": "B",
      "C": 4,
      "run_ids": [
        "RDVG_B_20260919_P03",
        "RDVG_B_20260919_P14",
        "RDVG_B_20260919_P25"
      ]
    },
    {
      "operating_point": "C",
      "C": 4,
      "run_ids": [
        "RDVG_B_20260919_P04",
        "RDVG_B_20260919_P15",
        "RDVG_B_20260919_P26"
      ]
    }
  ],
  "historical_plan_sha256": "412198d20ec2b83a1778da3a2db420b8f0162085e8987e8bd4daee75e3db004c",
  "frequency_capability_reference": {
    "path": "results/rate_dvfs_gate/frequency_capability.json",
    "sha256": "931cffb1ebbe9b2c9115134e1ea017123920b22aa608c2618b4ccb228cf9a4f3",
    "status": "FREQUENCY_CONTROL_PASS"
  },
  "engine_provenance": {
    "status": "PASS",
    "engine_path": "/home/ainet/research/thor-mec-rate-dvfs-gate/models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine",
    "resolved_path": "/home/ainet/research/thor-mec-inference/models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine",
    "sha256": "9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff",
    "expected_sha256": "9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff",
    "evidence": "/home/ainet/research/thor-mec-rate-dvfs-gate/results/local_concurrency_formal_full/replacements/c1/k2/replacement01/metadata.json"
  },
  "offline_parameterization_check": {
    "result": "PASS",
    "provenance": "GPU-free mock constructor check of adapted initialization statements",
    "configured_C_to_worker_ids": {
      "1": [
        0
      ],
      "2": [
        0,
        1
      ],
      "4": [
        0,
        1,
        2,
        3
      ]
    }
  }
}
```
