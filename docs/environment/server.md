# RTX 5070 Ti Edge Server Environment

Audit date: 2026-09-08

This document records the edge-server environment established for
Thor-to-edge TensorRT inference experiments.

## 1. Host Platform

- Hostname: `CY415AINET`
- Host operating system: Windows 11 version 25H2
- OS build: `26200.9168`
- Edition reported locally: Pro
- Host architecture: x86-64

During the audit, the Windows registry `ProductName` field reported
`Windows 10 Pro`, while `DisplayVersion` was `25H2` and the build was
`26200.9168`.

Microsoft's Windows release information identifies build 26200 as
Windows 11 version 25H2. Therefore, the build/version pair is used as
the authoritative OS identification for this experimental environment.

## 2. WSL Environment

- WSL version: `2.7.13.0`
- WSL2: enabled
- Distribution: Ubuntu 24.04.4 LTS
- Linux architecture: `x86_64`
- Python: `3.12.3`

Python virtual environment:

- Path:
  `~/research/thor-mec-inference/venv`
- `venv/` is excluded from Git.

WSL networking mode:

- `mirrored`

Configured in:

`C:\Users\gusdn\.wslconfig`

with:

    [wsl2]
    networkingMode=mirrored

## 3. GPU

- GPU: NVIDIA GeForce RTX 5070 Ti
- Reported GPU memory: `16,303 MiB`
- Approximate nominal VRAM class: 16 GB
- Windows NVIDIA driver: `595.95`
- WSL NVIDIA-SMI component observed: `595.61`
- Driver-reported CUDA compatibility: `13.2`
- Compute capability: `12.0`
- SM count reported by TensorRT: `70`
- GPU power cap observed: `300 W`

The RTX 5070 Ti is also used by the Windows host display environment.
Windows-side GPU activity and memory consumption must therefore be
controlled or recorded during formal performance experiments.

## 4. CUDA

Installed server CUDA environment:

- CUDA SDK: `13.2.2`
- CUDA package: `cuda-toolkit-13-2 13.2.2-1`
- NVCC: `13.2.86`
- CUDA path: `/usr/local/cuda-13.2`

This matches the CUDA SDK and NVCC versions used on the Thor.

## 5. TensorRT

Native TensorRT environment:

- TensorRT: `10.16.1.11`
- Package build: `10.16.1.11-1+cuda13.2`
- `trtexec`: `/usr/bin/trtexec`

Python virtual environment:

- Python: `3.12.3`
- TensorRT Python version: `10.16.1.11`
- TensorRT Builder creation test: PASS

TensorRT 10.16.1.11 was intentionally selected instead of the newer
TensorRT 11.x packages.

The Thor uses TensorRT 10.16.2.10. The Ubuntu 24.04 x86-64 NVIDIA
repository did not provide that exact Jetson TensorRT patch release,
while TensorRT 10.16.1.11 was available with CUDA 13.2.

The server therefore uses the closest available TensorRT 10.16 release
while keeping CUDA 13.2.2 identical across both platforms. This reduces
software-stack differences between local and edge inference.

## 6. Model

The server uses the same ONNX model as the Thor.

Model:

- RT-DETR Warehouse v1.0.2
- Input type: FP32
- Input layout: NCHW
- Input shape: `1x3x640x640`

ONNX:

- File: `rtdetr_warehouse_v1.0.2.fp16.onnx`
- Size: `87,890,438` bytes
- SHA256:
  `0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267`

The ONNX SHA256 was independently verified on both Thor and server and
was identical.

## 7. Server TensorRT Engine

RTX 5070 Ti B=1 engine:

- File:
  `server/models/rtdetr_warehouse_v1.0.2.fp16.b1.engine`
- Size: `90,662,748` bytes
- SHA256:
  `c94050f1969bca2fef9622c14fd9e307277ba26b0630bf5a669a980a8bad75e9`

Build configuration:

- TensorRT: 10.16.1
- GPU: RTX 5070 Ti
- Input shape:
  `MIN=OPT=MAX=1x3x640x640`
- `--fp16` enabled
- Network precision reported by TensorRT:
  `FP32+FP16`
- Input binding: FP32
- Outputs: FP32
- CUDA Graph was not enabled during the trtexec build/smoke procedures.
- Engine build inference phase was skipped with `--skipInference`.

Build result:

- PASS

The server and Thor TensorRT engine binaries are intentionally different.
Each engine is built specifically for its GPU/platform.

## 8. Server Inference Validation

Random-input execution smoke:

- Engine deserialization: PASS
- Execution context creation: PASS
- One actual GPU inference: PASS
- `pred_logits` shape: `1x300x7`
- `pred_boxes` shape: `1x300x4`

Actual warehouse-input execution:

- Input tensor was copied from the preserved Thor correctness artifact.
- Input SHA256:
  `c51c95a17ba7a102b8f898406aedf0385900357a6593fdde55d4668bf6f73e93`
- Actual server inference: PASS
- Output tensors were finite and had the expected shapes.

## 9. Cross-Platform Correctness Diagnostic

The preserved Thor reference output and the server output were compared
using the same actual warehouse input tensor.

Raw output comparison showed numerical differences between platforms,
which is expected to some extent because the GPU architectures and
TensorRT patch versions differ.

A detection-level diagnostic was therefore also performed using sigmoid
class scores and class-consistent IoU matching.

This sweep was a correctness diagnostic only. It does not define the
production confidence threshold.

At score >= 0.5:

- Thor detections: 11
- Server detections: 11
- Same-class matched detections: 11 / 11
- IoU >= 0.50: 11 / 11
- IoU >= 0.75: 11 / 11
- Mean matched IoU: `0.992775`
- Mean matched score difference: `0.008387`
- Maximum matched score difference: `0.025092`

At score >= 0.7:

- Thor detections: 4
- Server detections: 4
- Same-class matched detections: 4 / 4
- IoU >= 0.75: 4 / 4
- Mean matched IoU: `0.996041`

At score >= 0.3:

- Thor detections: 71
- Server detections: 72
- Same-class matched pairs: 71
- IoU >= 0.50: 70
- IoU >= 0.75: 70
- Mean matched IoU: `0.969456`

These results support the use of the server engine for subsequent
end-to-end integration testing.

## 10. Network Configuration

Thor:

- Address: `192.168.0.189`

Server / mirrored WSL:

- Address: `192.168.0.7`

Both devices were observed on:

- `192.168.0.0/24`

WSL2 originally used NAT networking. External Thor-to-WSL access did not
work in that configuration.

WSL was therefore configured to use mirrored networking.

Hyper-V firewall rule:

- Name: `WSL-Thor-5000`
- Display name: `WSL Thor TCP 5000`
- Direction: inbound
- Protocol: TCP
- Local port: `5000`
- Allowed remote address: `192.168.0.189`
- Action: Allow
- Enabled: True
- Enforcement status: OK

Connectivity validation:

- Thor -> Server TCP connection on port 5000: PASS
- HTTP request from Thor to `192.168.0.7:5000`: PASS
- HTTP response: `200 OK`

Physical negotiated network link speed:

- Not yet measured.
- No 1 GbE / 2.5 GbE / 10 GbE value is currently claimed.

An observed SCP application throughput must not be interpreted as the
physical negotiated link speed.

## 11. Timing Warning

One TensorRT correctness smoke reported:

- Engine deserialization time: `-6.40558 s`

A negative duration is physically invalid and indicates a wall-clock or
timestamp anomaly.

The root cause has not yet been established.

Therefore:

- No latency or throughput values from that correctness smoke are treated
  as performance measurements.
- Formal server and E2E instrumentation must use monotonic clocks.
- Timing behavior must be validated before formal performance experiments.

## 12. Repository

Repository:

- `HyeonWooJang726/thor-mec-inference`

Local server path:

- `~/research/thor-mec-inference`

Server-specific TensorRT engines and ONNX artifacts remain excluded from
Git by the repository `.gitignore`.

The environment documentation itself is tracked in Git.
