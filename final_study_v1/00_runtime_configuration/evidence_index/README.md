# Runtime configuration evidence index

Canonical paths and SHA-256 values for the C_L calibration history and Edge robustness evidence. These are links to existing files; no raw results are duplicated.

| Experiment | Plan SHA-256 | Preregistration SHA-256 | Selection/robustness output |
| --- | --- | --- | --- |
| local_inflight_calibration03 | `c41736aab6f2c7379cafe90b4c3ca6d0ec8ff811c3651f70c13a0fd05c9fb874` | `085d74af9b3e4f64ad12a34b0633953f2c62481218f75207aa505264f07ec204` | `results/timely_capacity_campaign/v2_2/local_inflight_calibration03/analysis01/c2_justification.json` (`64427a5a8e6cdeb1abf88bcf5d8c4979098c1e2b08b8f65139c8e968a22feea9`) |
| local_inflight_calibration04 | `e77653e2825c31840bba3353a820316d65d2c684b780c2c88394ae1fa6b499c0` | `f1589f1335b874e77866fd4388ec225a4ed62672a9147d3dc77a7adf79bdb00a` | `results/timely_capacity_campaign/v2_2/local_inflight_calibration04/analysis01/extension_verdict.json` (`e1dfb76857cc747b2d1b69de9606c837295951e4725a39638cae11c4defb1e2a`) |
| local_inflight_calibration05 | `8988f28531c0f3faa56a8e9e0c7dbc1386877b7df95e1ee5185a184590f36f57` | `5a2e603677e990e8658328a766519d8ce722d060aabeb9b7fbf2f4f701ee47cc` | `results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/final_C_selection.json` (`532def87ce6ecbe57288ad3cbf5de226eebec5ff3c871f1a08f4012f63112f1a`) |
| edge_inflight_robustness02 | `096de1830f6389f1c537664c001102659e4773465882d7499608d133515d5b5d` | `833d3148633f9a4a9e03154cb7cf3c67d0c4a1c84617c031b74dd4426aa5d1e8` | `results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/edge_C_robustness.json` (`f4834afe2c0edf3ac621f8c6974d0a138d67a488d237f0205496a04cdb606073`) |

Calibration05 alone formally selects C_L=3. Robustness02's historical TIR verdict is `EDGE_C_REPEAT_AMBIGUOUS` and C_E selected is null; its queue evidence supports a separate prospective C_E=2 choice before Grid03.

Provenance note: Calibration04/05 inherited a generic `plan.runtime.C_L` template string that names the older C1–C4 range. Their frozen session plans and actual `analysis01/per_run.csv` identify the tested sets as C3–C5 and C3–C6, respectively. This index uses those measured per-run cardinalities and leaves the historical plans untouched.
