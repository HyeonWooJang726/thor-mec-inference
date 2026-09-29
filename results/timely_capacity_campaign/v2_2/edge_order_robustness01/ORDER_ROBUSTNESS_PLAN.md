# EDGE_ORDER_ROBUSTNESS01 — preparation only

Frozen plan SHA-256: `233370402d62b9d185710ef664b6a03c730fa3f72a3784fa86fc9ac59710c727`. No session has been run. The K8×30 source, canonical E48 q6 mask, D100, RAW640, C_E=1, B=1, Edge backend/protocol and 30-s measured duration match E48 Confirmation01. Only within-slot submit order changes. Warm-up is E48 STAGGERED for 15 s, excluded from every score.

The exact 16-session sequence is in `session_plan.json`: WARMUP, then BASE1 REV1 ROT1 / REV2 ROT2 BASE2 / ROT3 BASE3 REV3 / BASE4 ROT4 REV4 / ROT5 REV5 BASE5. Each session must drain/clean up before the fixed minimum 10-s idle begins. First INVALID stops all later sessions; no retry, resume or overwrite.

BASE = stream 0..7, REVERSE = 7..0, ROTATE = [(j+i)%8 for i=0..7], where j starts at zero in each run and advances only on E48 ALIGNED active slots. The mask, frame IDs and source timestamps do not change. ROTATE has 180 active slots: each stream×position exposure is 22 or 23, per-stream max-minus-min ≤1. `DISPATCH_ORDER_MANIFEST.json` freezes the matrix.

For each run, G_id = TIR(stream0) − TIR(stream7). Primary engineering verdict is `ORDER_EFFECT_SUPPORTED` only when BASE G_id >0 in 5/5 and REVERSE G_id <0 in 5/5. Round-matched REV−BASE and ROT−BASE for aggregate/worst-stream TIR are descriptive only. Position-level quantities are attributed by request ID; run-level pending and network bytes are not apportioned to positions. Invalid network/protocol setup is not a mechanism failure.

Campaigns remain separate: complete Order, restore CPU, transfer Edge raw, analyze, then and only then begin Block B. Connection instructions: [Thor–Edge runbook](/home/ainet/research/thor-mec-rate-dvfs-gate/docs/testbed/THOR_EDGE_CONNECTION_RUNBOOK.md).
