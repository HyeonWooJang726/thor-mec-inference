# Grid03-mini figure captions and reproduction

## Figure A — Temporal placement structure

Temporally concentrated placement and temporally dispersed placement at the
same L224/E16 average split (eight 30-FPS streams; 240 FPS in total). Each cell
shows one source-slot assignment, with Local in gray and Edge in hatched blue.
Concentrated aligns Edge assignments across streams; Dispersed shifts the
assignment phases using the frozen phase vector [0, 2, 4, 6, 8, 9, 11, 13].
The traces show per-slot Local and Edge assignment counts, m_L[n] and m_E[n].
Both schedules contain 224 Local and 16 Edge assignments per 30 source slots,
including two Edge assignments per stream. The peak Edge assignment count is
eight for Concentrated and one for Dispersed. Same average split, different
temporal load shapes. Source timestamps are unchanged; assignment phases do
not imply a change in physical camera capture timing or GPU start times.

Figure A displays the frozen assignment schedule, not measured execution times
or a causal explanation of performance.

## Figure B — Measured timely service (main, threshold-independent)

Measured worst-stream timely-inference ratio (TIR) for temporally concentrated
placement and temporally dispersed placement at four Local/Edge splits.
Small markers show all three measured repeats per condition; their horizontal
offsets are for visibility only. Large markers and lines show arithmetic means;
connecting lines are visual guides between tested points. The top axis gives
the corresponding Edge assigned rate. All 24 measured runs are VALID and use
C_L=3, C_E=1, B=1, eight 30-FPS streams, and a 100-ms relative deadline.
The main figure has no feasibility threshold line: it presents the measured
TIR values and run-to-run variation. Dispersed has higher worst-stream TIR at
L208/E32, L216/E24, and L224/E16; the measured ordering reverses at L232/E8.
This observation establishes neither global optimality nor a causal mechanism.

## Figure C — Path-wise temporal effect

Difference in timely FPS, Dispersed minus Concentrated, decomposed into Local,
Edge, and Total contributions at each tested split. Bars show the stored mean
of three paired repeat differences; small markers show all paired differences.
The Edge contribution is positive across the tested points, while the Local
contribution becomes negative at L232/E8. The measured path-wise contributions
have opposite signs at L232/E8. A causal mechanism is not established.

## Scope and terminology

Grid03-mini is not a strict one-factor reproduction of Grid02. Local concurrency
changes from two to three, and dispersed assignment phases use the preregistered
period-aware construction. Configuration A, the mini-grid runtime, and final
Configuration B are distinct; their repeats are not pooled. Internal assignment
labels are translated only for display. No claim is made about an optimal
placement, online-controller necessity or sufficiency, hysteresis, state-dependent
capacity, or a GPU/Edge queue causal mechanism.

All figures use Liberation Sans with text at least 8.5 pt at the native 7.16-inch
two-column width. Insert at the native width to retain the font-size guarantee.
PDF and SVG are vector-only; PNG is 600 dpi. Paths use hatches, line styles,
and/or marker shapes in addition to color, for grayscale legibility.

## Reproduction

```bash
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py
```

Optional screening-target variant:

```bash
python3 -B scripts/figures/plot_grid03_mini_paper_figures.py --eta 0.99
```

Use `--output-dir <fresh-directory>` for another rendering; existing artifacts
are not overwritten. `FIGURE_DATA.json` records the exact plotted coordinates
and their CSV keys. `VALIDATION.json` records input/output SHA-256, cross-file
checks, native figure sizes, fonts, and output checks. No raw trace, analysis,
plan, preregistration, runtime, or Git index is modified.

## Optional Figure B — Screening-target variant

Same measured data as the main Figure B, with the separately requested
screening operating target, eta = 0.99. The dashed reference is labeled
“Screening target η = 0.99”. It is an operational screening target and is
not a universal system requirement or a real-time standard. The main Figure B
remains threshold-independent.
