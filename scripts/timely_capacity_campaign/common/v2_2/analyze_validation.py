"""Post-run controlled-build acceptance using frozen B1 latency/overlap definitions."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from v22_config import ROOT,OUT,order,load_plan,sha,b1
import analyze_b1 as base


def full_groups(ov):
    groups={}
    for r in ov:
        if r['group']=='full-overlap':groups.setdefault(r['run_id'],{})[r['metric']]=r
    return groups


def accept(row,full,cpu_pin_pass,valid):
    host=full.get('host_wakeup_delay_ms',{}).get('mean')
    checks=dict(integrity_VALID=valid and row['integrity_status']=='VALID',terminal_accounting_PASS=row['terminal_accounting']=='PASS',
       active_completed_ge_195=row['raw_completed_FPS']>=195,cohort_completed_ge_197=row['completed_cohort_FPS']>=197,
       expired_le_5=row['expired_FPS']<=5,service_mean_le_10_1=row['existing_service_duration_ms_mean']<=10.1,
       full_overlap_host_residual_le_1_7=host is not None and host<=1.7,
       bookkeeping_p95_le_0_05=row['bookkeeping_duration_ms_p95'] is not None and row['bookkeeping_duration_ms_p95']<=.05,
       GPU_restore_PASS=row['frequency_restore_ok'] is True,CPU_pin_PASS=cpu_pin_pass)
    return dict(status='PASS' if all(checks.values()) else 'FAIL',checks=checks,GPU_stream_span_is_gate=False)


def reference():
    return base.read(OUT/'B1F_REFERENCE.csv')[0]


def analyze(destination):
    load_plan()
    if destination.exists():raise RuntimeError('No overwrite')
    expected=order()
    if not all((OUT/c['run_id']/'summary.json').exists() for c in expected):raise RuntimeError('Four preserved runs required; preparation is not measurement')
    records=[];phases=[];ov=[];bins=[];cpu=[];thermal=[];gates=[];checks={};hashes={}
    for c in expected:
        d=OUT/c['run_id']
        for p in d.iterdir():
            if p.is_file():hashes[str(p.relative_to(ROOT))]=sha(p)
        m,s,raw,ph,valid=base.load_run(d,c);checks[c['run_id']]=valid
        r,ps,bs=base.summarize_run(c,m,s,raw,ph)
        overlap=base.summarize_overlap(base.overlap_rows(ph,c['run_id']),c['run_id']);full=full_groups(overlap).get(c['run_id'],{})
        r.update(comparison_role='V22_ON' if c['pruning_enabled'] else 'V22_OFF',
            full_overlap_host_residual_mean_ms=full.get('host_wakeup_delay_ms',{}).get('mean'),
            full_overlap_GPU_stream_span_mean_ms=full.get('gpu_exec_duration_ms',{}).get('mean'))
        pin=True
        for name in ('CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json'):
            report=json.loads((d/name).read_text());pin=pin and report['status']=='PASS'
        pin=pin and m.get('CPU_pin_child_readback',{}).get('status')=='PASS'
        delta=json.loads((d/'CPU_TIME_IN_STATE_DELTA.json').read_text())
        cpu.extend(dict(x,run_id=c['run_id']) for x in delta)
        r['CPU_pin_readback_PASS']=pin
        r['CPU_residency_diagnostic']='NON_TARGET_OR_UNAVAILABLE' if any(x.get('status')!='PASS' or (x.get('frequency_kHz')!=2601000 and x.get('delta_counter_units',0)>0) for x in delta) else 'ALL_OBSERVED_COUNTER_DELTA_AT_TARGET'
        for name,label in [('THERMAL_BEFORE_RUN.json','start'),('THERMAL_AFTER_RUN.json','end')]:
            thermal.extend(dict(x,run_id=c['run_id'],boundary=label) for x in json.loads((d/name).read_text()))
        if c['pruning_enabled']:gates.append(dict(run_id=c['run_id'],**accept(r,full,pin,valid['status']=='PASS')))
        records.append(r);phases+=ps;ov+=overlap;bins+=bs
    restored=OUT/'CPU_RESTORE_READBACK.json'
    restored_pass=restored.exists() and json.loads(restored.read_text()).get('status')=='PASS'
    verdict=dict(ON_acceptance='PASS' if len(gates)==3 and all(g['status']=='PASS' for g in gates) else 'FAIL',
        ON_runs=gates,OFF_reference_integrity=checks[expected[1]['run_id']]['status'],CPU_restore='PASS' if restored_pass else 'USER_VERIFICATION_PENDING_OR_FAILED',
        limitation='GPU stream-span outside historical range never fails the gate. No sole-cause/significance claim.')
    destination.mkdir(parents=True,exist_ok=False)
    ref=reference();ref['comparison_role']='B1F_REFERENCE'
    base.write_csv(destination/'per_run_summary.csv',[ref]+records)
    for name,rows in [('phase_metrics_by_run.csv',phases),('overlap_conditioned_metrics.csv',ov),('startup_100ms_timeseries.csv',bins),('cpu_residency.csv',cpu),('thermal_boundaries.csv',thermal)]:base.write_csv(destination/name,rows)
    base.write_json(destination/'acceptance.json',verdict);base.write_json(destination/'integrity_validation.json',checks)
    summaries=[]
    on=[r for r in records if r['mode']=='ON']
    for key in ('raw_completed_FPS','completed_cohort_FPS','timely_FPS','timely_ratio','expired_FPS','late_completed_FPS','queue_p95_ms','queue_p99_ms',
                'existing_service_duration_ms_mean','full_overlap_host_residual_mean_ms','full_overlap_GPU_stream_span_mean_ms','bookkeeping_duration_ms_p95'):
        vals=[r[key] for r in on]
        summaries.append(dict(metric=key,repeat1=vals[0],repeat2=vals[1],repeat3=vals[2],mean=statistics.mean(vals) if all(v is not None for v in vals) else None,
            sample_SD=statistics.stdev(vals) if all(v is not None for v in vals) else None,min=min(vals) if all(v is not None for v in vals) else None,max=max(vals) if all(v is not None for v in vals) else None))
    base.write_csv(destination/'ON_three_repeat_distribution.csv',summaries)
    text=['# V2.2 ON acceptance: '+verdict['ON_acceptance'],'','CPU restored readback: '+verdict['CPU_restore'],
          '','|Run|Active FPS|Cohort FPS|Timely FPS|Timely ratio|Expired FPS|Queue p95/p99 ms|Service mean ms|Full-overlap host residual ms|GPU span mean ms|',
          '|---|---:|---:|---:|---:|---:|---|---:|---:|---:|']
    for r in [ref]+records:text.append('|'+str(r['run_id'])+'|'+'|'.join(str(r.get(k,'N/A')) for k in ('raw_completed_FPS','completed_cohort_FPS','timely_FPS','timely_ratio','expired_FPS'))+'|'+str(r.get('queue_p95_ms'))+'/'+str(r.get('queue_p99_ms'))+'|'+'|'.join(str(r.get(k,'N/A')) for k in ('existing_service_duration_ms_mean','full_overlap_host_residual_mean_ms','gpu_exec_duration_ms_mean'))+'|')
    text+=['','All individual quantiles, ON mean/sample SD/min/max, OFF reference and CPU residency are preserved. CPU residency intervals include initialization/warmup/drain; not active-only.',
           'CPU fixed2601MHz is an experimental control, not a controller action. CPU DVFS joint control is outside scope. V2.1 energy measurements must not be pooled with this controlled runtime.',
           'No later knee/Edge/Block A/Block B run is authorized or auto-started by this analysis.']
    with (destination/'VALIDATION_SUMMARY.md').open('x') as f:f.write('\n'.join(text)+'\n')
    base.plots(destination,records,ov,bins)
    base.write_json(destination/'preservation.json',dict(status='PASS' if all(sha(ROOT/p)==h for p,h in hashes.items()) else 'FAIL',source_sha256=hashes))
    print(json.dumps(verdict,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=OUT/'analysis01');a=ap.parse_args();analyze(a.output)
