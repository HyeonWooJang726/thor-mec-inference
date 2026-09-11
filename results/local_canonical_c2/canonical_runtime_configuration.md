# Canonical static Local runtime

C=2 is used as the fixed static runtime configuration for the canonical Local baseline.

C denotes the number of independent frame-level TensorRT inference requests allowed to remain outstanding. It is neither the number of video sources K, CUDA threads, nor TensorRT auxiliary streams. A single inference already uses GPU parallelism. Host service overlap establishes concurrent outstanding requests; GPU kernel overlap is not directly measured.

The historical serialized runtime used one worker, one execution context, default CUDA stream 0, synchronous H2D, execute_async_v3(0), cudaDeviceSynchronize, synchronous D2H and reusable buffers. Its results remain historical serialized-runtime characterization. They are not pooled with the new baseline or treated as an implementation-identical concurrency comparison.

The current runtime shares one canonical engine and uses B=1, C=2: two workers, two independently owned IExecutionContext objects, two nonblocking submission CUDA streams, two independent device input/output buffer sets and two independent pinned host input/output staging sets. Each request uses async H2D, execute_async_v3, async D2H and synchronization of its own stream. No cudaDeviceSynchronize is used. Engine-owned auxiliary streams are separate from the two application submission streams.

Engine: models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine; SHA256 9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff. Static input 1x3x640x640. Engine and runtime source hashes are checked before every run.

Fixed environment: MAXN, DVFS unlocked, jetson_clocks OFF, CUDA Graph OFF. Read-only environment preflight is required for every run. No power or clock setting is changed. No warm-up, exclusion, drop or deliberate cooldown: this explicit user workload protocol takes precedence over the repository's general warm-up guideline.

Full-source workload: 30 FPS phase-aligned logical arrivals, all 1800 frames of each 60-second source, stream i maps to W027_Camera_000i.mp4 for i=0..K-1 in the audited Warehouse_027 dataset. Each source must report actual natural bus EOS, exact IDs, clean worker join and confirmed pipeline NULL shutdown. Bounded completion cannot replace EOS. All accepted work must drain; errors/watchdog/nonzero exit stop the campaign without retry.

Raw integer timestamps: a logical arrival; b front-end start; r ready enqueue complete; s service start; c host output available after D2H/stream synchronization. Waiting counts r <= t < s, active counts s <= t < c. Candidate deadline miss is (c-a)*30 > 1000000000; this is not a final application SLA.

Selection evidence (separate campaigns, not pooled):

- Identical-path C1/C2 formal control demonstrated the effect of allowing independent requests on application queue/deadline behavior.
- C1–7 trtexec micro-probe measured engine-level aggregate throughput; it did not establish application QoS or service latency.
- C2/C4/C7 actual-stream bounded screening showed higher C can reduce queues while increasing inference-service contention; C7 did not justify its cost.
- C2/C4 60-second full-source validation favored C2 for K5/K6 deadline QoS and C4 for K7 overload degradation, a load-dependent trade-off.
- C3/C5/C6 one-run full-source sanity screening did not provide sufficient evidence to adopt another fixed candidate.

The user therefore selected C2 for this static baseline. This is a tested fixed configuration, not a universal best concurrency claim. Future C_t in {2,4} control remains a separate research action and is not implemented here.

The fork changes only CLI/output metadata, campaign orchestration and validation allowing idle configured capacity at low K. Runtime AST checks preserve arrival, front-end, inference, pipeline and termination functions. TensorRT implementation, termination validator and raw metric implementation are byte-identical to the previous full-source runner. All old scripts/results remain read-only.

35-run rotation and exact commands are in formal_plan.json. Analysis and figures require independent replay of all 252000 raw frames after the complete campaign. The old serialized period-service-sum versus period comparison is prohibited: overlapping C2 service intervals would be double-counted.
