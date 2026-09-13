# Main manuscript figure: static concurrency response

## 한국어 설명

(a)는 K5·K6·K7의 C=1..8 전체 DMR을 동일한 선형 0–100% 축에서 비교한다. Workload에 따라 관측상 유리한 C가 달라지고, C 증가가 항상 DMR을 개선하지는 않는다. 이는 같은 데이터에서 관측한 static configuration 비교이며, 모든 조건에서 하나의 C가 명확한 winner라는 의미가 아니다. (b)는 K5의 queue waiting과 system-level service time을 함께 보여준다. 강조한 C4–C5 구간에서 queue mean은 2.764→0.482 ms로 감소하고 service mean은 13.969→19.694 ms로 증가한다. 이 동반 변화만으로 DMR 변화의 원인이 입증되지는 않는다. Dynamic-C의 필요성·우월성 또는 실제 개선량을 입증한 그림이 아니다.

## English manuscript caption

**Workload-dependent responses to static application-level request-concurrency caps.** (a) Deadline miss rate (DMR) versus cap C for K=5, 6, and 7 input streams, displayed on a common linear 0–100% scale. Observationally favorable static caps differ with workload, and increasing C does not consistently improve deadline performance. (b) Mean inference-ready queue waiting (s−r) and system-level request service time (c−s) at K=5 share a linear time axis. The shaded C4–C5 interval highlights a concurrent decrease in queue waiting (2.764 to 0.482 ms) and increase in service time (13.969 to 19.694 ms). Points are means of five repeated runs (n=5); error bars are run-level sample standard deviations (ddof=1), not confidence intervals. The same video content is repeated, with 30 FPS offered per active stream for 60 s and a deadline of exactly 1/30 s after logical arrival. All startup and drain frames are retained. Lines connect separate static acquisitions, not dynamic cap transitions or a time sequence. Queue and service changes do not alone establish the cause of DMR changes, nor do these measurements establish the necessity or superiority of Dynamic-C control.

## Data and statistical definitions

- Primary valid5 inclusion is unchanged: 56 conditions, five valid runs each, 280 runs and 2,016,000 frames. K2/C1 uses replacement01 instead of failed original run04; the post-campaign replacement is never treated as original Round 4. The plotted K5–K7 data use their original valid acquisitions.
- Experimental unit: run, not frame. Five repetitions of identical video content measure run-to-run system variability, not five independent workload samples. No outliers or startup frames are excluded.
- Deadline miss: `(c_ns−a_ns)*30 > 1_000_000_000`; DMR = `100*miss_frames/completed_frames`. Queue waiting = s−r; service = c−s. Service is host-observed system-level request time, not isolated GPU kernel time. Queue plus service is not complete local latency.
- All plotted values are computed from the original per-run CSV at stored precision, using `statistics.mean` and `statistics.stdev` (n−1 denominator), then checked against the stored valid5 aggregate. The K5 queue/service values are additionally checked against revision_001 source data. Only displayed text is rounded. The 40 source-data rows retain all five run values, source paths, actual rounds and SHA256 provenance.
- C is an application admission cap on in-flight frame requests, not batch size, stream count K, CUDA thread count, or physical GPU parallelism. Both panels compare fixed-C runs. No smoothing, double y-axis, significance symbols or optimal-cap labels are used. The Formal counterexamples, including DMR increases despite lower mean service, remain valid.
- This focused main figure uses the requested K5–K7 workloads. The unmodified supplementary heatmap in revision_001 retains the full K1–K7 grid on the common 0–100% scale. It is linked, never regenerated. The existing two-panel representative Figure 2 is also preserved.
- Rendering reuses the validated revision_001 K5 queue/service plotting block with the panel relocated. Width: 7.1 inches; embedded TrueType vector PDF and 300 dpi PNG. Fonts ≥8.5 pt; markers and line styles distinguish curves independently of color. The full-scale K5 curve remains visible without an inset.

## Reproduction

Run `python3 make_static_concurrency_motivation.py` with the repository's existing Matplotlib installation. If output files exist, a new unused sibling revision is selected. The script never calls a GPU runtime, profiling tool or prior analysis generator. Matplotlib cache is outside the repository. No raw trace is parsed.

Input SHA256:

- `results/local_concurrency_formal_full/formal_per_run_summary_valid5.csv`: `e7436bcea882fd220207c46b8ace9bd6a237572f6d019b9e2fb1ffbc20d92ecb`
- `results/local_concurrency_formal_full/formal_kc_aggregate_valid5.csv`: `379a6a8db5cba1b7d5c5cf1e9700772e68a3514296c70dabe2455e2718e7c91f`
- `results/local_concurrency_formal_full/analysis_valid5/representative_figures/revision_001/make_representative_figures.py`: `3d75fada5a9a19993e2e21104bf793b3eb2a98ae002e1194b27861482cf43784`
- `results/local_concurrency_formal_full/analysis_valid5/representative_figures/revision_001/figure_source_data.csv`: `0a67fc47fb87f9bc43cedfa66f10af09657b0f446598b147e20e2daa71f97d52`

Preservation check: PASS; 50 protected files, SHA256 mismatches=0. Entire revision_001 preserved. GPU executions=0; commit/push=NO.

Visual validation: the final 300 dpi PNG and an independent PDF rasterization were inspected. At the 7.1-inch page width, text, markers, error bars, panel margins and legends are legible without overlap. The K5 curve is identifiable on the shared scale, so no inset was added. PDF fonts are embedded TrueType. The mean ± SD display describes variability rather than feasible-value bounds or confidence intervals.
