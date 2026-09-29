# BLOCK_B_GRID01 — preparation only

Frozen plan SHA-256: `ecc6cfc219572ae2754ae3f9f3d8c7e9bcdfed0274c18a951bf459d71a66abe3`. No session has been run. Use the identical frozen V2.2 worker text, C_L=2, TRT B=1, GPU target 1575 MHz, CPU 7-policy 2601000-kHz fixed, K8×30 synchronized RAW640 source, pruning ON, D100. Every source frame goes to exactly one path. Local mask is canonical p27/p26/p25 (L216/L208/L200); STAGGERED is p[(n−k)%30] with phase [0..7]. Edge is the Boolean complement. No frame delay, reorder, hold or separate Edge mask optimization.

Warm-up is 15-s L200E40 STAGGERED, excluded. The 30 measured sessions each last 60 s. `session_plan.json` freezes all five six-condition rounds and 10-s post-drain minimum idle. Each condition has five repeats, compared within round only. Warm-up INVALID stops measured sessions; first measured INVALID stops all later sessions. No retry, resume or overwrite.

The Block-B-only post-drain summary binds the inherited integrity checks to 15 s for warm-up and 60 s for measured runs, with 240 admitted source frames/s and the planned Local/Edge split. It uses a private manifest view for the inherited total-admission field and restores the Local target in the reported summary. The actual run manifest, frozen V2.2 worker, and hot path remain unchanged.

H1: in each of 5 rounds, total timely FPS(L208S) > FPS(L216A) **and** worst-stream TIR(L208S) ≥ TIR(L216A). Both inequalities must hold 5/5 for H1_SUPPORTED. The same-round split and rate contrasts are descriptive; this is not a significance test. Prediction MATCH/MISMATCH is separate from H1, integrity and validity. `mechanism_expectations.json` is frozen before workload.

Prior exact mask matches: L208A/S to Block A pilot02 D100, L216A/L200A to timely scan02 D100. Distributed Edge slot peaks are E24=1, E32=2, E40=2. L208S provenance: pilot02 D100 S TIR 1/1 at 208, highest tested feasible. L200A provenance: scan02 D100 200, highest tested 2/2 feasible. Neither is a global optimum claim.

Energy is Thor VIN input only; Edge energy is excluded. The named first instantaneous `VIN` mW field, 100-ms requested tegrastats sampling and active-window trapezoidal integration are verified. Existing frozen trace coverage ends near active end and does not establish full drain/cleanup E_run_J; `BLOCK_B_ENERGY_SOURCE_MANIFEST.json` records review required. No missing energy value is fabricated.

The offline analyzer reports unavailable VIN integration as an energy-only status; it does not enter H1 or the prediction MATCH rule. The inherited frequency/readback validity checks still require their telemetry, independently of the optional VIN energy calculation.

The frozen source scheduler dispatches stream IDs 0..7 within each slot. Per-stream frontend threads may finish decode/preprocess in a different order before Local ready-queue insertion (`effective_runtime.txt:239-263`), so the analysis labels source dispatch position separately from actual ready-queue/service order. It does not claim that V2.2 forces Local enqueue order or alter that behavior. Edge request IDs retain canonical slot/stream order.

Grid01 ended INVALID at the first warm-up because the inherited post-drain summary rebound to common `campaign_config.decorate`, whose STAGGERED whitelist covers only 22/23/24. Grid02 binds the private summary to the exact frozen Block B mask decorator for 25/26/27; the common module and V2.2 worker remain unchanged. Grid01 remains immutable evidence.
