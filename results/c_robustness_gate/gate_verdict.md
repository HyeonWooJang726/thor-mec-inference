# C robustness / offline configuration Gate

Overall: **STATIC_C_SUFFICIENT**

Primary completed/finalized: 27/27; integrity VALID 27, INVALID 0. Smoke excluded from primary statistics.
Hardware counts: CLEAN 21, PROTECTION_LIMITED 6. FRONTEND_LIMITED 0.

B(t)=logical admissions minus completions, all local stages included. g_B uses only active t=30..60 s. Stable requires g_B<=0.5 frames/s, valid integrity and no cap/drop. Drain is accounting only. All valid raw summaries replay identically. VDD_GPU is measured rail power; J/frame is reported only for stable conditions. Condition values are means of valid repetitions (minimum two), peak concurrency is the maximum observed peak. OC3_delta in CSV is the per-run mean; OC3_total and per-repeat counts are separate.

| Point | C | completed FPS | min/mean stream FPS | g_B | stability | GPU W | active J | J/frame | peak/mean concurrency | OC3 by repeat | frontend limited | valid/attempted |
|---|---:|---:|---|---:|---|---:|---:|---:|---|---|---:|---|
| A | 1 | 175.6111 | 29.2556/29.2685 | 4.2250 | UNSTABLE | 40.1594 | 2409.5641 | N/A | 1/0.9944 | [0, 0, 0] | 0 | 3/3 |
| A | 2 | 179.9667 | 29.9833/29.9944 | 0.0023 | STABLE | 41.4240 | 2485.4429 | 0.2302 | 2/1.7527 | [0, 0, 0] | 0 | 3/3 |
| A | 4 | 179.9444 | 29.9833/29.9907 | 0.0002 | STABLE | 41.8279 | 2509.6716 | 0.2324 | 4/2.9344 | [0, 0, 0] | 0 | 3/3 |
| B | 1 | 165.6056 | 23.6500/23.6579 | 23.5861 | UNSTABLE | 38.5591 | 2313.5457 | N/A | 1/0.9942 | [0, 0, 0] | 0 | 3/3 |
| B | 2 | 188.7889 | 26.9667/26.9698 | 0.0134 | STABLE | 43.0786 | 2584.7143 | 0.2282 | 2/1.9558 | [0, 0, 0] | 0 | 3/3 |
| B | 4 | 188.9056 | 26.9833/26.9865 | 0.0032 | STABLE | 43.2665 | 2595.9918 | 0.2290 | 4/3.4287 | [0, 0, 0] | 0 | 3/3 |
| C | 1 | 185.5889 | 26.5056/26.5127 | 24.4272 | UNSTABLE | 46.7063 | 2802.3792 | N/A | 1/0.9945 | [0, 0, 0] | 0 | 3/3 |
| C | 2 | 209.9056 | 29.9778/29.9865 | -0.0032 | STABLE | 52.4192 | 3145.1541 | 0.2497 | 2/1.9238 | [33, 43, 69] | 0 | 3/3 |
| C | 4 | 209.9500 | 29.9833/29.9929 | 0.0006 | STABLE | 52.4308 | 3145.8474 | 0.2497 | 4/3.2429 | [14, 22, 24] | 0 | 3/3 |

Service-equivalent comparisons and material effects (frozen definitions):
- {"operating_point": "A", "C_pair": [1, 2], "service_equivalent": false, "throughput_difference_fraction": 0.024202012718404636, "throughput_gain_fraction": 0.024802277760202385, "power_saving_fraction": 0.030529292545049325, "energy_saving_fraction": null, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [0, 0, 0], "lower_power_C": 1, "power_direction_consistent": true}
- {"operating_point": "A", "C_pair": [1, 4], "service_equivalent": false, "throughput_difference_fraction": 0.024081506637851087, "throughput_gain_fraction": 0.024675735526731968, "power_saving_fraction": 0.039888675861696865, "energy_saving_fraction": null, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [0, 0, 0], "lower_power_C": 1, "power_direction_consistent": true}
- {"operating_point": "A", "C_pair": [2, 4], "service_equivalent": true, "throughput_difference_fraction": 0.00012347965672665257, "throughput_gain_fraction": 0.00012349490583529743, "power_saving_fraction": 0.009654116668690094, "energy_saving_fraction": 0.009777008561368983, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [0, 0, 0], "lower_power_C": 2, "power_direction_consistent": true}
- {"operating_point": "B", "C_pair": [1, 2], "service_equivalent": false, "throughput_difference_fraction": 0.12280030604437646, "throughput_gain_fraction": 0.13999127780200604, "power_saving_fraction": 0.10491241775105198, "energy_saving_fraction": null, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [0, 0, 0], "lower_power_C": 1, "power_direction_consistent": true}
- {"operating_point": "B", "C_pair": [1, 4], "service_equivalent": false, "throughput_difference_fraction": 0.12334205805370106, "throughput_gain_fraction": 0.14069576302458975, "power_saving_fraction": 0.10880086063684202, "energy_saving_fraction": null, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [0, 0, 0], "lower_power_C": 1, "power_direction_consistent": true}
- {"operating_point": "B", "C_pair": [2, 4], "service_equivalent": true, "throughput_difference_fraction": 0.0006175925653617696, "throughput_gain_fraction": 0.0006179742216465556, "power_saving_fraction": 0.004344203810782599, "energy_saving_fraction": 0.0037300263535470224, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [0, 0, 0], "lower_power_C": 2, "power_direction_consistent": false}
- {"operating_point": "C", "C_pair": [1, 2], "service_equivalent": false, "throughput_difference_fraction": 0.11584575073445741, "throughput_gain_fraction": 0.13102436688020136, "power_saving_fraction": 0.10898507806642044, "energy_saving_fraction": null, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": true, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [33, 43, 69], "lower_power_C": 1, "power_direction_consistent": true}
- {"operating_point": "C", "C_pair": [1, 4], "service_equivalent": false, "throughput_difference_fraction": 0.11603291789050305, "throughput_gain_fraction": 0.13126384481829612, "power_saving_fraction": 0.10918146143194829, "energy_saving_fraction": null, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": true, "OC3_by_repeat_a": [0, 0, 0], "OC3_by_repeat_b": [14, 22, 24], "lower_power_C": 1, "power_direction_consistent": true}
- {"operating_point": "C", "C_pair": [2, 4], "service_equivalent": true, "throughput_difference_fraction": 0.00021169061416729208, "throughput_gain_fraction": 0.00021173543657182492, "power_saving_fraction": 0.00022040412645585317, "energy_saving_fraction": 8.955453730918883e-06, "matched_repeats": [1, 2, 3], "repeated_clean_vs_protected": false, "OC3_by_repeat_a": [33, 43, 69], "OC3_by_repeat_b": [14, 22, 24], "lower_power_C": 2, "power_direction_consistent": false}

Material effect flags by point: {"A": {"stable_vs_unstable": true, "throughput_5pct": false, "equivalent_service_cost_5pct": false, "repeated_clean_vs_protected": false}, "B": {"stable_vs_unstable": true, "throughput_5pct": true, "equivalent_service_cost_5pct": false, "repeated_clean_vs_protected": false}, "C": {"stable_vs_unstable": true, "throughput_5pct": true, "equivalent_service_cost_5pct": false, "repeated_clean_vs_protected": true}}

Non-dominated stable C values by point: {"A": [2], "B": [2], "C": [2, 4]}
Offline selection under the frozen descriptive rules: {"static_C": 2}

Dominance is descriptive at these fixed operating points: among stable configurations providing service within 1%, a configuration dominates another if mean power, J/frame and mean OC3 are all no greater and at least one is lower. Differences and repeat consistency are reported; small numerical dominance is not a statistical significance claim. Counts may expose power/protection trade-offs, for which no unmeasured preference or objective weighting is invented.

These three fixed points support keeping C as offline execution configuration and retaining r_k(t), s(t) as the proposed runtime actions. This is conditional evidence within the measured grid, not a proof for dynamic traces or other workloads. No controller or Dynamic-C was implemented.

mu(s,C) interpretation: reported changes are Local system completed capacity at fixed demand/frequency, not ready-queue improvement or a fitted GPU-only service law. FRONTEND_LIMITED and protection behavior remain part of the operating result.

Historical rate-DVFS references (not pooled with the new campaign):
- {"operating_point": "A", "C": 2, "historical_run_ids": ["RDVG_B_20260919_S02", "RDVG_B_20260919_S04", "RDVG_B_20260919_S09"], "historical_completed_fps": 179.9611111111111, "new_completed_fps": 179.96666666666667, "historical_power_W": 41.89362355337388, "new_power_W": 41.42404892731544}
- {"operating_point": "B", "C": 4, "historical_run_ids": ["RDVG_B_20260919_P03", "RDVG_B_20260919_P14", "RDVG_B_20260919_P25"], "historical_completed_fps": 188.92222222222222, "new_completed_fps": 188.90555555555554, "historical_power_W": 43.280537378198844, "new_power_W": 43.266530393253205}
- {"operating_point": "C", "C": 4, "historical_run_ids": ["RDVG_B_20260919_P04", "RDVG_B_20260919_P15", "RDVG_B_20260919_P26"], "historical_completed_fps": 209.92222222222222, "new_completed_fps": 209.95, "historical_power_W": 52.70683765014291, "new_power_W": 52.43079036886589}

Invalid runs retained without automatic retry:
- None.

Concrete answers and interpretation limits:
- Q1: C materially affects sustainable Local processing capacity. All nine C1 primary runs are UNSTABLE; all eighteen C2/C4 runs are STABLE. At fixed point B and C, C1→C2 completion improves by more than 5%; at A the improvement is smaller but changes stability.
  - Point A: C1→C2 completed FPS +2.4802%; C2/C4 service difference 0.0123%; C2 mean power saving relative to C4 0.9654%, energy/frame saving 0.9777%. These small cost differences are below the 5% material-cost criterion.
  - Point B: C1→C2 completed FPS +13.9991%; C2/C4 service difference 0.0618%; C2 mean power saving relative to C4 0.4344%, energy/frame saving 0.3730%. These small cost differences are below the 5% material-cost criterion.
  - Point C: C1→C2 completed FPS +13.1024%; C2/C4 service difference 0.0212%; C2 mean power saving relative to C4 0.0220%, energy/frame saving 0.0009%. These small cost differences are below the 5% material-cost criterion.
- Q2: Lower C is not generally established as an energy advantage at equal service. C1 uses less power but fails the offered demand and is not service-equivalent. C2 versus C4 mean power/energy differences are below 1% at all points. C2 power is lower in all three A repeats, but the direction is not consistent across the B or C repeats; do not claim a robust energy improvement there.
- Protection variation beyond the binary hardware label: at point C both C2 and C4 are PROTECTION_LIMITED in 3/3 repeats. C2 OC3=[33, 43, 69], total 145; C4 OC3=[14, 22, 24], total 60. C4 has fewer events in every matched repeat (58.6207% fewer in total), at essentially the same service and power. This repeated OC3-count contrast is reported descriptively, not hidden by their identical hardware-status labels or promoted to a new numeric criterion.
- Q3: No unique universally best C is established. The frozen condition-mean ordering favors C2 at A/B; point C retains both C2 and C4 as non-dominated because C2 has marginally lower mean power/energy while C4 has substantially fewer OC3 events. Tiny mean cost differences are not evidence that C2 is statistically better.
- Q4: STATIC_C_SUFFICIENT means C2 is a sufficient common offline configuration across these measured points, not that it is uniquely optimal. C4 remains an explicit protection-oriented alternative at point C. This trade-off does not require adding C as a runtime dynamic action on the present evidence. Proposed controller actions can remain r_k(t), s(t), conditional on the tested regimes. No controller is implemented and no configuration in historical experiments is changed.
- The effective service relation mu(s,C) depends materially on choosing C1 versus sufficient concurrency. Within C2/C4, observed service is nearly unchanged at these demands; stable observed service does not estimate their untested saturation capacity. C effects can therefore be absorbed as offline configuration for this Gate rather than inferred as a Dynamic-C contribution.

Final integrity and preservation verification:
- Parameterization fixture PASS; one C1 smoke PASS; 27/27 primary runs PASS integrity and lifecycle. Exact observed peak concurrency equals configured C in all 28 runs including smoke, without exceeding it.
- 324000 logical source frames and 312660 logically admitted/completed frames across primary runs; drain B=0 for every run. No retries, hidden exclusions or added conditions.
- All new runs record plan SHA256 a04ed5ca2b4acec6b8ed90210f47604269adccd6f66c3206b62d06f12432862a; source hashes remain frozen. MAXN remained fixed and GPC default range min315/max1575 MHz is restored.
- All 308 inventoried historical rate-DVFS result/source files remain byte-identical, including all 45-run raw data, prior failed runs, frozen plans and characterization report.
