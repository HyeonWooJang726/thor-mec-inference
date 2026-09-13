# Structural stage model feasibility gate

## Dataset and preservation
280 valid Static-C acquisitions, 56 conditions, five saved valid slots. 2,016,000 frames audited; 1,973,897 ready-on-time evaluated; 42,103 PRE_READY_LATE excluded (2.0884%). No startup exclusion. Dynamic acquisitions unused. K2/C1 replacement retains statistical slot4 and is not original Round4. Historical failed run is excluded. No GPU runs, controller, residual predictor, policy replay or counterfactual C.

## Measurement and probability model
See metric_definitions.md and analysis_plan.md for source-level boundaries, rational deadline arithmetic and pre-frame states. Q is exact canonical before-enqueue accounting. A is ideal event-time in-flight state; publication delay was not recorded, so deployment observability is not established. W and A_start remain a joint empirical training sample; the service empirical CDF then integrates all samples, with no Monte Carlo, smoothing or duration binning. Test W/A_start/S never enter prediction. Service distributions include all ready-on-time training frames, including queue-stage misses; no selection on successful service start. This explicitly assumes S independent of W given K,C,A_start.

All models share held-out frames. B0 uses K,C,b; B1 adds Q,A; P uses the specified empirical chain. Direct baselines use training-only scaling and fixed L2=0.001, no tuning. Multiclass Brier is the sum over three classes. Exact empirical zeros are retained; only logloss scoring clips at 1e-15. Their true-class zero counts are reported below, so a large logloss is not hidden or repaired by smoothing.

## Primary held-out results
Five-fold mean metrics (folds equally weighted; each fold contains 56 acquisitions; shared training sets mean folds are not five independent new workloads):

```
model    Brier  logloss
   B0 0.164171 0.295501
   B1 0.151729 0.273000
    P 0.105119 0.170405
```

Five-fold sample SD:
```
model    Brier  logloss
   B0 0.007023 0.011531
   B1 0.007374 0.012836
    P 0.005932 0.010755
```

P-minus-baseline per-fold differences (negative improves):
```
comparison  metric  fold     delta  improved
P_minus_B0   Brier     1 -0.059265      True
P_minus_B0   Brier     2 -0.060315      True
P_minus_B0   Brier     3 -0.057095      True
P_minus_B0   Brier     4 -0.056046      True
P_minus_B0   Brier     5 -0.062543      True
P_minus_B0 logloss     1 -0.127301      True
P_minus_B0 logloss     2 -0.124578      True
P_minus_B0 logloss     3 -0.123180      True
P_minus_B0 logloss     4 -0.119906      True
P_minus_B0 logloss     5 -0.130514      True
P_minus_B1   Brier     1 -0.050566      True
P_minus_B1   Brier     2 -0.047120      True
P_minus_B1   Brier     3 -0.045012      True
P_minus_B1   Brier     4 -0.042859      True
P_minus_B1   Brier     5 -0.047493      True
P_minus_B1 logloss     1 -0.110973      True
P_minus_B1 logloss     2 -0.101754      True
P_minus_B1 logloss     3 -0.102027      True
P_minus_B1 logloss     4 -0.095033      True
P_minus_B1 logloss     5 -0.103190      True
```

Fold metrics, including exact-zero true-class probabilities:
```
 fold model      n    Brier  logloss  true_class_exact_zero
    1    B0 394731 0.164657 0.297209                      0
    1    B1 394731 0.155958 0.280882                      0
    1     P 394731 0.105392 0.169909                      5
    2    B0 394710 0.175501 0.313664                      0
    2    B1 394710 0.162306 0.290840                      0
    2     P 394710 0.115186 0.189086                      3
    3    B0 394694 0.160327 0.288863                      0
    3    B1 394694 0.148244 0.267710                      0
    3     P 394694 0.103232 0.165683                      4
    4    B0 395041 0.156860 0.283077                      0
    4    B1 395041 0.143672 0.258203                      0
    4     P 395041 0.100814 0.163170                      1
    5    B0 394721 0.163512 0.294691                      0
    5    B1 394721 0.148462 0.267367                      0
    5     P 394721 0.100969 0.164177                      2
```

Frame counts are observation counts, not independent replication. Per-run metrics and both pooled-fold and equal-run condition reporting are preserved. No significance claim.

## Calibration
Condition/stage mean absolute run rate-error improved for 54/72 K5–7/C1–8 stage cells versus B1. At K-aggregate stage level it improved for 7/9 cells. These counts are descriptive; individual important regressions are retained. Rates below are conditional on ready-on-time, not all-frame DMR. Absolute errors are probability units (multiply by100 for pp).

```
scope model   stage  runs  observed_rate_mean  predicted_rate_mean  signed_rate_gap  absolute_mean_rate_gap  mean_run_absolute_error  SD_run_absolute_error
   K5    B0   Queue    40            0.003691             0.011826         0.008135                0.008135                 0.008622               0.016147
   K5    B0 Service    40            0.103674             0.105097         0.001423                0.001423                 0.047694               0.045900
   K5    B0 On_time    40            0.892634             0.883077        -0.009558                0.009558                 0.051882               0.046333
   K5    B1   Queue    40            0.003691             0.011462         0.007771                0.007771                 0.008425               0.016750
   K5    B1 Service    40            0.103674             0.105921         0.002247                0.002247                 0.047720               0.042161
   K5    B1 On_time    40            0.892634             0.882616        -0.010018                0.010018                 0.053906               0.042032
   K5     P   Queue    40            0.003691             0.000588        -0.003103                0.003103                 0.003171               0.004463
   K5     P Service    40            0.103674             0.181781         0.078106                0.078106                 0.079936               0.055269
   K5     P On_time    40            0.892634             0.817631        -0.075003                0.075003                 0.078172               0.053900
   K6    B0   Queue    40            0.073343             0.067934        -0.005409                0.005409                 0.059328               0.122682
   K6    B0 Service    40            0.516828             0.504698        -0.012131                0.012131                 0.087502               0.061083
   K6    B0 On_time    40            0.409829             0.427369         0.017539                0.017539                 0.072989               0.056850
   K6    B1   Queue    40            0.073343             0.066697        -0.006646                0.006646                 0.069243               0.126748
   K6    B1 Service    40            0.516828             0.504841        -0.011987                0.011987                 0.087817               0.059496
   K6    B1 On_time    40            0.409829             0.428462         0.018633                0.018633                 0.078524               0.061536
   K6     P   Queue    40            0.073343             0.067287        -0.006055                0.006055                 0.008180               0.011637
   K6     P Service    40            0.516828             0.525810         0.008982                0.008982                 0.020029               0.016379
   K6     P On_time    40            0.409829             0.406903        -0.002927                0.002927                 0.017223               0.015283
   K7    B0   Queue    40            0.268564             0.259910        -0.008654                0.008654                 0.109152               0.095252
   K7    B0 Service    40            0.531160             0.516252        -0.014909                0.014909                 0.079213               0.049051
   K7    B0 On_time    40            0.200276             0.223838         0.023563                0.023563                 0.080614               0.053087
   K7    B1   Queue    40            0.268564             0.261143        -0.007421                0.007421                 0.055862               0.072210
   K7    B1 Service    40            0.531160             0.517891        -0.013269                0.013269                 0.046760               0.039884
   K7    B1 On_time    40            0.200276             0.220966         0.020690                0.020690                 0.055218               0.045230
   K7     P   Queue    40            0.268564             0.260671        -0.007893                0.007893                 0.012954               0.030260
   K7     P Service    40            0.531160             0.523851        -0.007310                0.007310                 0.027472               0.034479
   K7     P On_time    40            0.200276             0.215478         0.015203                0.015203                 0.020399               0.026060
```

K6/C1, the prespecified calibration check:
```
scope model   stage  runs  observed_rate_mean  predicted_rate_mean  signed_rate_gap  absolute_mean_rate_gap  mean_run_absolute_error  SD_run_absolute_error
K6/C1    B0   Queue     5            0.540140             0.291757        -0.248383                0.248383                 0.269512               0.264752
K6/C1    B0 Service     5            0.089920             0.270816         0.180896                0.180896                 0.180896               0.117057
K6/C1    B0 On_time     5            0.369939             0.437427         0.067487                0.067487                 0.145039               0.096268
K6/C1    B1   Queue     5            0.540140             0.236584        -0.303557                0.303557                 0.303557               0.248498
K6/C1    B1 Service     5            0.089920             0.284598         0.194678                0.194678                 0.194678               0.080734
K6/C1    B1 On_time     5            0.369939             0.478818         0.108879                0.108879                 0.150261               0.122078
K6/C1     P   Queue     5            0.540140             0.511748        -0.028392                0.028392                 0.028392               0.021156
K6/C1     P Service     5            0.089920             0.104518         0.014598                0.014598                 0.014598               0.004119
K6/C1     P On_time     5            0.369939             0.383734         0.013794                0.013794                 0.014891               0.017261
```

All K5–7/C stage rates (mean of five run rates):
```
 K  C model  Queue_observed_mean  Queue_predicted_mean  Service_observed_mean  Service_predicted_mean  On_time_observed_mean  On_time_predicted_mean
 5  1    B0             0.014350              0.027062               0.113831                0.019475               0.871819                0.953463
 5  1    B1             0.014350              0.012913               0.113831                0.019538               0.871819                0.967550
 5  1     P             0.014350              0.001079               0.113831                0.139439               0.871819                0.859482
 5  2    B0             0.006450              0.032553               0.010781                0.025578               0.982769                0.941869
 5  2    B1             0.006450              0.033095               0.010781                0.022039               0.982769                0.944867
 5  2     P             0.006450              0.000585               0.010781                0.134496               0.982769                0.864919
 5  3    B0             0.004464              0.010946               0.028343                0.045297               0.967193                0.943757
 5  3    B1             0.004464              0.014660               0.028343                0.038403               0.967193                0.946937
 5  3     P             0.004464              0.000312               0.028343                0.173698               0.967193                0.825990
 5  4    B0             0.004198              0.006816               0.056261                0.058265               0.939541                0.934919
 5  4    B1             0.004198              0.009091               0.056261                0.048651               0.939541                0.942257
 5  4     P             0.004198              0.002711               0.056261                0.150144               0.939541                0.847145
 5  5    B0             0.000023              0.002688               0.122931                0.040667               0.877047                0.956645
 5  5    B1             0.000023              0.004172               0.122931                0.045327               0.877047                0.950500
 5  5     P             0.000023              0.000002               0.122931                0.168143               0.877047                0.831854
 5  6    B0             0.000045              0.006178               0.161360                0.178279               0.838595                0.815543
 5  6    B1             0.000045              0.008302               0.161360                0.194141               0.838595                0.797558
 5  6     P             0.000045              0.000014               0.161360                0.210204               0.838595                0.789782
 5  7    B0             0.000000              0.003553               0.155514                0.216961               0.844486                0.779487
 5  7    B1             0.000000              0.003907               0.155514                0.225320               0.844486                0.770774
 5  7     P             0.000000              0.000003               0.155514                0.210908               0.844486                0.789090
 5  8    B0             0.000000              0.004817               0.180376                0.256254               0.819624                0.738930
 5  8    B1             0.000000              0.005561               0.180376                0.253953               0.819624                0.740486
 5  8     P             0.000000              0.000001               0.180376                0.267214               0.819624                0.732785
 6  1    B0             0.540140              0.291757               0.089920                0.270816               0.369939                0.437427
 6  1    B1             0.540140              0.236584               0.089920                0.284598               0.369939                0.478818
 6  1     P             0.540140              0.511748               0.089920                0.104518               0.369939                0.383734
 6  2    B0             0.018166              0.141985               0.301384                0.221143               0.680451                0.636873
 6  2    B1             0.018166              0.156833               0.301384                0.229404               0.680451                0.613763
 6  2     P             0.018166              0.002737               0.301384                0.316998               0.680451                0.680265
 6  3    B0             0.010708              0.034002               0.363774                0.321911               0.625518                0.644087
 6  3    B1             0.010708              0.045254               0.363774                0.338604               0.625518                0.616142
 6  3     P             0.010708              0.000933               0.363774                0.416370               0.625518                0.582697
 6  4    B0             0.006594              0.019863               0.328833                0.338780               0.664574                0.641357
 6  4    B1             0.006594              0.027905               0.328833                0.350658               0.664574                0.621437
 6  4     P             0.006594              0.005954               0.328833                0.316681               0.664574                0.677366
 6  5    B0             0.010998              0.020832               0.409660                0.486780               0.579342                0.492388
 6  5    B1             0.010998              0.028043               0.409660                0.487741               0.579342                0.484216
 6  5     P             0.010998              0.016914               0.409660                0.384949               0.579342                0.598137
 6  6    B0             0.000038              0.017486               0.863509                0.772560               0.136453                0.209954
 6  6    B1             0.000038              0.020958               0.863509                0.758246               0.136453                0.220796
 6  6     P             0.000038              0.000006               0.863509                0.871705               0.136453                0.128289
 6  7    B0             0.000077              0.008815               0.891461                0.818937               0.108462                0.172248
 6  7    B1             0.000077              0.009177               0.891461                0.798283               0.108462                0.192540
 6  7     P             0.000077              0.000003               0.891461                0.900759               0.108462                0.099238
 6  8    B0             0.000019              0.008730               0.886084                0.806655               0.113897                0.184615
 6  8    B1             0.000019              0.008822               0.886084                0.791194               0.113897                0.199984
 6  8     P             0.000019              0.000001               0.886084                0.894502               0.113897                0.105497
 7  1    B0             1.000000              0.714283               0.000000                0.130425               0.000000                0.155291
 7  1    B1             1.000000              0.985959               0.000000                0.003733               0.000000                0.010308
 7  1     P             1.000000              1.000000               0.000000                0.000000               0.000000                0.000000
 7  2    B0             0.740174              0.620236               0.086731                0.154670               0.173095                0.225094
 7  2    B1             0.740174              0.581885               0.086731                0.157194               0.173095                0.260922
 7  2     P             0.740174              0.735587               0.086731                0.095782               0.173095                0.168631
 7  3    B0             0.219029              0.266300               0.367420                0.390724               0.413551                0.342976
 7  3    B1             0.219029              0.224678               0.367420                0.395944               0.413551                0.379378
 7  3     P             0.219029              0.167076               0.367420                0.405196               0.413551                0.427728
 7  4    B0             0.039519              0.133581               0.426289                0.425447               0.534191                0.440972
 7  4    B1             0.039519              0.093962               0.426289                0.441373               0.534191                0.464665
 7  4     P             0.039519              0.018879               0.426289                0.445005               0.534191                0.536116
 7  5    B0             0.066231              0.138525               0.596246                0.560612               0.337522                0.300863
 7  5    B1             0.066231              0.093864               0.596246                0.579941               0.337522                0.326195
 7  5     P             0.066231              0.078907               0.596246                0.523220               0.337522                0.397873
 7  6    B0             0.083367              0.102624               0.840718                0.782644               0.075915                0.114732
 7  6    B1             0.083367              0.061152               0.840718                0.805466               0.075915                0.133382
 7  6     P             0.083367              0.084845               0.840718                0.778045               0.075915                0.137109
 7  7    B0             0.000140              0.051147               0.969584                0.842507               0.030276                0.106346
 7  7    B1             0.000140              0.023317               0.969584                0.879930               0.030276                0.096753
 7  7     P             0.000140              0.000067               0.969584                0.974818               0.030276                0.025115
 7  8    B0             0.000053              0.052586               0.962293                0.842983               0.037654                0.104431
 7  8    B1             0.000053              0.024327               0.962293                0.879551               0.037654                0.096123
 7  8     P             0.000053              0.000009               0.962293                0.968738               0.037654                0.031253
```

`calibration_curves.csv` retains fixed-bin predicted/observed rates for each held-out fold; `calibration_errors.csv` distinguishes absolute gap of mean rates from mean absolute run-level gaps. Neither is a causal effect.

## Backoff and support
Full transition state usage: 95.3537%; backoff: 4.6463%. All selected distributions have >=200 samples and >=3 distinct training runs. Predictions carry transition_group_id; transition_support_lookup.csv gives level, exact key, sample/run count and service-mixture lookup IDs. service_support_lookup.csv resolves every sampled A_start lookup/support. Service usage is transition-mixture-weighted, not an extra sample count. No silent unsupported default.

```
           kind  fold     level  predictions_or_mixture_weight  minimum_training_samples  minimum_training_runs
     transition     1        KC                      30.000000                      7195                      4
     transition     1       KCA                   16311.000000                       496                      4
     transition     1       KCQ                    1909.000000                       218                      3
     transition     1      KCQA                  376481.000000                       201                      3
     transition     2        KC                      25.000000                      7195                      4
     transition     2       KCA                   16277.000000                       550                      4
     transition     2       KCQ                    1783.000000                       231                      3
     transition     2      KCQA                  376625.000000                       200                      3
     transition     3        KC                      28.000000                     14360                      4
     transition     3       KCA                   18719.000000                       469                      3
     transition     3       KCQ                    1887.000000                       204                      3
     transition     3      KCQA                  374060.000000                       200                      3
     transition     4        KC                      25.000000                     14361                      4
     transition     4       KCA                   15368.000000                       467                      4
     transition     4       KCQ                    2079.000000                       204                      3
     transition     4      KCQA                  377569.000000                       202                      3
     transition     5        KC                      30.000000                     14364                      4
     transition     5       KCA                   15016.000000                       450                      4
     transition     5       KCQ                    2226.000000                       221                      3
     transition     5      KCQA                  377449.000000                       200                      3
service_mixture     1 KCA_start                  394730.686352                      1170                      4
service_mixture     1  CA_start                       0.313648                      1175                      6
service_mixture     2 KCA_start                  394709.979755                      1293                      3
service_mixture     2  CA_start                       0.020245                      1294                      5
service_mixture     3 KCA_start                  394693.760576                      1096                      3
service_mixture     3  CA_start                       0.239424                      1102                      7
service_mixture     4 KCA_start                  395040.702215                      1141                      3
service_mixture     4  CA_start                       0.297785                      1147                      7
service_mixture     5 KCA_start                  394720.739916                      1014                      3
service_mixture     5  CA_start                       0.260084                      1102                      7
```

## Structural assumption audit
All 844 held-out run/state groups are retained. For readable effect summaries, 842 groups have >=20 held-out frames in each training-defined low/high-W tail. Their median high-minus-low service difference is 0.133311 ms; median absolute difference 0.478714 ms; median held-out within-group Spearman W/S 0.026601. These are descriptive support-stratified effects, not significance tests.

Largest absolute held-out differences, presented as diagnostic examples with all groups available in CSV:
```
 fold  run  K  C  A_start  training_n  training_runs  test_n  train_W_q25_ns  train_W_q75_ns  test_low_n  test_high_n  test_low_service_mean_ms  test_high_service_mean_ms  high_minus_low_ms  heldout_spearman_W_S  heldout_service_CDF_mean
    1  265  7  6        5       13705              4    3476    95417.000000 18341838.000000         830          969                 25.091181                   8.431747         -16.659434             -0.847239                  0.504044
    3  267  7  6        5       13788              4    3393    96248.500000 18329934.500000         839          955                 24.836010                   8.287305         -16.548705             -0.849580                  0.484454
    2  266  7  6        5       13741              4    3440    95889.000000 18325992.000000         834          969                 24.869936                   8.366257         -16.503680             -0.842043                  0.499419
    4  268  7  6        5       13789              4    3392    95787.000000 18713434.000000         819          690                 24.589482                   8.380330         -16.209153             -0.839886                  0.502096
    5  269  7  6        5       13701              4    3480   101140.000000 18696105.000000         974          727                 24.586390                   8.624284         -15.962107             -0.825393                  0.509733
    3  222  6  5        4       13968              4    3491    83727.500000 15228574.500000         874          954                 20.595052                   7.535930         -13.059122             -0.863614                  0.495597
    2  221  6  5        4       13983              4    3476    81481.500000 15329212.000000         811          822                 20.560272                   7.529592         -13.030680             -0.868442                  0.504825
    1  220  6  5        4       13965              4    3494    83888.000000 15312812.000000         879          846                 20.460751                   7.582083         -12.878668             -0.862145                  0.501032
    4  223  6  5        4       13955              4    3504    85144.500000 15273242.000000         923          896                 20.468344                   7.590217         -12.878127             -0.854746                  0.502648
    5  224  6  5        4       13965              4    3494    84093.000000 15304577.000000         884          855                 20.384768                   7.566490         -12.818277             -0.864078                  0.495908
    1  260  7  5        4       21823              4    5482   414301.000000 16359727.500000        1362         1491                 21.434291                  11.262074         -10.172216             -0.806322                  0.503809
    4  263  7  5        4       21892              4    5413   424378.500000 16366935.250000        1379         1452                 21.375521                  11.211401         -10.164121             -0.815052                  0.492583
```

W cut points and service CDFs are learned only from the other four slots. Held-out W and S are used here exclusively to audit the assumption, never to produce ready predictions. Nonzero within-state dependence indicates missing history/state or selection effects can matter; it does not prove W causes service inflation. The descriptive audit does not add features or rescue the model. The test is not a conditional-independence proof, and correlations remain sensitive to shared temporal state and small support.

Repeated counterexamples to the service independence assumption are visible even after conditioning on K,C,A_start: at K5/C4/A_start=3, the held-out high-W versus low-W service difference averages -8.1124 ms (sample SD 1.4605), negative in 5/5 runs; median within-group rank association is -0.8282. At K7/C6/A_start=5 the difference is -16.3766 ms (SD 0.2853), negative in 5/5, rank association -0.8420. These repeated conditional associations are material counterevidence to treating service as independent of waiting/history. They can help explain a limitation of the factorization but do not prove the cause of a particular calibration error. No W feature was added to the service model. See structural_assumption_summary.csv for every supported group and workload_fold_calibration.csv for all workload/fold stage errors.

## Verdict
**STRUCTURAL_STAGE_MODEL_WEAKLY_SUPPORTED**

P-minus-B1 means: Brier -0.04661006, logloss -0.10259523; improving folds 5/5 and 5/5, respectively. The predeclared rule requires mean improvement in both metrics and >=4/5 consistent folds, alongside improved important calibration. The full condition table above must accompany the mean result. The WEAKLY_SUPPORTED condition-consistency clause applies here: K5 service mean absolute run rate-error increases from 4.7720 to 7.9936 pp, worsens in all five held-out folds, and worsens in five of eight C conditions, especially C2–C4. K5 observed service-stage rate is 10.3674%, versus P prediction 18.1781% (equal-run means). Thus the strong aggregate improvement does not establish consistently improved stage calibration across important workloads. This is a qualitative assessment under the supplied criterion, not an added effect-size or significance threshold. No further models, tuned support or thresholds were introduced.

## Limitations
This is observed-trajectory probability modeling, not a controller evaluation or an alternative-C outcome. Same videos, one Thor platform/model and 60-second acquisitions limit generalization. Five held-out slots quantify run-to-run behavior, with overlapping training sets. A is host request-interval concurrency, not kernel parallelism; unmeasured publication delay limits online claims. Exact-state backoff can remove Q/A information; empirical CDFs can assign zero probability to held-out events. Service independence from waiting is not guaranteed. PRE_READY_LATE exclusion limits scope and is not a policy-invariant lower bound. No deadline guarantee, Local/Edge/Lyapunov validation, residual prediction, or new policy DMR is demonstrated. A negative verdict ends this gate without extending the model.

## Reproduction and outputs
Run `_scripts/build_dataset.py`, `_scripts/fit_models.py`, `_scripts/analyze_models.py`, `_scripts/make_figures.py`, `_scripts/verify_preservation.py` in that order in an empty copy of this output root (script root constants need the chosen new root). Existing outputs have overwrite guards; do not rerun into protected results. Numerical CDF helper is compiled by fit_models using installed g++; all inference/runtime modules are read only and never imported. Three figure types, each PNG/PDF; no SVG. Final hashes and Git preservation evidence are in analysis_integrity.json.
