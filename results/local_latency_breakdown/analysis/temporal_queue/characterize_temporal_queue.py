#!/usr/bin/env python3
"""Offline raw-ns characterization; never imports a profiler or GPU library.

All new tables/reports live beside this script. Only the explicitly named final
PNG figures are written outside that directory. Existing result tables are read.
"""
from pathlib import Path
import argparse, csv, hashlib, json, math, os
import numpy as np

OUT=Path(__file__).resolve().parent
ANALYSIS=OUT.parent
ROOT=ANALYSIS.parent
REPO=ROOT.parents[1]
FIG=ANALYSIS/'figures'

def load(p):return json.loads(p.read_text())
def csvread(p):
    with p.open(newline='') as f:return list(csv.DictReader(f))
def writejson(name,value):
    with (OUT/name).open('x') as f:json.dump(value,f,indent=2,allow_nan=False)
def writecsv(name,rows):
    assert rows
    with (OUT/name).open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def avg(x):return float(np.mean(x))
def quant(x,p):return float(np.percentile(x,p,method='linear'))
def longest_true(mask):
    best=current=0
    for yes in mask:
        current=current+1 if yes else 0;best=max(best,current)
    return best
def ranks(x):
    _,inverse,counts=np.unique(x,return_inverse=True,return_counts=True)
    return (np.cumsum(counts)-(counts-1)/2)[inverse]
def correlation(x,y):
    assert np.std(x)>0 and np.std(y)>0
    return float(np.corrcoef(x,y)[0,1])
def aggregate(rows,group_fields,excluded):
    result=[]
    keys=sorted({tuple(r[f] for f in group_fields) for r in rows})
    for key in keys:
        group=[r for r in rows if tuple(r[f] for f in group_fields)==key]
        assert len(group)==5 and {r['run_id'] for r in group}=={f'run{i:02d}' for i in range(1,6)}
        result.extend(group)
        metrics=[m for m in group[0] if m not in excluded]
        for kind,fn in [('mean',avg),('sample_sd',lambda x:float(np.std(x,ddof=1))),('min',min),('max',max)]:
            r={**dict(zip(group_fields,key)),'row_type':kind,'run_id':'ALL','run_count':5}
            r.update({m:float(fn([g[m] for g in group])) for m in metrics});result.append(r)
    return result

def analyze():
    expected={(k,f'run{i:02d}') for k in range(1,8) for i in range(1,6)}
    runpaths=sorted(p for k in range(1,8) for p in (ROOT/f'k{k}').iterdir() if p.is_dir())
    assert {(int(p.parent.name[1:]),p.name) for p in runpaths}==expected
    assert len(runpaths)==len(list(ROOT.glob('k*/run*/per_frame.csv')))==35
    summary={(int(r['K']),r['run_id']):r for r in csvread(ROOT/'per_run_summary.csv')}
    ready=[];demand=[];carry=[];depth_wait=[];integrity=[]
    for k,runid in sorted(expected):
        path=ROOT/f'k{k}'/runid;raw=load(path/'raw_ns.json');t0=raw['t0_ns'];records=raw['records']
        nframes=k*1800
        assert len(records)==nframes
        framecsv=csvread(path/'per_frame.csv');assert len(framecsv)==nframes
        for stream in range(k):
            assert sorted(r['frame_id'] for r in records if r['stream_id']==stream)==list(range(1800))
            assert sorted(int(r['frame_id']) for r in framecsv if int(r['stream_id'])==stream)==list(range(1800))
        validation=load(path/'validation.json')
        assert validation['validation']=='PASS' and not validation['errors']
        assert all(validation['counts'][m]==nframes for m in ('arrivals','source_samples','preprocessed','completions','per_frame_rows'))
        for r in records:
            assert all(type(r[m]) is int for m in ('a_ns','b_ns','r_ns','s_ns','c_ns'))
            assert r['a_ns']<=r['b_ns']<=r['r_ns']<=r['s_ns']<=r['c_ns']
            assert r['a_ns']==t0+r['frame_id']*1_000_000_000//30
            assert (r['c_ns']-r['a_ns'])==sum(r[y]-r[x] for x,y in [('a_ns','b_ns'),('b_ns','r_ns'),('r_ns','s_ns'),('s_ns','c_ns')])
        arr={m:np.array([r[m] for r in records],dtype=np.int64) for m in ('a_ns','r_ns','s_ns','c_ns','frame_id','inference_queue_depth_before_enqueue')}
        assert np.all(arr['inference_queue_depth_before_enqueue']>=0)
        assert all(x['c_ns']<=y['s_ns'] for x,y in zip(records,records[1:]))
        byid={(r['stream_id'],r['frame_id']):r for r in records}
        for row in framecsv:
            r=byid[int(row['stream_id']),int(row['frame_id'])]
            assert float(row['inference_queue_wait_ms'])==(r['s_ns']-r['r_ns'])/1e6
            assert int(row['inference_queue_depth_before_enqueue'])==r['inference_queue_depth_before_enqueue']
        ordered=sorted(records,key=lambda r:(r['frame_id'],r['stream_id']))
        mat={m:np.array([r[m] for r in ordered],dtype=np.int64).reshape(1800,k) for m in ('r_ns','s_ns','c_ns')}
        boundaries=t0+np.arange(1801,dtype=np.int64)*1_000_000_000//30
        lengths=np.diff(boundaries)
        spans=mat['r_ns'].max(axis=1)-mat['r_ns'].min(axis=1)
        span_pct=100*spans/lengths
        rr={'K':k,'row_type':'run','run_id':runid,'run_count':1,
            'period_count':1800,'ready_span_mean_ms':avg(spans)/1e6,
            'ready_span_median_ms':quant(spans,50)/1e6,'ready_span_p95_ms':quant(spans,95)/1e6,
            'ready_span_period_mean_pct':avg(span_pct),'ready_span_period_p95_pct':quant(span_pct,95),
            'first_ready_lag_mean_ms':avg(mat['r_ns'].min(axis=1)-boundaries[:-1])/1e6,
            'ready_span_after_first_1s_mean_ms':avg(spans[30:])/1e6,
            'ready_span_after_first_1s_p95_ms':quant(spans[30:],95)/1e6}
        ready.append(rr)
        sums=(mat['c_ns']-mat['s_ns']).sum(axis=1)
        over=sums*30>1_000_000_000
        demand.append({'K':k,'row_type':'run','run_id':runid,'run_count':1,'period_count':1800,
            'period_inference_service_sum_mean_ms':avg(sums)/1e6,
            'period_inference_service_sum_median_ms':quant(sums,50)/1e6,
            'period_inference_service_sum_p95_ms':quant(sums,95)/1e6,
            'period_inference_service_sum_p99_ms':quant(sums,99)/1e6,
            'periods_service_sum_over_33p33ms':int(over.sum()),
            'period_service_sum_over_33p33_pct':avg(over)*100,
            'period_service_sum_after_first_1s_mean_ms':avg(sums[30:])/1e6,
            'period_service_sum_after_first_1s_over_period_pct':avg(over[30:])*100})
        wait_depth=[];service_depth=[];pre_depth=[]
        for boundary in boundaries[1:]:
            # Strict older-frame filter excludes jobs whose a equals this boundary.
            older=arr['a_ns']<boundary
            waiting=older & (arr['r_ns']<=boundary) & (boundary<arr['s_ns'])
            service=older & (arr['s_ns']<=boundary) & (boundary<arr['c_ns'])
            preready=older & (boundary<arr['r_ns'])
            nw,ni,npready=int(waiting.sum()),int(service.sum()),int(preready.sum())
            assert ni<=1
            assert nw+ni+npready==int((older & (boundary<arr['c_ns'])).sum())
            wait_depth.append(nw);service_depth.append(ni);pre_depth.append(npready)
        for scope,start in [('all_60s',0),('first_1s_excluded',30)]:
            w=np.array(wait_depth[start:],dtype=np.int64);s=np.array(service_depth[start:],dtype=np.int64)
            pre=np.array(pre_depth[start:],dtype=np.int64);unfinished=w+s
            carry.append({'K':k,'scope':scope,'row_type':'run','run_id':runid,'run_count':1,
                'period_count':len(w),'periods_with_waiting_carryover':int((w>0).sum()),
                'waiting_carryover_period_pct':avg(w>0)*100,
                'periods_with_inservice_carryover':int((s>0).sum()),
                'inservice_carryover_period_pct':avg(s>0)*100,
                'periods_with_inference_unfinished_carryover':int((unfinished>0).sum()),
                'inference_unfinished_carryover_period_pct':avg(unfinished>0)*100,
                'mean_waiting_carryover_depth':avg(w),'p95_waiting_carryover_depth':quant(w,95),
                'max_waiting_carryover_depth':int(w.max()),'mean_inservice_carryover_depth':avg(s),
                'max_inservice_carryover_depth':int(s.max()),'mean_inference_unfinished_depth':avg(unfinished),
                'p95_inference_unfinished_depth':quant(unfinished,95),'max_inference_unfinished_depth':int(unfinished.max()),
                'maximum_consecutive_inference_unfinished_carryover_periods':longest_true(unfinished>0),
                'pre_ready_carryover_period_pct':avg(pre>0)*100,
                'mean_pre_ready_carryover_depth':avg(pre),'max_pre_ready_carryover_depth':int(pre.max())})
        if k in (5,6,7):
            depth=arr['inference_queue_depth_before_enqueue'];wait=arr['s_ns']-arr['r_ns']
            groups=depth if k in (5,6) else depth//50
            for g in np.unique(groups):
                subset=wait[groups==g]
                label=str(int(g)) if k in (5,6) else f'[{int(g)*50},{(int(g)+1)*50})'
                for metric,value,unit in [('frame_count',len(subset),'frames'),('wait_mean_ms',avg(subset)/1e6,'ms'),('wait_median_ms',quant(subset,50)/1e6,'ms'),('wait_p95_ms',quant(subset,95)/1e6,'ms')]:
                    depth_wait.append({'K':k,'row_type':'run','run_id':runid,'depth_group':label,
                        'group_definition':'exact_depth' if k in (5,6) else '50_frame_bin_left_closed',
                        'run_count_present':1,'metric':metric,'value':value,'unit':unit})
            for metric,value in [('Pearson',correlation(depth,wait)),('Spearman',correlation(ranks(depth),ranks(wait)))]:
                depth_wait.append({'K':k,'row_type':'run','run_id':runid,'depth_group':'ALL',
                    'group_definition':'all_depths_within_run','run_count_present':1,
                    'metric':metric,'value':value,'unit':'correlation'})
        integrity.append({'K':k,'run_id':runid,'frame_count':nframes,'raw_ns_available':True,
            'frame_IDs':'PASS','counts':'PASS','timing_order':'PASS','decomposition_error_ns':0,
            'carryover_category_partition':'PASS','inservice_depth_le_one':'PASS'})
        print(f'K{k}/{runid}: {nframes} frames, raw-ns temporal characterization complete',flush=True)
    assert sum(r['frame_count'] for r in integrity)==252000
    excluded={'K','scope','row_type','run_id','run_count'}
    ready_all=aggregate(ready,['K'],excluded);demand_all=aggregate(demand,['K'],excluded)
    carry_all=aggregate(carry,['K','scope'],excluded)
    # Conditional distributions first within run; aggregate only runs with that depth.
    depth_all=list(depth_wait)
    for k,label,definition,metric,unit in sorted({(r['K'],r['depth_group'],r['group_definition'],r['metric'],r['unit']) for r in depth_wait}):
        vals=[r['value'] for r in depth_wait if (r['K'],r['depth_group'],r['metric'])==(k,label,metric)]
        for kind,fn in [('mean',avg),('sample_sd',lambda x:float(np.std(x,ddof=1))),('min',min),('max',max)]:
            if kind=='sample_sd' and len(vals)<2:continue
            depth_all.append({'K':k,'row_type':kind,'run_id':'ALL','depth_group':label,'group_definition':definition,
                'run_count_present':len(vals),'metric':metric,'value':float(fn(vals)),'unit':unit})
    for name,rows in [('ready_span_summary.csv',ready_all),('period_service_demand_summary.csv',demand_all),('carryover_summary.csv',carry_all),('queue_depth_wait_summary.csv',depth_all)]:writecsv(name,rows)
    writejson('temporal_data.json',{'ready':ready_all,'service':demand_all,'carry':carry_all,'depth_wait':depth_all,
        'integrity':integrity,'formal_summary':[dict(r,K=int(r['K'])) for r in csvread(ROOT/'motivation_summary.csv')],
        'run_summary':[dict(r,K=int(r['K'])) for r in summary.values()],
        'boundary_definition':'B_m=t0+floor(m*1e9/30); test B_(n+1) for n=0..1799; include only a<B',
        'startup_definition':'all: n=0..1799 (1800 boundaries); excluded: n=30..1799 (1770 boundaries); retain ALL older frames including jobs scheduled before 1s',
        'timestamp_source':'raw_ns.json integer a_ns/r_ns/s_ns/c_ns; no ms reconstruction',
        'service_over_period_rule':'period_service_sum_ns*30 > 1000000000',
        'ready_span_period_pct':'100*ready_span_ns/(B_(n+1)-B_n); integer boundary lengths 33333333 or 33333334 ns'})
    print('ANALYSIS PASS; four data CSVs written. No figure replacement performed yet.')

def row(d,section,k,kind='mean',scope=None):
    return next(r for r in d[section] if r['K']==k and r['row_type']==kind and (scope is None or r['scope']==scope))
def fmt(x,places=3):return f'{float(x):,.{places}f}'
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,r))+' |' for r in rows])+'\n'

def report():
    d=load(OUT/'temporal_data.json')
    r5,r6=[row(d,'ready',k) for k in (5,6)]
    s5,s6=[row(d,'service',k) for k in (5,6)]
    c5,c6=[row(d,'carry',k,scope='first_1s_excluded') for k in (5,6)]
    formal={r['K']:r for r in d['formal_summary']}
    # These are interpretations of the observed comparisons, not a significance test.
    assert r6['ready_span_mean_ms']>r5['ready_span_mean_ms']
    assert r6['ready_span_p95_ms']>r5['ready_span_p95_ms']
    assert s6['period_inference_service_sum_mean_ms']>s5['period_inference_service_sum_mean_ms']
    assert c6['inference_unfinished_carryover_period_pct']>c5['inference_unfinished_carryover_period_pct']
    hypotheses=[
        {'hypothesis':'H1','status':'NOT SUPPORTED','interpretation':'K6 ready span is wider on the five-run mean, not more concentrated; overlapping run ranges preclude a claim of universal broadening.',
         'ready_evidence':'mean 3.195 -> 3.789 ms; p95 4.850 -> 6.026 ms',
         'demand_evidence':'mean observed service sum 23.119 -> 29.419 ms',
         'carryover_evidence':'after first 1s: unfinished 17.006% -> 100%',
         'queue_wait_evidence':'mean 8.975 -> 25.778 ms','claim_limit':'No controlled phase experiment; no causal clustering claim.'},
        {'hypothesis':'H2','status':'SUPPORTED','interpretation':'Supported as an observational demand/carry-over explanation: both ready spans occupy a small fraction of the period, but K6 is modestly wider, not statistically established equivalent.',
         'ready_evidence':'mean span / period 9.586% -> 11.367%; no tighter ready span at K6',
         'demand_evidence':'mean service sum rises 27.246% with one more stream and a 6.038% service-mean rise',
         'carryover_evidence':'after first 1s: waiting 0.068% -> 54.418%; in-service 16.983% -> 98.678%; unfinished 17.006% -> 100%',
         'queue_wait_evidence':'mean 8.975 -> 25.778 ms','claim_limit':'H2 does not establish equal ready distributions, independent causal effects, or system capacity.'},
        {'hypothesis':'H3','status':'NOT SUPPORTED','interpretation':'The proposed simultaneous H1+H2 explanation lacks support for its stronger-concentration component.',
         'ready_evidence':'K6 mean and p95 ready spans broaden',
         'demand_evidence':'observed period demand increases',
         'carryover_evidence':'unfinished inference carry-over increases beyond startup',
         'queue_wait_evidence':'mean queue wait increases','claim_limit':'Concurrent changes are associations, not proof of arrival-clustering causation.'}]
    # Format the measured relative changes from the already computed statistics.
    demand_change=(s6['period_inference_service_sum_mean_ms']/s5['period_inference_service_sum_mean_ms']-1)*100
    service_change=(float(formal[6]['inference_mean_ms'])/float(formal[5]['inference_mean_ms'])-1)*100
    hypotheses[1]['demand_evidence']=f'mean service sum rises {demand_change:.3f}% with one more stream and a {service_change:.3f}% service-mean rise'
    writecsv('k5_k6_explanation.csv',hypotheses)
    text=[]
    def add(s):text.append(s.strip()+'\n')
    add('''# K5→K6 temporal inference queue characterization

K5→K6에서 queue wait가 증가한 현상은 **더 강해진 ready-time concentration보다, 늘어난 period별 observed service demand와 훨씬 빈번한 inference-stage carry-over의 동반 변화**로 설명하는 것이 현재 데이터에 맞다. Ready span의 5-run mean과 p95는 오히려 넓어진다. 이는 observational characterization이며 phase를 조작한 causal experiment가 아니다.

## 입력과 범위

기존 formal 35 runs / 252,000 frames만 사용했다. K5는 run별 9,000 frames × 5, K6는 10,800 frames × 5다. 모든 stream의 frame_id 0…1799 exactly once, per_frame rows, saved count validation, raw-ns ordering와 decomposition을 검증했다. 35개 raw_ns.json 모두 존재하며 **a_ns/r_ns/s_ns/c_ns integer 값을 직접 사용**했다. MS component 합으로 ready time을 복원하지 않았다. b_ns는 ordering/decomposition 검증에만 추가로 사용했다.

Measurement code, formal raw/summary, 이전 CSV/JSON/MD, 기존 smoke와 baseline은 변경하지 않았다. 입력 snapshot의 SHA256/size/mtime_ns 및 파일 집합을 마지막에 대조한다. 신규 benchmark, smoke, GPU inference, phase-stagger, server/network, graph split, counterfactual replay/simulation은 실행하지 않았다.

## 정의와 집계

- `B_m = t0 + floor(m × 10^9 / 30)`이며 period n의 boundary는 `B_(n+1)`이다. 계산은 integer ns로 한다.
- **전체 60초:** n=0…1799, boundary B1…B1800, run별 1,800개. B1800=60초의 마지막 endpoint를 포함한다.
- **첫 1초 제외:** scheduled period n=30…1799, boundary B31…B1800, run별 1,770개. 이때도 boundary 이전에 scheduled된 **모든 older frame**을 센다. 첫 1초에 scheduled되어 아직 남은 work를 버리지 않는다.
- Older frame은 `a_j < B`로 제한한다. 새 boundary와 a가 정확히 같은 새 period frame은 제외한다.
- Waiting: older ∩ `r_j ≤ B < s_j`; in-service: older ∩ `s_j ≤ B < c_j`; unfinished inference stage: 두 depth의 합이다.
- Pre-ready: older ∩ `a_j ≤ B < r_j`. Inference-stage unfinished에 포함하지 않는다.
- 한 boundary에서 waiting과 in-service가 동시에 존재할 수 있다. 따라서 **unfinished period %는 두 percentage의 합이 아니라 union의 비율**이다. Depth는 더할 수 있다.
- Maximum consecutive unfinished periods는 **연속된 boundary 관측**의 최대 길이다. Boundary 사이 모든 순간에 queue가 비어 있지 않다는 뜻이 아니다.
- Ready span은 동일 n에서 생성된 K개 frame의 `max(r)-min(r)`이다. Ratio는 `100×span_ns/(B_(n+1)-B_n)`이며 period 길이는 33,333,333 또는 33,333,334 ns다. Inter-ready gap을 clustering 지표로 사용하지 않았다.
- Service demand는 같은 n의 K개 `(c-s)` 합이다. Exact 1/30초 초과 판정은 `sum_ns×30 > 10^9`다. Period 길이와 service capacity를 동일시하지 않는다.
- 각 run statistic을 먼저 계산하고 K별 5개 값의 arithmetic mean/sample SD(n−1)/min/max를 계산한다. Pooled percentile/correlation을 대표값으로 사용하지 않는다. Percentile은 linear interpolation이다.
''')
    add('## 1. Ready timing: K6은 더 좁게 몰리지 않는다')
    ready_metrics=['ready_span_mean_ms','ready_span_median_ms','ready_span_p95_ms','ready_span_period_mean_pct','ready_span_period_p95_pct']
    add(table(['K','Run/stat','Mean ms','Median ms','p95 ms','Mean period %','p95 period %'],[
        [r['K'],r['run_id'] if r['row_type']=='run' else r['row_type']]+[fmt(r[m]) for m in ready_metrics]
        for r in d['ready'] if r['K'] in (5,6)]))
    add(table(['Reference K','Mean span ms','p95 span ms','Mean period %'],[
        [k,fmt(row(d,'ready',k)['ready_span_mean_ms']),fmt(row(d,'ready',k)['ready_span_p95_ms']),fmt(row(d,'ready',k)['ready_span_period_mean_pct'])] for k in (4,7)]))
    add(f'''K5→K6 span mean은 {fmt(r5['ready_span_mean_ms'])}→{fmt(r6['ready_span_mean_ms'])} ms (+{fmt((r6['ready_span_mean_ms']/r5['ready_span_mean_ms']-1)*100,2)}%), p95는 {fmt(r5['ready_span_p95_ms'])}→{fmt(r6['ready_span_p95_ms'])} ms다. 두 K 모두 ready span이 period의 작은 부분에 모이지만 K6의 span은 평균적으로 넓다. 최종 표기는 **LESS CLUSTERED (ready-span 기준의 기술적 비교)**다.

Run 간 범위가 겹치고 모든 run pair가 같은 방향은 아니다. K5 run02의 span mean은 4.539 ms로 해당 K6 run02의 4.257 ms보다 넓다. 따라서 population 차이나 모든 run에서의 broadening을 입증했다고 말하지 않는다. 특히 “K6 inter-ready gap이 작으므로 더 bursty하다”는 추론을 하지 않았다.

첫 1초 제외 후에도 ready span mean은 {fmt(r5['ready_span_after_first_1s_mean_ms'])}→{fmt(r6['ready_span_after_first_1s_mean_ms'])} ms, p95는 {fmt(r5['ready_span_after_first_1s_p95_ms'])}→{fmt(r6['ready_span_after_first_1s_p95_ms'])} ms로 같은 방향이다. “Concentration이 비슷하다”는 말은 양쪽 모두 수 ms/period의 작은 비율이라는 정성적 표현일 뿐 distribution equivalence를 검증한 결과가 아니다.''')
    add('## 2. Period inference service demand')
    demand_metrics=['period_inference_service_sum_mean_ms','period_inference_service_sum_median_ms','period_inference_service_sum_p95_ms','period_inference_service_sum_p99_ms','periods_service_sum_over_33p33ms','period_service_sum_over_33p33_pct']
    add(table(['K','Run/stat','Mean ms','Median ms','p95 ms','p99 ms','Over-period count','Over-period %'],[
        [r['K'],r['run_id'] if r['row_type']=='run' else r['row_type']]+[fmt(r[m]) for m in demand_metrics]
        for r in d['service'] if r['K'] in (5,6)]))
    add(table(['Reference K','Service sum mean ms','p95 ms','Over-period %'],[
        [k]+[fmt(row(d,'service',k)[m]) for m in ('period_inference_service_sum_mean_ms','period_inference_service_sum_p95_ms','period_service_sum_over_33p33_pct')] for k in (4,7)]))
    add(f'''Mean inference service는 {float(formal[5]['inference_mean_ms']):.3f}→{float(formal[6]['inference_mean_ms']):.3f} ms로 {service_change:.2f}% 증가했다. 완전히 동일하지 않지만 per-frame 변화는 작다. 반면 stream/frame 수가 period당 5→6으로 20% 늘어 **service 합은 {s5['period_inference_service_sum_mean_ms']:.3f}→{s6['period_inference_service_sum_mean_ms']:.3f} ms (+{demand_change:.2f}%)**가 된다. 산술적으로 `6×mean_service_K6` 대 `5×mean_service_K5`의 비교이며 두 변화를 독립적인 causal effect로 분해한 것은 아니다.

33.333… ms를 초과하는 service sum의 period 비율은 {s5['period_service_sum_over_33p33_pct']:.3f}%→{s6['period_service_sum_over_33p33_pct']:.3f}%다. 첫 1초 제외 후에도 {s5['period_service_sum_after_first_1s_over_period_pct']:.3f}%→{s6['period_service_sum_after_first_1s_over_period_pct']:.3f}%로 차이가 남는다.

**Service sum < period는 그 period 안에 완료할 수 있다는 뜻이 아니다.** First-ready lag mean도 K5 {r5['first_ready_lag_mean_ms']:.3f} ms, K6 {r6['first_ready_lag_mean_ms']:.3f} ms다. 즉 inference는 logical period 시작부터 모든 frame을 즉시 처리할 수 없다. 서로 다른 frame의 ready 시점, 기존 work, service 사이 간격도 영향을 준다. 이 평균들만 더해서 개별 period의 feasibility를 판정하지 않았다. Service demand를 system capacity로 부르지 않는다.''')
    add('## 3. Carry-over: waiting / in-service / pre-ready 분리')
    cm=['waiting_carryover_period_pct','inservice_carryover_period_pct','inference_unfinished_carryover_period_pct','maximum_consecutive_inference_unfinished_carryover_periods','pre_ready_carryover_period_pct']
    for scope in ('all_60s','first_1s_excluded'):
        add('### '+scope)
        add(table(['K','Run/stat','Waiting %','In-service %','Unfinished %','Longest consecutive periods','Pre-ready %'],[
            [r['K'],r['run_id'] if r['row_type']=='run' else r['row_type']]+[fmt(r[m]) for m in cm]
            for r in d['carry'] if r['K'] in (5,6) and r['scope']==scope]))
    add(table(['K','Scope','Mean waiting depth','p95 waiting depth','Mean in-service depth','Mean unfinished depth','p95 unfinished depth','Max unfinished depth mean'],[
        [r['K'],r['scope']]+[fmt(r[m]) for m in ('mean_waiting_carryover_depth','p95_waiting_carryover_depth','mean_inservice_carryover_depth','mean_inference_unfinished_depth','p95_inference_unfinished_depth','max_inference_unfinished_depth')]
        for r in d['carry'] if r['K'] in (4,5,6,7) and r['row_type']=='mean']))
    add('''K5は first 1s 이후 waiting carry-over가 약 0.068%인 반면 in-service carry-over는 16.983%다. 따라서 “waiting queue가 경계에서 거의 비었다”와 “이전 inference work가 전부 완료됐다”는 같은 말이 아니다. K6에서는 waiting이 54.418%, in-service가 98.678%, 두 상태의 union이 100%다. Pre-ready는 두 K 모두 first 1s 제외 후 0%이므로 이 결과를 아직 inference-ready가 되지 않은 이전 frame 수와 혼동하지 않는다.

K6의 1,770개 post-startup boundary 모두 unfinished work가 있다는 것은 **startup-only가 아님**을 보여 준다. 그러나 매 순간 queue가 nonempty이거나 backlog가 끝없이 증가한다는 뜻은 아니다. 이전 timeline에서 K6은 후반부 낮은 주기적 queue로 회복했고, 이번 post-startup mean unfinished depth는 3.935다. K7은 같은 metric이 824.381이며 waiting 자체가 모든 post-startup boundary에서 남는 sustained-backlog reference다. Longest-consecutive 값과 growing queue depth를 구분해야 한다.
'''.replace('K5は','K5는'))
    add('## 4. Queue depth별 wait distribution')
    add('''`queue_depth_wait_summary.csv`는 long format이다. K5/K6는 exact integer depth, K7은 [0,50), [50,100), …의 50-frame bin을 사용한다. 각 run/depth에 frame_count, wait_mean_ms, wait_median_ms, wait_p95_ms를 기록한다. 그 뒤 depth가 존재하는 run들의 statistic mean/sample SD/min/max와 run_count_present를 기록한다. 해당 depth가 없는 run의 wait를 0으로 대체하지 않는다. 존재하는 run이 하나뿐이면 정의되지 않는 sample SD 행을 생략한다. Frame-count 평균도 present runs 기준이며 전체 count 확인은 각 run의 frame_count 행을 사용한다.

아래는 exact-depth 조건부 분포 중 일부다. 전체 depth와 모든 run 값은 CSV에 보존했다. n_runs가 5보다 작은 high-depth 값을 5-run formal statistic처럼 해석하지 않는다.
''')
    distribution=[]
    for k in (5,6):
        for depth in (0,1,2,3,4,5,10,20,30):
            rs={r['metric']:r for r in d['depth_wait'] if r['K']==k and r['depth_group']==str(depth) and r['row_type']=='mean'}
            if rs:distribution.append([k,depth,rs['frame_count']['run_count_present']]+[fmt(rs[m]['value']) for m in ('frame_count','wait_mean_ms','wait_median_ms','wait_p95_ms')])
    add(table(['K','Depth','n_runs','Mean frame count/run','Wait mean ms','Median ms','p95 ms'],distribution))
    corr=[r for r in d['depth_wait'] if r['depth_group']=='ALL']
    add(table(['K','Run/stat','Correlation','Value'],[[r['K'],r['run_id'] if r['row_type']=='run' else r['row_type'],r['metric'],fmt(r['value'],6)] for r in corr]))
    add('''Pearson/Spearman은 run 안에서 먼저 계산한 뒤 5개 coefficient의 arithmetic mean을 보고한다. Spearman은 tied depth/wait에 average ranks를 사용한다. K5와 K6 모두 depth가 클수록 대체로 wait가 길어지는 강한 association이 관측된다. 그러나 high-depth 표본은 startup/긴 carry-over episode에 편중될 수 있고 일부 depth의 표본 수가 매우 작다. 모든 조건부 quantile이 strictly monotonic이라는 주장이나 correlation의 causal 해석은 하지 않는다.

Depth=0에서도 wait가 0일 필요는 없다. Pre-enqueue depth는 service 중인 frame을 제외하므로 이미 진행 중인 service의 잔여시간 또는 handoff 지연을 기다릴 수 있다. 이 정의를 바꾸지 않았다.
''')
    add('## 5. Hypotheses')
    add(table(['Hypothesis','판정','의미'],[[r['hypothesis'],r['status'],r['interpretation']] for r in hypotheses]))
    add('''H2의 SUPPORTED는 **“강한 concentration 증가 없이 demand/carry-over 증가가 동반된다”는 observational 설명**에 대한 판정이다. Ready distribution이 통계적으로 같다고 입증했다는 뜻은 아니다. 실제 span은 평균적으로 넓어졌으므로 “timing concentration remained identical”라고 쓰면 안 된다. H1/H3의 tighter-clustering 주장은 지지되지 않는다.
''')
    add('## 6. Four required questions')
    add('''**Q1. Ready timing은 어떻게 다른가?** K5→K6 mean span은 3.195→3.789 ms, median 3.055→3.449 ms, p95 4.850→6.026 ms다. Period 대비 mean span도 9.586→11.367%다. 양쪽 모두 수 ms에 ready가 모이지만 K6가 더 좁게 집중됐다는 증거는 없다. Run 간 겹침을 감안한 descriptive broadening이다.

**Q2. 한 period가 생성하는 observed service demand는 얼마나 늘었는가?** Mean 23.119→29.419 ms, +6.299 ms (+27.25%). Mean service는 약 6.04% 증가했고 frame 수가 20% 증가한 결과다. p95는 25.800→33.331 ms, period 초과 비율은 0.100→5.567%다. 이 합이 period보다 작아도 ready 이후에만 처리할 수 있으므로 intra-period completion을 보장하지 않는다.

**Q3. 이전 inference-stage work가 얼마나 자주 남는가?** 전체 60초에서 K5 waiting/in-service/unfinished 비율은 1.389/17.967/18.067%, K6은 54.922/98.433/99.744%다. 첫 1초 제외 후에는 K5 0.068/16.983/17.006%, K6 54.418/98.678/100.000%다. Waiting/in-service를 구분했고 pre-ready를 합치지 않았다.

**Q4. Unfinished carry-over 증가와 queue wait 증가가 함께 관측되는가?** YES. Post-startup mean unfinished depth는 0.171→3.935 frames, mean queue wait는 8.975→25.778 ms다. 각각 boundary-based post-startup metric과 full-run frame metric이므로 같은 denominator라고 혼동하지 않는다. 기존 formal 후반부/새 carry-over split도 startup만의 설명을 배제한다. 이러한 동반 변화는 causal attribution의 완결된 증명은 아니다.
''')
    add('## 7. Claim strength와 paper wording')
    add('''**LEVEL 1: SUPPORTED.** Queue wait의 mean E2E 비율은 K5 34.88%, K6 59.10%, K7 99.54%다. K5→K6 E2E mean 증가의 93.92%가 queue wait 증가다. 이는 기존 mean decomposition을 인용한 것이며 component p95를 합산하지 않는다.

**LEVEL 2: SUPPORTED.** Ready timing, 늘어난 period inference demand, inter-period unfinished work가 큰 queue wait와 함께 관측된다.

**LEVEL 3: NOT PROVEN.** Arrival clustering이 deadline miss를 유발했다고 확정할 controlled phase experiment를 수행하지 않았다. Demand/ready distribution/service variation/host effects를 독립적으로 조작하지 않았으므로 각각의 causal 기여는 식별하지 못한다. 기존 raw가 설명하는 association의 범위 안에서 주장한다.

**English:** From K=5 to K=6, the mean inference-ready span widened from 3.20 to 3.79 ms, while observed inference service demand per logical period increased from 23.12 to 29.42 ms. Excluding the first second, unfinished inference work was present at 17.01% versus 100% of subsequent period boundaries, alongside an increase in full-run mean queue wait from 8.98 to 25.78 ms. These observations support an association between increased per-period demand, inter-period carry-over, and queue buildup, rather than stronger ready-time concentration at K=6; they do not establish a causal effect of arrival clustering.

**Korean:** K5에서 K6로 증가할 때 inference-ready span 평균은 3.20에서 3.79 ms로 넓어졌지만, logical period당 observed inference service demand는 23.12에서 29.42 ms로 증가했다. 첫 1초를 제외한 period boundary에서 이전 inference work가 남는 비율은 17.01%에서 100%로 증가했으며, 전체 run의 평균 queue wait도 8.98에서 25.78 ms로 증가했다. 이는 K6의 더 강한 ready-time 집중보다 증가한 period demand와 carry-over가 queue buildup과 연관된다는 설명을 지지하며, arrival clustering의 causal effect를 입증하지는 않는다.
''')
    add('## 8. 최종 논문 figure: PNG 3개')
    add('''[Figure 1](../figures/figure_1_local_qos_knee.png): (a) K별 mean-of-run E2E mean/p95와 candidate deadline, (b) mean-of-run miss percentage. K7 scale 때문에 (a)는 log y축이다. Error bar는 5-run sample SD, 개별 run line/point는 없다.

[Figure 2](../figures/figure_2_latency_decomposition.png): 5-run K-level mean 4개 component의 additive stacked bar. K1–K6와 K7을 서로 다른 linear y축 panel로 나눠 작은 항과 K7의 크기를 동시에 읽을 수 있게 했다. 두 y축 모두 ms이며 percentile을 쌓지 않는다. Variability overlay는 없다.

[Figure 3](../figures/figure_3_k5_k6_temporal_queue.png): K5/K6의 (a) ready span mean, (b) observed per-period service sum mean, (c) unfinished inference carry-over period %. 세 panel 모두 전체 60초 metric이고 error bar는 5-run sample SD다. Panel (b)의 33.333… ms line은 **frame-period reference**, service capacity가 아니다. Startup 제외 결과는 위 표에 별도로 보존한다.

세 PNG는 350 dpi로 저장한다. 개별 run trace/scatter/cloud는 표시하지 않는다. 이전 A–H PNG/PDF는 삭제 대상으로 지정되었으며 기존 CSV/JSON/MD의 수치는 그대로 보존한다. 이전 analysis_report.md와 figure_manifest.json은 historical 분석 기록이므로 삭제된 A–H를 가리키는 링크/목록이 남을 수 있다. 현재 논문 figure의 기준은 이 report의 Figure 1–3이다. 이전 report/manifest를 재작성하거나 원본 CSV를 수정하지 않았다.
''')
    add('## 9. 재현과 검증')
    add('''단일 `characterize_temporal_queue.py`는 `analyze`(raw 읽기), `report`(이미 계산된 temporal data의 표/해석), `figures`(PNG 3개), `validate`(파일/집계/보존 검증) mode를 제공한다. 파일은 exclusive creation하므로 기존 산출물이 있으면 덮어쓰지 않는다. Python script에 figure 삭제나 Git commit/push 명령은 없다. 삭제와 Git 작업은 명시적인 allowlist로 별도 수행한다.

CSV는 `ready_span_summary.csv`, `period_service_demand_summary.csv`, `carryover_summary.csv`, `queue_depth_wait_summary.csv`, `k5_k6_explanation.csv`다. Run-level 값 및 mean/sample SD/min/max를 포함한다. 추가 로컬 JSON은 input preservation과 offline intermediate/validation evidence이고 raw frame을 Git에 추가하지 않는다.

검증은 NaN/inf/중복 key 없음, K5/K6 각각 5개 run, per-stream IDs, boundary category partition, in-service depth≤1, 5-run aggregate, 원본 SHA256/size/mtime/file count 동일성, 최종 figure PNG=3/PDF=0을 확인한다. 이 과정에서 새로운 workload는 실행하지 않는다.

## 다음 단계

**RT-DETR graph split feasibility analysis로 진행 가능: YES.** Local motivation에 필요한 queue dominance와 demand/carry-over association이 정리되었다. 특정 split/offloading의 이득을 입증한 것은 아니므로 다음 단계는 구조적 feasibility와 비용 분석이다. Level 3 causal claim이 반드시 필요한 경우에만 별도 승인된 controlled phase experiment가 필요하다. 이번 task에서는 어떤 phase/partition experiment도 수행하지 않았다.
''')
    with (OUT/'temporal_queue_report.md').open('x') as f:f.write('\n'.join(text))
    print('Report and hypothesis CSV written; H1 NOT SUPPORTED / H2 SUPPORTED (qualified association) / H3 NOT SUPPORTED.')

def figures():
    os.environ['MPLCONFIGDIR']=str(OUT/'.matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    d=load(OUT/'temporal_data.json')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.labelsize':10,
        'xtick.labelsize':9,'ytick.labelsize':9,'legend.fontsize':8.5,
        'axes.spines.top':False,'axes.spines.right':False,'axes.grid':False,'savefig.dpi':350})
    blue,orange='#0072B2','#D55E00'
    def save(fig,name):
        p=FIG/name;assert not p.exists(),p
        fig.savefig(p,dpi=350,bbox_inches='tight',facecolor='white');plt.close(fig)
    def formal_values(metric):
        return np.array([[float(r[metric]) for r in d['run_summary'] if r['K']==k] for k in range(1,8)])
    ks=np.arange(1,8)
    fig,axes=plt.subplots(1,2,figsize=(7.2,2.9),layout='constrained')
    for metric,label,color,marker in [('e2e_mean_ms','Mean',blue,'o'),('e2e_p95_ms','p95',orange,'s')]:
        values=formal_values(metric)
        axes[0].errorbar(ks,values.mean(axis=1),yerr=values.std(axis=1,ddof=1),color=color,marker=marker,
            markersize=4,capsize=2,lw=1.4,label=label)
    axes[0].axhline(1000/30,color='black',ls='--',lw=1,label='Deadline (33.33 ms)')
    axes[0].set_yscale('log');axes[0].set_ylabel('E2E latency (ms, log scale)');axes[0].legend(loc='upper left',frameon=False)
    values=formal_values('deadline_miss_pct')
    axes[1].errorbar(ks,values.mean(axis=1),yerr=values.std(axis=1,ddof=1),color=orange,marker='o',markersize=4,capsize=2,lw=1.4)
    axes[1].set_ylim(0,105);axes[1].set_ylabel('Deadline miss (%)')
    for ax,tag in zip(axes,['(a)','(b)']):ax.set_xticks(ks);ax.set_xlabel('Streams K');ax.text(0,1.04,tag,transform=ax.transAxes)
    save(fig,'figure_1_local_qos_knee.png')
    fig,axes=plt.subplots(1,2,figsize=(7.2,2.8),gridspec_kw={'width_ratios':[3,1]},layout='constrained')
    comps=['frame_start_lag','front_end','inference_queue_wait','inference']
    labels=['Start lag','Front end','Queue wait','Inference service'];colors=['#999999','#56B4E9',orange,'#009E73']
    for ax,group in zip(axes,[list(range(1,7)),[7]]):
        bottom=np.zeros(len(group))
        for comp,label,color in zip(comps,labels,colors):
            values=formal_values(comp+'_mean_ms').mean(axis=1)[np.array(group)-1]
            ax.bar(group,values,bottom=bottom,color=color,label=label,width=.65);bottom+=values
        ax.set_xticks(group);ax.set_xlabel('Streams K');ax.set_ylabel('Mean latency (ms)');ax.set_ylim(bottom=0)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False)
    save(fig,'figure_2_latency_decomposition.png')
    fig,axes=plt.subplots(1,3,figsize=(7.2,2.7),layout='constrained')
    specs=[('ready','ready_span_mean_ms','Ready span (ms)',None),
           ('service','period_inference_service_sum_mean_ms','Service sum / period (ms)',None),
           ('carry','inference_unfinished_carryover_period_pct','Unfinished carry-over (%)','all_60s')]
    for ax,(section,metric,label,scope),tag in zip(axes,specs,['(a)','(b)','(c)']):
        values=[row(d,section,k,scope=scope)[metric] for k in (5,6)]
        sd=[row(d,section,k,'sample_sd',scope=scope)[metric] for k in (5,6)]
        ax.bar([0,1],values,yerr=sd,color=[blue,orange],width=.6,capsize=3,error_kw={'elinewidth':1})
        ax.set_xticks([0,1],['5','6']);ax.set_xlabel('Streams K');ax.set_ylabel(label);ax.set_ylim(bottom=0)
        ax.text(0,1.04,tag,transform=ax.transAxes)
    axes[1].axhline(1000/30,color='black',ls='--',lw=1,label='Frame period')
    axes[1].legend(loc='upper left',frameon=False,fontsize=8);axes[1].set_ylim(0,41)
    axes[2].set_ylim(0,105)
    save(fig,'figure_3_k5_k6_temporal_queue.png')
    print('Three 350-dpi PNGs written; aggregate bars/lines and sample SD only; no PDF generated.')

def validate():
    from PIL import Image
    d=load(OUT/'temporal_data.json');state=load(OUT/'input_preservation_before.json')
    assert len(d['integrity'])==35 and sum(r['frame_count'] for r in d['integrity'])==252000
    for k in range(1,8):
        for section in ('ready','service'):
            runs=[r for r in d[section] if r['K']==k and r['row_type']=='run']
            assert len(runs)==5 and {r['run_id'] for r in runs}=={f'run{i:02d}' for i in range(1,6)}
            for field in runs[0]:
                if field in ('K','row_type','run_id','run_count'):continue
                assert math.isclose(avg([r[field] for r in runs]),row(d,section,k)[field],rel_tol=1e-12,abs_tol=1e-12)
    event_checks=[]
    for k in range(1,8):
        for n in range(1,6):
            runid=f'run{n:02d}';raw=load(ROOT/f'k{k}'/runid/'raw_ns.json');events=raw['queue_events'];records=raw['records']
            # Independent boundary reconstruction from the queue event sequence.
            depth=0;previous=-1
            for seq,e in enumerate(events):
                assert e['seq']==seq and e['ns']>=previous
                depth+=1 if e['kind']=='enqueue' else -1
                assert depth==e['depth'] and depth>=0
                previous=e['ns']
            assert depth==0
            ns=np.array([e['ns'] for e in events],dtype=np.int64);dep=np.array([e['depth'] for e in events],dtype=np.int64)
            boundaries=raw['t0_ns']+np.arange(1,1801,dtype=np.int64)*1_000_000_000//30
            a=np.array([r['a_ns'] for r in records],dtype=np.int64)
            ready=np.array([r['r_ns'] for r in records],dtype=np.int64)
            starts=np.array([r['s_ns'] for r in records],dtype=np.int64)
            ends=np.array([r['c_ns'] for r in records],dtype=np.int64)
            # In these observed records r>a: a new boundary's jobs cannot be ready at B.
            assert np.all(ready>a)
            ix=np.searchsorted(ns,boundaries,side='right')-1
            w=np.where(ix>=0,dep[np.maximum(ix,0)],0)
            service=np.searchsorted(np.sort(starts),boundaries,side='right')-np.searchsorted(np.sort(ends),boundaries,side='right')
            pre=np.searchsorted(np.sort(a),boundaries,side='left')-np.searchsorted(np.sort(ready),boundaries,side='right')
            assert np.all(service>=0) and np.all(service<=1) and np.all(pre>=0)
            assert np.all(w+service+pre==np.searchsorted(np.sort(a),boundaries,side='left')-np.searchsorted(np.sort(ends),boundaries,side='right'))
            for scope,start in [('all_60s',0),('first_1s_excluded',30)]:
                saved=next(r for r in d['carry'] if r['K']==k and r['run_id']==runid and r['scope']==scope)
                expected={'period_count':1800-start,'waiting_carryover_period_pct':avg(w[start:]>0)*100,
                    'inservice_carryover_period_pct':avg(service[start:]>0)*100,
                    'inference_unfinished_carryover_period_pct':avg((w+service)[start:]>0)*100,
                    'mean_waiting_carryover_depth':avg(w[start:]),'max_waiting_carryover_depth':int(w[start:].max()),
                    'mean_inference_unfinished_depth':avg((w+service)[start:]),
                    'maximum_consecutive_inference_unfinished_carryover_periods':longest_true((w+service)[start:]>0),
                    'pre_ready_carryover_period_pct':avg(pre[start:]>0)*100}
                assert all(saved[key]==value for key,value in expected.items()),(k,runid,scope)
            saved_service=next(r for r in d['service'] if r['K']==k and r['run_id']==runid)
            formal=next(r for r in d['run_summary'] if r['K']==k and r['run_id']==runid)
            assert math.isclose(saved_service['period_inference_service_sum_mean_ms'],k*float(formal['inference_mean_ms']),abs_tol=1e-10)
            event_checks.append({'K':k,'run_id':runid,'independent_event_boundary_check':'PASS'})
    schemas={}
    for name in ('ready_span_summary.csv','period_service_demand_summary.csv','carryover_summary.csv','queue_depth_wait_summary.csv','k5_k6_explanation.csv'):
        rows=csvread(OUT/name);assert rows
        keys=[]
        for r in rows:
            assert None not in r and None not in r.values()
            for val in r.values():
                try:value=float(val)
                except ValueError:continue
                assert math.isfinite(value),(name,val)
            if name=='k5_k6_explanation.csv':keys.append(r['hypothesis'])
            else:keys.append(tuple(r.get(key,'') for key in ('K','scope','row_type','run_id','depth_group','metric')))
        assert len(keys)==len(set(keys)),name
        schemas[name]={'rows':len(rows),'columns':len(rows[0]),'finite_and_unique':'PASS'}
    for k in (5,6,7):
        for n in range(1,6):
            rows=[r for r in d['depth_wait'] if r['K']==k and r['run_id']==f'run{n:02d}' and r['metric']=='frame_count']
            assert sum(r['value'] for r in rows)==k*1800
    expected_png={'figure_1_local_qos_knee.png','figure_2_latency_decomposition.png','figure_3_k5_k6_temporal_queue.png'}
    assert {p.name for p in FIG.glob('*.png')}==expected_png
    assert not list(FIG.glob('*.pdf')) and not list(OUT.rglob('*.pdf'))
    image_info=[]
    for name in sorted(expected_png):
        with Image.open(FIG/name) as im:
            assert im.format=='PNG' and all(v>=300 for v in im.info['dpi'])
            image_info.append({'file':name,'pixels':list(im.size),'dpi':list(im.info['dpi'])})
    changes=[]
    for rel,old in state['protected'].items():
        p=REPO/rel;s=p.stat()
        now={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':s.st_size,'mtime_ns':s.st_mtime_ns}
        if now!=old:changes.append(rel)
    assert not changes,changes
    now_raw=sorted(str(p.relative_to(REPO)) for p in ROOT.rglob('*') if p.is_file() and not p.is_relative_to(ANALYSIS) and not p.is_relative_to(ROOT/'_smoke'))
    assert now_raw==state['raw_paths']
    for prefix in ('results/local_realtime_baseline/capacity_sweep_5rep','results/local_latency_breakdown/_smoke'):
        current={str(p.relative_to(REPO)) for p in (REPO/prefix).rglob('*') if p.is_file()}
        assert current=={p for p in state['protected'] if p.startswith(prefix+'/')}
    assert all(not (REPO/p).exists() for p in state['figure_deletions'])
    outcome={'validation':'PASS','runs':35,'frames':252000,'raw_timestamp_source':'35 raw_ns.json files; direct integer ns',
        'formal_raw_file_count_before':state['raw_file_count'],'formal_raw_file_count_after':len(now_raw),
        'protected_files_unchanged':len(state['protected']),'raw_hash_size_mtime_unchanged':True,
        'existing_summary_analysis_tables_and_measurement_code_unchanged':True,
        'CSV_validation':schemas,'independent_event_checks':event_checks,'figures':image_info,
        'PNG_count':3,'PDF_count_in_target':0,'PDF_count_in_temporal':0,
        'individual_run_traces':False,'new_experiment_executed':False}
    writejson('validation.json',outcome)
    print(json.dumps({k:v for k,v in outcome.items() if k not in ('independent_event_checks','CSV_validation')},indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['analyze','report','figures','validate'])
    args=p.parse_args()
    if args.mode=='analyze':analyze()
    elif args.mode=='report':report()
    elif args.mode=='figures':figures()
    elif args.mode=='validate':validate()

if __name__=='__main__':main()
