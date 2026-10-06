Inputs: assignment_table.csv, assignment_manifest.json, paper/figure_data_section3.csv, paper/validation_section3.json (exact paths/SHA in validation_fig1.json).
Outputs: fig1_e16.pdf/png, figure1_data.csv, plot_fig1.py, validation_fig1.json, README_fig1.txt; regenerate with python3 -B paper/figures/campaign2/plot_fig1.py --replace-generated.
Deleted obsolete Figure 1 outputs: see deleted_files_precheck/deleted_files in validation_fig1.json; Figure 2 and shared sources retained.
Interpretation: identical aggregate and per-stream counts, different temporal assignment positions, different observed stream-wise timely service; no causal or algorithm claim.
Metric: all Edge-assigned frames remain in the denominator, including pre-submission expiration; means and observed ranges use five measured runs.
