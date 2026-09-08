# NVIDIA Jetson AGX Thor Environment

Audit date: 2026-09-08

This document records the frozen local-device environment used for the
validated local inference experiments.

## 1. Platform

- Device: NVIDIA Jetson AGX Thor Developer Kit
- Hostname: `thor`
- Architecture: `aarch64`
- Operating system: Ubuntu 24.04.4 LTS
- Kernel: `6.8.12-1021-tegra`
- JetPack: `7.2.1-b49`
- Jetson Linux / L4T: `R39.2.1`
- CPU cores online: 14 (`0-13`)
- Observed usable memory: 122 GiB

The device uses the NVIDIA JetPack 7.2.1 software stack for Jetson AGX Thor.

## 2. GPU and Power Configuration

- GPU: NVIDIA Thor
- NVIDIA driver: `595.78`
- Power mode: `MAXN`
- nvpmodel ID: `0`
- CPU governor observed during audit: `schedutil`
- DVFS: enabled
- `jetson_clocks` maximum-clock locking was not used for the validated
  local experiments.

The local experimental configuration was intentionally operated with DVFS
enabled rather than with CPU/GPU/EMC clocks permanently locked to their
maximum values.

## 3. CUDA and TensorRT

- CUDA SDK: `13.2.2`
- NVCC: `13.2.86`
- CUDA runtime component observed: `13.2.86`
- TensorRT: `10.16.2.10`
- TensorRT package build: `10.16.2.10-1+cuda13.2`
- `trtexec`: `/usr/bin/trtexec`
- cuDNN CUDA-13 package version observed: `9.20.0.46-1`

cuDNN was present as part of the NVIDIA/JetPack software environment; it
was not separately selected as an experimental variable.

## 4. Python and Media Software

- Python: `3.12.3`
- Python executable: `/usr/bin/python3`
- NumPy: `1.26.4`
- OpenCV: `4.8.0`
- GStreamer: `1.24.2`
- `nvv4l2decoder`: available
- `nvvidconv`: available

## 5. Model and Preprocessing

Model:

- RT-DETR Warehouse v1.0.2
- ONNX input tensor: FP32 NCHW
- Input shape: `1x3x640x640`

Validated preprocessing path:

1. Actual 1920x1080 BGR frame
2. Resize to 640x360
3. Top-aligned zero padding to 640x640
4. BGR to RGB conversion
5. Divide pixel values by 255
6. FP32 NCHW conversion
7. TensorRT inference

ONNX model:

- File: `rtdetr_warehouse_v1.0.2.fp16.onnx`
- Size: `87,890,438` bytes
- SHA256:
  `0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267`

## 6. Canonical Local TensorRT Engine

Canonical B=1 engine:

- File: `rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`
- TensorRT execution configuration: FP16-enabled
- Batch size: 1
- Input shape: `1x3x640x640`
- SHA256:
  `9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff`

TensorRT engine binaries are platform-specific. This engine is the
canonical local Thor engine and must not be used on the edge server.

## 7. Network

Observed Thor LAN address during the server integration setup:

- Thor: `192.168.0.189`
- Network: `192.168.0.0/24`

The Thor successfully established a TCP/HTTP connection to the edge server
at `192.168.0.7:5000`.

Physical negotiated link speed:

- Not yet measured and therefore not reported.

An observed SCP transfer rate must not be interpreted as the physical
negotiated link speed.

## 8. Git Freeze Point

Repository:

- `HyeonWooJang726/thor-mec-inference`

Audit state:

- Branch: `main`
- Commit:
  `d37db42f5496509fe4c384fb2c50330499b9410d`
- Local HEAD, cached `origin/main`, and GitHub `main` matched at audit time.
- Working tree was clean.

## 9. Environment Freeze Policy

The validated local environment is frozen.

Unless explicitly required by a later experiment, do not change:

- JetPack
- Jetson Linux / L4T
- CUDA
- TensorRT
- NVIDIA driver
- Linux kernel
- power mode
- clock policy
- canonical local TensorRT engine

Do not run `apt upgrade` or `apt autoremove` as part of the validated
local experimental workflow.
