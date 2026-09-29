"""Read-only CPU policy validation; this file never writes sysfs."""
import argparse
import json
import os
from pathlib import Path
import time
from b1f_common import OUT

FIELDS=('affected_cpus','related_cpus','scaling_governor','scaling_min_freq','scaling_max_freq',
        'cpuinfo_min_freq','cpuinfo_max_freq','scaling_cur_freq')
BASE=Path('/sys/devices/system/cpu/cpufreq')


def reference():return json.loads((OUT/'CPU_STATE_BEFORE.json').read_text())


def snapshot(base=BASE,online_path=Path('/sys/devices/system/cpu/online')):
    rows=[]
    for p in sorted(base.glob('policy[0-9]*'),key=lambda p:int(p.name[6:])):
        r=dict(path=str(p),fields={},errors={})
        for k in FIELDS:
            try:r['fields'][k]=(p/k).read_text().strip()
            except OSError as e:r['fields'][k]=None;r['errors'][k]=str(e)
        r['time_in_state_exists']=(p/'stats/time_in_state').exists()
        try:r['time_in_state']=(p/'stats/time_in_state').read_text();r['time_in_state_readable']=True
        except OSError as e:r['time_in_state']=None;r['time_in_state_readable']=False;r['time_in_state_error']=str(e)
        rows.append(r)
    return dict(monotonic_ns=time.monotonic_ns(),online=online_path.read_text().strip(),
                affinity=sorted(os.sched_getaffinity(0)),policies=rows)


def validate(current,saved,mode):
    errors=[];old={r['path']:r for r in saved['policies']};now={r['path']:r for r in current['policies']}
    if not old or set(old)!=set(now):errors.append('policy set mismatch')
    if current['online']!=saved['online']:errors.append('online CPU set changed')
    if current['affinity']!=saved['affinity']:errors.append('process affinity changed')
    for path,r in old.items():
        if path not in now:continue
        before=r['fields'];after=now[path]['fields']
        expected={k:before[k] for k in ('affected_cpus','related_cpus','scaling_governor','scaling_min_freq','scaling_max_freq','cpuinfo_min_freq','cpuinfo_max_freq')}
        if mode=='pinned':
            expected.update(scaling_governor='performance',scaling_min_freq=before['scaling_max_freq'],scaling_cur_freq=before['scaling_max_freq'])
        for k,v in expected.items():
            if v is None or after.get(k)!=v:errors.append(path+': '+k+' mismatch '+str(after.get(k))+' != '+str(v))
    return dict(status='PASS' if not errors else 'FAIL',mode=mode,errors=errors,snapshot=current)


def require_pinned():
    report=validate(snapshot(),reference(),'pinned')
    if report['status']!='PASS':raise RuntimeError('CPU pin preflight failed: '+json.dumps(report['errors']))
    return report


def residency(before,after):
    rows=[];right={r['path']:r for r in after['policies']}
    for r in before['policies']:
        z=right.get(r['path'],{})
        try:
            a={int(f):int(t) for f,t in (line.split() for line in r['time_in_state'].splitlines())}
            b={int(f):int(t) for f,t in (line.split() for line in z['time_in_state'].splitlines())}
            if set(a)!=set(b) or any(b[f]<a[f] for f in a):raise ValueError('counter reset/frequency set changed')
            total=sum(b[f]-a[f] for f in a)
            for f in a:rows.append(dict(policy=r['path'],frequency_kHz=f,delta_counter_units=b[f]-a[f],
                residency_fraction=(b[f]-a[f])/total if total else None,status='PASS' if total else 'ZERO_DELTA',
                scope='whole supervised attempt including initialization/warmup/drain; not active-only'))
        except (TypeError,ValueError,AttributeError) as e:
            rows.append(dict(policy=r['path'],status='UNAVAILABLE',reason=str(e),residency_fraction=None))
    return rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['pinned','restored']);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('Readback output exists; no overwrite')
    report=validate(snapshot(),reference(),a.mode)
    with a.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2));return 0 if report['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
