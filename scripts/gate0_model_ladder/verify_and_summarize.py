#!/usr/bin/env python3
"""CPU tests and explicit secondary coverage/margin supplement; no model refit."""
import argparse
import csv
import json
from pathlib import Path
import statistics as st

import numpy as np
import analyze_gate0 as model


def main(source, output):
    if output.exists(): raise RuntimeError('No overwrite')
    low=model.queue_model(10,10,np.array([1.]),1000)
    high=model.queue_model(30,10,np.array([1.]),1000)
    assert low['predicted_feasible'] and not high['predicted_feasible']
    assert abs(high['g_B_model']-40)<.02
    assert model.selection('x',96,{('x',630):None,('x',792):150},[630,792])==(None,'UNKNOWN_MISSING_LOWER_FREQUENCY')
    assert model.truth_selection(100,{630:(96,104),792:(120,128)},[630,792])==(None,'INSIDE_UNTESTED_BRACKET')
    try: model.record(model.ROOT/'results/local_capacity_characterization/capacity_anchor_map.csv','PREDICTOR')
    except RuntimeError: pass
    else: raise AssertionError('Target predictor input accepted')
    def read(name):
        with (source/name).open() as f:return list(csv.DictReader(f))
    errors=read('bracket_errors.csv');sweeps=read('safety_margin_sweep.csv')
    output.mkdir()
    summary=[]
    for name in ['M1','M2','M3','M4']:
        for scope,domain in [('DIRECT-ONLY',model.DIRECT),('FULL-7',model.FREQS)]:
            vals=[float(x['absolute_error_percent']) for x in errors if x['model']==name and int(x['frequency_MHz']) in domain and x['absolute_error_percent']]
            summary.append(dict(model=name,scope=scope,N=len(vals),mean_absolute_error=st.mean(vals),
                                median_absolute_error=st.median(vals),max_absolute_error=max(vals)))
    model.write_csv(output,'bracket_errors_by_scope.csv',summary)
    zeros=[]
    for name in ['M1','M2','M3','M4','M3_POWER_LAW','M4_POWER_LAW']:
        for scope in ['FULL-7','DIRECT-ONLY']:
            rr=[r for r in sweeps if r['model']==name and r['scope']==scope]
            if not rr:continue
            zero=next((r for r in rr if int(r['FALSE_FEASIBLE'])==0),None)
            zeros.append(dict(model=name,scope=scope,margin=None if zero is None else zero['margin_percent'],
                exact_matches=None if zero is None else zero['exact_matches'],N=rr[0]['N'],
                unknown=None if zero is None else zero['unknown'],
                over_provision_steps_mean=None if zero is None else zero['over_provision_steps_mean'],
                additional_steps_mean=None if zero is None else zero['additional_DVFS_steps_mean'],
                additional_steps_max=None if zero is None else zero['additional_DVFS_steps_max']))
    model.write_csv(output,'minimum_margins_by_scope.csv',zeros)
    text=['# SECONDARY — coverage and margin supplement','', 'POST-HOC SECONDARY ANALYSIS; no Gate verdict change.', '',
        model.table(summary,['model','scope','N','mean_absolute_error','median_absolute_error','max_absolute_error']), '',
        model.table(zeros,['model','scope','margin','exact_matches','N','unknown','over_provision_steps_mean','additional_steps_mean','additional_steps_max']), '',
        'DIRECT-ONLY frequencies945/1260/1575: M4 at10% margin has0false feasible,0false infeasible and12/12 exact selections '
        'relative to this restricted domain. Mean over-provision versus restricted empirical minimum is0physical steps. '
        'Mean additional steps relative to the optimistic zero-margin model is14.583 (max35), a different comparison. '
        'Thus a small safety margin resolves the tested DIRECT subset, an important practical counterargument.', '',
        'FULL-7 M4:630/792 remain N/A; five-frequency endpoint false feasible becomes0at10%, '
        'but12minimum-frequency decisions and their over-provision costs remain UNKNOWN. '
        'The requested binary FULL-7 flag is PRACTICAL_GAP_REMAINS with UNEVALUABLE coverage, '
        'not evidence that small margins fail. Do not present this as stronger practical model-gap evidence.', '',
        'All secondary inference profiles are independent of target raw traces. The K6->K8 and unlocked frontend '
        'transfer assumptions limit the model class tested. No universal claim about conventional models is supported.']
    with (output/'SECONDARY.md').open('x') as f:f.write('\n'.join(text)+'\n')
    model.write_json(output,'cpu_verification.json',dict(status='PASS',provenance='SYNTHETIC_CPU_CHECKS_NOT_MEASUREMENTS',
        checks=['Known D/D/2 overload slope40frames/s','Stable below service capacity','Missing lower frequency yields UNKNOWN',
                'Interior bracket excluded','Target trace predictor firewall'],GPU_executed=False,network_executed=False))
    print('CPU tests and secondary coverage supplement PASS')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=Path('results/gate0_model_ladder'))
    p.add_argument('--output',type=Path,default=Path('results/gate0_model_ladder/secondary_detail01'))
    args=p.parse_args();main(args.source,args.output)
