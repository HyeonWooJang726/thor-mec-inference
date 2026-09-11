# Targeted bounded termination stress

PASS: C2-K7 5/5, C4-K7 2/2, C7-K7 2/2. All 56,700 frames complete; no watchdog, retry or error. Source joins and actual NULL pipeline shutdown confirmed. These runs are not C-selection performance results.

| C | run | frames | bounded contract | EOS observed (stream 0..6) | missing bus EOS streams |
|---|---|---:|---|---|---|
| 2 | run01 | 6300 | PASS | [True, True, True, False, True, True, True] | [3] |
| 2 | run02 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 2 | run03 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 2 | run04 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 2 | run05 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 4 | run01 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 4 | run02 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 7 | run01 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |
| 7 | run02 | 6300 | PASS | [True, True, True, True, True, True, True] | [] |

Missing EOS is an observation, independently preserved. Bounded PASS does not assert EOS delivery, and does not resolve the original Camera_0004 missing-EOS root cause (UNKNOWN).
