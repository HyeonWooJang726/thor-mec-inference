# BLOCK_B_CONFIRMATION02 preregistration

This document is frozen **before any confirmation workload**. The 30 Grid02 measured runs are exploratory selection evidence only. Grid02's H1 verdict remains `H1_NOT_SUPPORTED`; the new 25 measured runs alone determine C1–C5. No confirmation outcome has been observed.

Confirmation01 was aborted before any workload because the CPU execution-state lifecycle was consumed during setup. No confirmation performance outcome was observed. Confirmation02 preserves the preregistered scientific design unchanged.

Research question: does the empirically selected placement-aware feasible configuration reproduce its stream-level deadline service and same-round advantages in an independent execution namespace?

Selection provenance: recomputed from every Grid02 active per-frame trace and cross-checked against `analysis01/per_run.csv`. At eta=0.99, all five repeats must have `worst_stream_TIR>=0.99`; among such Grid02 configurations, choose the highest Local assigned FPS. A tie at that rate must be reported as `MULTIPLE_CANDIDATES`. The exact recomputation artifact is `GRID02_SELECTION_RECOMPUTE.json` (SHA-256 18f53ff7dcb96418873e36246d50515da21a15a1d8ab7db373d9d90d5240599c). Its sole feasible cell and candidate are `L200S`. Grid02 plan SHA-256 is `ecc6cfc219572ae2754ae3f9f3d8c7e9bcdfed0274c18a951bf459d71a66abe3`. This is exploratory selection, not formal Grid02 superiority.

The previously fixed scalar rule `lambda_L < mu_backlog_lower` is **rejected for candidate selection**: its 197-FPS conservative empirical lower envelope selected no tested rate. `mu_high`, backlog, and carry-over remain secondary descriptive diagnostics and cannot change C1–C5.

## Frozen conditions and controls

Five cells, each five repeats: L216A (216/24), L200A (200/40), L200S (200/40), L208S (208/32), L192S (192/48), where the two rates are Local/Edge FPS. K=8 synchronized streams ×30 FPS =240 source FPS; D=100 ms; measured active 60 s; warm-up L200S 15 s excluded. Local C_L=2, TRT B=1, GPU target 1575 MHz; Edge C_E=1, B=1, CUDA Graph OFF, dynamic batching OFF. Thor CPU seven policies performance/min=max=2601000 kHz during campaign; user restores schedutil/min=972000/max=2601000 kHz before analysis. Model, preprocess, RAW640 payload, protocol, pruning, queue, TensorRT/CUDA order and instrumentation are unchanged from Grid02. Source arrival timestamps remain fixed. Edge mask is the exact Local complement. ALIGNED uses phase zero; STAGGERED uses [0,1,2,3,4,5,6,7]. Minimum post-drain inter-session idle is 10 s. No retry, resume or overwrite.

## Exact 26-session order

Warm-up: `BCONF02_WARMUP_L200_S` (15 s, excluded). Measured 60-s runs, by round:

1. `BCONF02_L216_A1`, `BCONF02_L200_A1`, `BCONF02_L200_S1`, `BCONF02_L208_S1`, `BCONF02_L192_S1`
2. `BCONF02_L200_A2`, `BCONF02_L200_S2`, `BCONF02_L208_S2`, `BCONF02_L192_S2`, `BCONF02_L216_A2`
3. `BCONF02_L200_S3`, `BCONF02_L208_S3`, `BCONF02_L192_S3`, `BCONF02_L216_A3`, `BCONF02_L200_A3`
4. `BCONF02_L208_S4`, `BCONF02_L192_S4`, `BCONF02_L216_A4`, `BCONF02_L200_A4`, `BCONF02_L200_S4`
5. `BCONF02_L192_S5`, `BCONF02_L216_A5`, `BCONF02_L200_A5`, `BCONF02_L200_S5`, `BCONF02_L208_S5`

Each cell occupies each within-round ordinal position once. All comparisons below are same-round. Five-of-five engineering rules are not statistical significance tests.

## Primary rules, frozen at eta=0.99

- C1 L200S feasibility: `worst_stream_TIR(L200S_j)>=0.99` in all five runs → `L200S_FEASIBILITY_CONFIRMED`; otherwise `L200S_FEASIBILITY_NOT_CONFIRMED`.
- C2 temporal placement at L200: every round `TimelyFPS(L200S_j)>TimelyFPS(L200A_j)` **and** `WorstTIR(L200S_j)>=WorstTIR(L200A_j)` → `L200_TEMPORAL_EFFECT_CONFIRMED`; otherwise `L200_TEMPORAL_EFFECT_NOT_CONFIRMED`.
- C3 aggressive baseline: every round `TimelyFPS(L200S_j)>TimelyFPS(L216A_j)` **and** `WorstTIR(L200S_j)>=WorstTIR(L216A_j)` → `L200S_VS_L216A_CONFIRMED`; otherwise `L200S_VS_L216A_NOT_CONFIRMED`.
- C4 max-Local check: if L208S has `worst_stream_TIR>=0.99` in all five runs, `MAX_LOCAL_SELECTION_NOT_CONFIRMED`; otherwise `MAX_LOCAL_SELECTION_CONSISTENT`. This is no superiority claim.
- C5 lower-rate sensitivity: check L192S by the same five-of-five feasibility rule. If L200S and L192S both pass, report 40 versus 48 Edge-assigned FPS, an 8-FPS assignment difference. No equivalence, formal winner, or post-hoc ranking claim.

## Validity and descriptive evidence

Each run must have exact 14,400 source-frame IDs, Local XOR Edge, no duplicates/missing IDs, exact terminal accounting, zero unfinished after drain, GPU frequency restore PASS, Thor CPU pin before/after PASS, Edge protocol/integrity VALID, zero transport errors, and no automatic retry. Warm-up failure blocks measured runs; first measured INVALID stops the campaign. Network/setup/protocol failures are INVALID, never performance failures. CPU restore PASS and Edge raw collection precede analysis.

Descriptive outputs include total timely FPS/TIR, per-stream worst/best/gap, Local/Edge timely FPS and assigned TIR, Local queue/service/GPU stream span/host residual/concurrency, Edge offload wait/request-response/pending/server queue/inference, late/expired counts, OC3/temperature/frequency/CPU evidence, network TX and errors. L208S feasible-run count and timely-FPS spread are reported. An optional post-restore carry-over replay may report B_Q recoveries/HIGH seconds/end B_Q but cannot alter C1–C5. Thor VIN 60-s active-window energy is optional descriptive evidence; it excludes Edge energy and full-run energy, and missing energy does not invalidate service results.
