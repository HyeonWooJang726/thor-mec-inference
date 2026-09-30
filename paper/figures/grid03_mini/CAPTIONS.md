# Grid03-mini figure captions and reproduction

## Figure A — Temporal placement structure

Temporally concentrated placement and temporally dispersed placement at the same
L224/E16 mean split, with K=8 and F=30 FPS per stream. The 30 scheduled source
slots span one second. Each stream is assigned 28 Local frames and two Edge
frames, so both placements have identical total and per-stream assignment counts
(224 Local and 16 Edge). Concentrated aligns Edge assignments across streams;
Dispersed uses the frozen assignment phase vector [0, 2, 4, 6, 8, 9, 11, 13].
The lower step curves show the number of frames assigned to each path in each
source slot, with the same colors and line styles in both panels. A Local
assignment count of zero does not imply GPU idle. Scheduled assignment times
are distinct from actual queue arrivals, socket submissions, and GPU execution
start times. The assignment phases do not change the common source phase or
establish synchronized physical camera capture. This figure describes the
frozen schedule, not measured GPU load or Edge receive times.

## Figure B — Worst-stream timely service

Measured worst-stream TIR at four Local/Edge splits for temporally concentrated
placement and temporally dispersed placement. Markers and asymmetric error bars
show means and observed ranges across three runs: lower=mean-min and
upper=max-mean. All 24 VALID measured runs are included. The ranges are not
confidence intervals or standard errors; zero ranges are not enlarged.
Connecting lines guide the eye between measured operating points and estimate
neither unmeasured performance nor a crossing point. The upper axis reports the
corresponding Edge assigned rate. Runs use C_L=3, C_E=1, B=1, K=8, F=30 FPS,
and D=100 ms. The main figure contains no eta reference line.

## Figure C — Path-wise timely FPS difference

Paired timely FPS difference, Dispersed minus Concentrated, decomposed into
Local, Edge, and Total. Grouped bars show paired means, and asymmetric error
bars show the observed min-max range of three paired-run differences. Each
difference is computed within the same split and repeat before summarization;
the ranges are not obtained by subtracting the two conditions' extrema.
Positive values mean Dispersed provided more timely results; negative values
mean Concentrated provided more. Total=Local+Edge within each paired repeat,
up to floating-point representation. This is a path-wise measured decomposition.
At L232/E8 the Local and Edge contributions have opposite signs. It does not
establish a causal mechanism involving Local relief, GPU idle, or hysteresis.

## Scope and reproduction

Grid03-mini is not a strict one-factor reproduction of Grid02: C_L changes from
two to three, and dispersed assignment phases use the preregistered period-aware
rule. Configuration A, the mini-grid runtime, and final Configuration B are
not pooled. Historical verdicts and screening targets remain unchanged. No claim
is made about global optimality, controller necessity or sufficiency,
state-dependent capacity, or a GPU/Edge queue causal mechanism.

Figures use the installed CPU Cairo renderer, without matplotlib or seaborn.
PDF/SVG contain vector drawing and vector font glyphs; PNG is 600 dpi. Liberation
Sans is used at a minimum 8.5 pt at the native 7.16-inch two-column width. No
font file is copied. The PDF metadata date is fixed solely for reproducible
rendering and is not an experiment date.

```bash
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py --output-dir <fresh-directory>
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py --eta 0.99 --output-dir <fresh-directory>
```

Existing outputs are never overwritten by the generator. VALIDATION.json holds
current mean/min/max coordinates, all input SHA-256, output checksums, and layout
checks. The preexisting FIGURE_DATA.json is retained unchanged as the prior
rendering's coordinate record; its former jitter offsets are not used by this
version. No scientific data, plan, preregistration, or runtime is modified.

## Optional Figure B — Reference variant

The separate eta variant shows the same means and observed ranges, with the
line labeled “Reference: η = 0.99”. At eta=0.99 this is the mini-grid's
preregistered screening target, not a universal standard or a requirement for
all experiments. It does not change the main threshold-independent figure.
