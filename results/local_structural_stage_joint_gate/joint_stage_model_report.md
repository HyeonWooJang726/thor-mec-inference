# Joint structural stage model feasibility gate

## Scope and dataset
This gate changes only the old probability factorization, retaining observed training-frame (W,A_start,S) triplets under the same ready-state lookup. No additional feature, model family, smoothing, tuning, GPU acquisition, controller, action or policy replay. All old files remain read-only.

The previous dataset arrays were independently rebuilt from canonical raw and matched exactly: 280 valid runs, K1–7/C1–8, 2,016,000 frames; 1,973,897 ready-on-time evaluated; 42,103 PRE_READY_LATE excluded. Both training and test populations follow the same eligibility rule, including queue-stage-late service observations in training. No startup/outlier removal. K2/C1 replacement remains saved statistical slot4; failed historical run04 is excluded. Slot4 is not original temporal Round4. Dynamic acquisitions are unused.

## B1/P-old reproduction barrier
Reference commit d965452619af7ea103f8b5f4b421fa608a8d8f6e matches startup HEAD and origin/main. Previous extraction/fit/empirical counting code was copied byte-for-byte and compared with that commit. B1 was refitted with original train-only scaling, categorical encoding, L2=0.001 and optimizer settings; P-old distributions were rebuilt. We did not substitute prior predictions for the new computation. Every eligible frame ID, label, backoff ID, support table and probability was checked against the prior files. All five reproduction folds passed before P-joint predictions were generated. Tolerance was frozen at probability atol=rtol=1e-10 and metric absolute difference1e-10. See reproduction_check.json for actual differences and hashes in input_manifest.json.

Reproduced means:
```
{
  "B1": {
    "Brier": 0.1517286090293937,
    "logloss": 0.27300032474675706
  },
  "P-old": {
    "Brier": 0.10511854943821128,
    "logloss": 0.1704050980649347
  }
}
```

## Same state, joint outcomes
At ready, input is K,C,Q,A,b30 only. Q is before target enqueue; A is target-excluded in-flight state immediately before ready. W=s-r, S=c-s and A_start are retained together by training row identity. Test W,S,A_start never condition a prediction. P-old uses empirical W/A_start then an independent conditional service CDF; P-joint uses actual paired W+S from each selected training row. No different-C outcome is computed.

Exact rational deadline: b30=1e9-30*(r-a). Queue count uses 30W>b30; Service uses 30W<=b30<30(W+S); On-time uses 30(W+S)<=b30. Sorting integer30W and integer30(W+S) gives exact CDF counts without a rounded deadline. Direct tuple classifications cross-check deterministic queries. Class order is Queue, Service, On-time; probabilities sum to1.

Transition support/backoff remains KCQA -> KCQ -> KCA -> KC -> C, >=200 samples AND >=3 distinct training runs. Every selected training index set is hashed and its support/backoff linked to each held-out prediction. Old/joint backoff discrepancies: 0. Maximum old/joint queue probability difference: 1.11e-16. The unchanged W marginal means Queue risk is algebraically preserved: K6/C1 success retention is expected, not a newly discovered queue-model improvement.

## Held-out metrics
Five held-out slots; each uses224 training and56 test runs, no shared run within a fold. Brier sums three squared class-probability errors. Logloss retains exact empirical zeros and clips only scoring probabilities to1e-15. No smoothing is introduced. Metrics are pooled over eligible frames within a fold, then reported as equally weighted fold mean and sample SD. Runs, not frames, are experimental units; folds have overlapping training data and are not independent workload draws.

```
  model  Brier_mean  Brier_std  logloss_mean  logloss_std
     B1    0.151729   0.007374      0.273000     0.012836
  P-old    0.105119   0.005932      0.170405     0.010755
P-joint    0.093701   0.006675      0.153830     0.011875
```

All fold values:
```
 fold   model      n    Brier  logloss  true_class_exact_zero  Queue_observed  Queue_predicted  Queue_absolute_error  Service_observed  Service_predicted  Service_absolute_error  On_time_observed  On_time_predicted  On_time_absolute_error
    1      B1 394731 0.155958 0.280882                      0        0.094386         0.086907              0.007479          0.255032           0.253718                0.001314          0.650582           0.659375                0.008793
    1   P-old 394731 0.105392 0.169909                      5        0.094386         0.089973              0.004413          0.255032           0.265499                0.010467          0.650582           0.644528                0.006055
    1 P-joint 394731 0.094733 0.154570                     17        0.094386         0.089973              0.004413          0.255032           0.264157                0.009125          0.650582           0.645870                0.004713
    2      B1 394710 0.162306 0.290840                      0        0.093360         0.088988              0.004371          0.256482           0.257905                0.001423          0.650158           0.653107                0.002948
    2   P-old 394710 0.115186 0.189086                      3        0.093360         0.089030              0.004329          0.256482           0.278368                0.021886          0.650158           0.632602                0.017556
    2 P-joint 394710 0.104952 0.174195                     12        0.093360         0.089030              0.004329          0.256482           0.279062                0.022580          0.650158           0.631908                0.018251
    3      B1 394694 0.148244 0.267710                      0        0.096120         0.085169              0.010951          0.246409           0.251852                0.005443          0.657471           0.662979                0.005508
    3   P-old 394694 0.103232 0.165683                      4        0.096120         0.087650              0.008470          0.246409           0.266521                0.020112          0.657471           0.645829                0.011642
    3 P-joint 394694 0.089911 0.146445                      7        0.096120         0.087650              0.008470          0.246409           0.263714                0.017305          0.657471           0.648636                0.008836
    4      B1 395041 0.143672 0.258203                      0        0.077377         0.084328              0.006951          0.253632           0.251822                0.001810          0.668991           0.663850                0.005141
    4   P-old 395041 0.100814 0.163170                      1        0.077377         0.075562              0.001815          0.253632           0.267708                0.014076          0.668991           0.656730                0.012262
    4 P-joint 395041 0.089729 0.146729                      5        0.077377         0.075562              0.001815          0.253632           0.265932                0.012300          0.668991           0.658506                0.010485
    5      B1 394721 0.148462 0.267367                      0        0.062472         0.078740              0.016268          0.259003           0.256210                0.002793          0.678525           0.665050                0.013474
    5   P-old 394721 0.100969 0.164177                      2        0.062472         0.060544              0.001928          0.259003           0.273394                0.014391          0.678525           0.666062                0.012463
    5 P-joint 394721 0.089181 0.147209                      8        0.062472         0.060544              0.001928          0.259003           0.270448                0.011444          0.678525           0.669008                0.009516
```

Paired P-joint minus P-old (negative improves):
```
 fold  metric  old_value  joint_value  delta_joint_minus_old  improved
    1   Brier   0.105392     0.094733              -0.010659      True
    1 logloss   0.169909     0.154570              -0.015338      True
    2   Brier   0.115186     0.104952              -0.010234      True
    2 logloss   0.189086     0.174195              -0.014891      True
    3   Brier   0.103232     0.089911              -0.013320      True
    3 logloss   0.165683     0.146445              -0.019239      True
    4   Brier   0.100814     0.089729              -0.011085      True
    4 logloss   0.163170     0.146729              -0.016441      True
    5   Brier   0.100969     0.089181              -0.011788      True
    5 logloss   0.164177     0.147209              -0.016968      True
```

## Calibration, including required conditions
Calibration rates are equal-run mean observed/predicted fractions, conditional on ready-on-time. Signed error is predicted minus observed, absolute error is its absolute value; mean run absolute error averages the absolute within-run gaps. CSVs distinguish these and include sample SD. Rates are probability units; multiply by100 for percentage points. These are not all-frame DMR.

K5 Service mean run absolute error: 7.993643 pp -> 4.839761 pp. K5/C Service absolute mean-rate error improves in 8/8 cells; the mean-run-absolute counterpart improves in 8/8. The primary cell-count interpretation was frozen in analysis_plan.md before results.

Required key conditions:
```
scope        K        C   model   stage  n_runs  n_frames  observed_rate  observed_run_SD  predicted_rate  predicted_run_SD  signed_error  absolute_error  mean_run_absolute_error  run_absolute_error_SD
   K5 5.000000      NaN      B1 Service      40    355776       0.103674         0.067361        0.105921          0.099245      0.002247        0.002247                 0.047720               0.042161
   K5 5.000000      NaN   P-old Service      40    355776       0.103674         0.067361        0.181781          0.067489      0.078106        0.078106                 0.079936               0.055269
   K5 5.000000      NaN P-joint Service      40    355776       0.103674         0.067361        0.148496          0.095105      0.044822        0.044822                 0.048398               0.050666
K6/C1 6.000000 1.000000      B1   Queue       5     53734       0.540140         0.339265        0.236584          0.091892     -0.303557        0.303557                 0.303557               0.248498
K6/C1 6.000000 1.000000   P-old   Queue       5     53734       0.540140         0.339265        0.511748          0.327260     -0.028392        0.028392                 0.028392               0.021156
K6/C1 6.000000 1.000000 P-joint   Queue       5     53734       0.540140         0.339265        0.511748          0.327260     -0.028392        0.028392                 0.028392               0.021156
```

All K5/C service cells retained:
```
scope        K        C   model   stage  n_runs  n_frames  observed_rate  observed_run_SD  predicted_rate  predicted_run_SD  signed_error  absolute_error  mean_run_absolute_error  run_absolute_error_SD
K5/C1 5.000000 1.000000      B1 Service       5     44809       0.113831         0.033339        0.019538          0.001915     -0.094293        0.094293                 0.094293               0.034705
K5/C1 5.000000 1.000000   P-old Service       5     44809       0.113831         0.033339        0.139439          0.015148      0.025608        0.025608                 0.040250               0.023821
K5/C1 5.000000 1.000000 P-joint Service       5     44809       0.113831         0.033339        0.124752          0.015281      0.010921        0.010921                 0.038294               0.013134
K5/C2 5.000000 2.000000      B1 Service       5     44806       0.010781         0.016067        0.022039          0.014115      0.011258        0.011258                 0.011258               0.002297
K5/C2 5.000000 2.000000   P-old Service       5     44806       0.010781         0.016067        0.134496          0.029456      0.123715        0.123715                 0.123715               0.013522
K5/C2 5.000000 2.000000 P-joint Service       5     44806       0.010781         0.016067        0.041379          0.063474      0.030598        0.030598                 0.030598               0.047409
K5/C3 5.000000 3.000000      B1 Service       5     44807       0.028343         0.037996        0.038403          0.034241      0.010060        0.010060                 0.010060               0.006375
K5/C3 5.000000 3.000000   P-old Service       5     44807       0.028343         0.037996        0.173698          0.079080      0.145355        0.145355                 0.145355               0.041601
K5/C3 5.000000 3.000000 P-joint Service       5     44807       0.028343         0.037996        0.082967          0.111922      0.054624        0.054624                 0.054624               0.074379
K5/C4 5.000000 4.000000      B1 Service       5     44780       0.056261         0.037932        0.048651          0.032762     -0.007610        0.007610                 0.010932               0.011238
K5/C4 5.000000 4.000000   P-old Service       5     44780       0.056261         0.037932        0.150144          0.027645      0.093883        0.093883                 0.093883               0.015814
K5/C4 5.000000 4.000000 P-joint Service       5     44780       0.056261         0.037932        0.101677          0.065018      0.045416        0.045416                 0.045416               0.032846
K5/C5 5.000000 5.000000      B1 Service       5     44241       0.122931         0.025403        0.045327          0.000756     -0.077603        0.077603                 0.077603               0.025527
K5/C5 5.000000 5.000000   P-old Service       5     44241       0.122931         0.025403        0.168143          0.007051      0.045213        0.045213                 0.045213               0.024663
K5/C5 5.000000 5.000000 P-joint Service       5     44241       0.122931         0.025403        0.164255          0.006923      0.041324        0.041324                 0.041324               0.023605
K5/C6 5.000000 6.000000      B1 Service       5     44126       0.161360         0.022501        0.194141          0.006325      0.032781        0.032781                 0.034229               0.021865
K5/C6 5.000000 6.000000   P-old Service       5     44126       0.161360         0.022501        0.210204          0.009713      0.048845        0.048845                 0.048845               0.017060
K5/C6 5.000000 6.000000 P-joint Service       5     44126       0.161360         0.022501        0.204602          0.010137      0.043242        0.043242                 0.043242               0.015424
K5/C7 5.000000 7.000000      B1 Service       5     44119       0.155514         0.029947        0.225320          0.008320      0.069806        0.069806                 0.069806               0.035031
K5/C7 5.000000 7.000000   P-old Service       5     44119       0.155514         0.029947        0.210908          0.009667      0.055394        0.055394                 0.055394               0.030756
K5/C7 5.000000 7.000000 P-joint Service       5     44119       0.155514         0.029947        0.204538          0.009192      0.049024        0.049024                 0.049024               0.030031
K5/C8 5.000000 8.000000      B1 Service       5     44088       0.180376         0.042253        0.253953          0.077618      0.073578        0.073578                 0.073578               0.054503
K5/C8 5.000000 8.000000   P-old Service       5     44088       0.180376         0.042253        0.267214          0.135134      0.086838        0.086838                 0.086838               0.108267
K5/C8 5.000000 8.000000 P-joint Service       5     44088       0.180376         0.042253        0.263798          0.137816      0.083422        0.083422                 0.084658               0.109442
```

Overall/K5/K6/K7 calibration:
```
scope        K   C   model   stage  n_runs  n_frames  observed_rate  observed_run_SD  predicted_rate  predicted_run_SD  signed_error  absolute_error  mean_run_absolute_error  run_absolute_error_SD
  ALL      NaN NaN      B1   Queue     280   1973897       0.049706         0.184838        0.051825          0.154970      0.002119        0.002119                 0.022099               0.061291
  ALL      NaN NaN      B1 Service     280   1973897       0.164736         0.290167        0.169519          0.265540      0.004783        0.004783                 0.034112               0.042403
  ALL      NaN NaN      B1 On_time     280   1973897       0.785558         0.335784        0.778656          0.311240     -0.006901        0.006901                 0.037895               0.042450
  ALL      NaN NaN   P-old   Queue     280   1973897       0.049706         0.184838        0.046962          0.182098     -0.002744        0.002744                 0.003781               0.013087
  ALL      NaN NaN   P-old Service     280   1973897       0.164736         0.290167        0.177778          0.286802      0.013041        0.013041                 0.019957               0.037711
  ALL      NaN NaN   P-old On_time     280   1973897       0.785558         0.335784        0.775260          0.330012     -0.010298        0.010298                 0.018463               0.035689
  ALL      NaN NaN P-joint   Queue     280   1973897       0.049706         0.184838        0.046962          0.182098     -0.002744        0.002744                 0.003781               0.013087
  ALL      NaN NaN P-joint Service     280   1973897       0.164736         0.290167        0.175170          0.294325      0.010433        0.010433                 0.011437               0.027748
  ALL      NaN NaN P-joint On_time     280   1973897       0.785558         0.335784        0.777868          0.337612     -0.007690        0.007690                 0.010740               0.025621
   K5 5.000000 NaN      B1   Queue      40    355776       0.003691         0.004797        0.011462          0.017785      0.007771        0.007771                 0.008425               0.016750
   K5 5.000000 NaN      B1 Service      40    355776       0.103674         0.067361        0.105921          0.099245      0.002247        0.002247                 0.047720               0.042161
   K5 5.000000 NaN      B1 On_time      40    355776       0.892634         0.065677        0.882616          0.098134     -0.010018        0.010018                 0.053906               0.042032
   K5 5.000000 NaN   P-old   Queue      40    355776       0.003691         0.004797        0.000588          0.001207     -0.003103        0.003103                 0.003171               0.004463
   K5 5.000000 NaN   P-old Service      40    355776       0.103674         0.067361        0.181781          0.067489      0.078106        0.078106                 0.079936               0.055269
   K5 5.000000 NaN   P-old On_time      40    355776       0.892634         0.065677        0.817631          0.067328     -0.075003        0.075003                 0.078172               0.053900
   K5 5.000000 NaN P-joint   Queue      40    355776       0.003691         0.004797        0.000588          0.001207     -0.003103        0.003103                 0.003171               0.004463
   K5 5.000000 NaN P-joint Service      40    355776       0.103674         0.067361        0.148496          0.095105      0.044822        0.044822                 0.048398               0.050666
   K5 5.000000 NaN P-joint On_time      40    355776       0.892634         0.065677        0.850916          0.095010     -0.041719        0.041719                 0.046633               0.051212
   K6 6.000000 NaN      B1   Queue      40    423166       0.073343         0.209222        0.066697          0.084984     -0.006646        0.006646                 0.069243               0.126748
   K6 6.000000 NaN      B1 Service      40    423166       0.516828         0.299595        0.504841          0.230344     -0.011987        0.011987                 0.087817               0.059496
   K6 6.000000 NaN      B1 On_time      40    423166       0.409829         0.260291        0.428462          0.189612      0.018633        0.018633                 0.078524               0.061536
   K6 6.000000 NaN   P-old   Queue      40    423166       0.073343         0.209222        0.067287          0.199918     -0.006055        0.006055                 0.008180               0.011637
   K6 6.000000 NaN   P-old Service      40    423166       0.516828         0.299595        0.525810          0.298864      0.008982        0.008982                 0.020029               0.016379
   K6 6.000000 NaN   P-old On_time      40    423166       0.409829         0.260291        0.406903          0.261659     -0.002927        0.002927                 0.017223               0.015283
   K6 6.000000 NaN P-joint   Queue      40    423166       0.073343         0.209222        0.067287          0.199918     -0.006055        0.006055                 0.008180               0.011637
   K6 6.000000 NaN P-joint Service      40    423166       0.516828         0.299595        0.527909          0.297989      0.011081        0.011081                 0.013451               0.011575
   K6 6.000000 NaN P-joint On_time      40    423166       0.409829         0.260291        0.404804          0.259599     -0.005025        0.005025                 0.015511               0.013110
   K7 7.000000 NaN      B1   Queue      40    479178       0.268564         0.372613        0.261143          0.328983     -0.007421        0.007421                 0.055862               0.072210
   K7 7.000000 NaN      B1 Service      40    479178       0.531160         0.358504        0.517891          0.313000     -0.013269        0.013269                 0.046760               0.039884
   K7 7.000000 NaN      B1 On_time      40    479178       0.200276         0.199163        0.220966          0.155664      0.020690        0.020690                 0.055218               0.045230
   K7 7.000000 NaN   P-old   Queue      40    479178       0.268564         0.372613        0.260671          0.372491     -0.007893        0.007893                 0.012954               0.030260
   K7 7.000000 NaN   P-old Service      40    479178       0.531160         0.358504        0.523851          0.348946     -0.007310        0.007310                 0.027472               0.034479
   K7 7.000000 NaN   P-old On_time      40    479178       0.200276         0.199163        0.215478          0.204389      0.015203        0.015203                 0.020399               0.026060
   K7 7.000000 NaN P-joint   Queue      40    479178       0.268564         0.372613        0.260671          0.372491     -0.007893        0.007893                 0.012954               0.030260
   K7 7.000000 NaN P-joint Service      40    479178       0.531160         0.358504        0.546809          0.356413      0.015649        0.015649                 0.015928               0.029639
   K7 7.000000 NaN P-joint On_time      40    479178       0.200276         0.199163        0.192520          0.195797     -0.007756        0.007756                 0.009014               0.012036
```

All K5–7/C1–8 class rates and errors are in calibration_by_K_C.csv; no favorable-cell-only reporting. Full per-run metrics remain available for each comparison.

Remaining K5 bias is not eliminated: the P-joint Service predicted mean is 14.8496% versus observed 10.3674%. Its mean run absolute error is 4.8398 pp, compared with B1 4.7720 pp. Passing this gate therefore supports improvement over P-old under the supplied criteria; it does not establish perfect calibration or superiority in every individual condition.

## Support and backoff
```
 fold level  test_frames  usage_percent  lookup_groups  training_samples_min  training_samples_weighted_mean  training_samples_max  training_runs_min  training_runs_max  old_joint_backoff_differences
    0  KCQA      1882184      95.353709           2299            200.000000                     5478.044023           7519.000000           3.000000           4.000000                              0
    0   KCQ         9884       0.500735            328            204.000000                     2521.017807          35590.000000           3.000000           4.000000                              0
    0   KCA        81691       4.138564            416            450.000000                    44759.745186          50138.000000           3.000000           4.000000                              0
    0    KC          138       0.006991             29           7195.000000                    24551.594203          41607.000000           4.000000           4.000000                              0
    0     C            0       0.000000              0                   NaN                             NaN                   NaN                NaN                NaN                              0
```

Full-state usage is 95.353709%; remaining usage follows the original backoff. No test labels or test W/S/A_start select support. joint_support_lookup.csv records training sample/run counts, training-index hashes and old comparisons; prediction files carry the lookup ID. A_start remains in the source tuple and is not a new target feature.

## Predeclared verdict
**JOINT_STAGE_MODEL_SUPPORTED**

```
{
  "Brier_mean_improved": true,
  "logloss_mean_improved": true,
  "Brier_at_least_4_of_5": true,
  "logloss_at_least_4_of_5": true,
  "K5_service_mean_run_error_reduced": true,
  "K5_service_absolute_error_cells_at_least_5": true,
  "K6_C1_queue_absolute_error_at_most_5pp": true
}
```

Improving folds: Brier 5/5, logloss 5/5. Mean differences: Brier -0.01141722, logloss -0.01657540. Criteria are exactly those supplied before analysis: both mean metrics improve, each >=4/5, K5 mean-run Service error reduces, >=5/8 K5 Service cells improve, K6/C1 Queue error<=5pp. NOT_SUPPORTED takes precedence if either mean does not improve, either metric improves in<=2 folds or K5 mean-run Service error does not decrease. No post-result rule changes.

## Interpretation and limitations
This ablation asks whether retaining the observed W/S association improves the probability model. It does not establish that the old independence assumption uniquely caused all errors; besides W/S coupling, the triplet keeps all observed associations between ready state and service within each selected support group, whereas the old service pool marginalized some of them. This is the requested single replacement of the factorized distribution, not an added observed feature.

Any support is confined to held-out acquisitions of this same static grid, video content, model and Thor platform. Empirical probabilities may still be poorly calibrated in sparse regimes. Publication/receipt delay was not recorded: A is ideal event-time state, not validated observer receipt state. A is application in-flight count, not GPU kernel parallelism. PRE_READY_LATE exclusion limits scope and does not prove an immutable policy lower bound. No residual-time prediction, deadline guarantee, alternative-C outcome, scheduler improvement, Local/Edge or Lyapunov validity is demonstrated. No additional model or history feature was tried to improve the verdict.

## Reproduction and files
In a new output directory containing these script copies: build_dataset.py -> reproduce_old.py -> fit_joint.py -> analyze_joint.py -> make_figures.py -> verify_integrity.py. Root derives from the script location. Existing-output guards prevent reruns/overwrites. `frozen_models.py` is an unchanged reference module; do not execute its original main entrypoint (it would run the prior gate, including B0). Only the listed reproduction wrapper invokes B1 and P-old. Code hashes, input hashes and numerical checks preserve provenance. Three PNG/PDF figure types only. analysis_integrity.json records final preservation and Git state; commit/push is NO.
