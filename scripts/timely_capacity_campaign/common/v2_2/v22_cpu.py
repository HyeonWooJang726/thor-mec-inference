"""Read-only CPU/thermal inspection; manual CPU control only."""
import argparse
import json
from pathlib import Path
import sys
from v22_config import HERE,OUT
sys.path.insert(0,str(HERE.parent/'service_phase_b1f'))
import cpu_state as original
snapshot=original.snapshot
residency=original.residency


def reference():return json.loads((OUT/'CPU_STATE_BEFORE.json').read_text())


def validate(current,mode):
    report=original.validate(current,reference(),mode)
    if len(current['policies'])!=7:report['errors'].append('exactly seven policies required')
    if mode=='pinned':
        for p in current['policies']:
            if p['fields']['scaling_max_freq']!='2601000':report['errors'].append('CPU target must be2601000kHz')
    report['status']='FAIL' if report['errors'] else 'PASS';return report


def require_pinned():
    report=validate(snapshot(),'pinned')
    if report['status']!='PASS':raise RuntimeError('CPU pin mismatch: '+str(report['errors']))
    if not all(r['time_in_state_readable'] for r in report['snapshot']['policies']):raise RuntimeError('Required time_in_state unavailable; no workload')
    return report


def thermal_snapshot():
    rows=[]
    for p in sorted(Path('/sys/class/thermal').glob('thermal_zone*')):
        try:rows.append(dict(path=str(p),type=(p/'type').read_text().strip(),temp_millidegrees_C=int((p/'temp').read_text())))
        except (OSError,ValueError) as e:rows.append(dict(path=str(p),error=str(e)))
    return rows


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['pinned','restored']);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('Readback output exists')
    r=validate(snapshot(),a.mode)
    with a.output.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['status']=='PASS' else 2)
