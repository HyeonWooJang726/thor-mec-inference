# Recovery 001 — frozen continuation, no redesign

Original campaign and original smoke campaign row remain HALTED / FAIL. This recovery does not amend that history.

1. The original FIXED_C4 GPU acquisition completed with actual exit 0 and 780/780 frames.
2. The original summary failed after acquisition because `expected_frames` occurred in both `**row` and an explicit keyword.
3. Reproduced the exact failing analyzer path on original raw CSV/events with writes prohibited.
4. Original source is preserved. A recovery-only analyzer copy validates trace/row/runtime metadata/manifest/termination expected counts, selects the trace count as the canonical value, and writes it once.
5. Original raw replay, all policy/trace/duration CPU fixtures, invalid expected-count fixtures, failure validator, success/failure/HALT bookkeeping and full 30-row report path passed without GPU. Synthetic fixtures are regression evidence only, never measured data.
6. Reuse original FIXED_C4 as integration evidence only. Execute original frozen runtime at its original path for the previously unattempted lookup smoke, then precisely the existing 30-row primary order.
7. All new GPU raw directories are previously unused original manifest acquisition paths under the experiment root. Recovery state, report and ledger are here. Historical status/log/raw/forensic records are not written.
8. Hold original campaign lock without truncation and a separate recovery lock. Persistent child processes use dedicated sessions, actual wait/exit accounting, 420-s parent timeout, no retry. Any failure HALTs. Primary requires lookup LIVE_END_TO_END_PASS and repeated freeze/environment audit.

Unchanged: P=4; policies C2/C4/current-K lookup; Trace A/B; 30 FPS exact integer arrivals; B=1; engine; source mapping; preprocessing; a/b/r/s/c; FIFO and admission; cap update; 60-s primary; deadline 1/30 s; windows; sequence/seed; engineering thresholds; warm-up 0 and deliberate cooldown 0 inherited from original plan. No power/clock/dependency changes.

Original runtime/core and imported measurement-critical sources remain byte-identical. The postprocessing/report copies only change canonical expected-count validation and recovery output/input routing. New bookkeeping/launcher manage recovery state only. Freeze is checked before/after each acquisition and before primary. No code change is permitted after the freeze.

Engineering gate remains both traces Δ2 and Δ4 ≥0.5 pp, each positive in at least 4/5 rounds. Comparison is only against predeclared C2 and C4; no claim about all possible fixed caps. Original first smoke and new smoke are excluded from primary performance analysis.

No commit/push; no Formal or figure changes.
