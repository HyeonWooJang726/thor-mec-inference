"""Read-only temperature repair. No polling, inferred readings or raw-log changes."""
import re
import statistics
from pathlib import Path
import json
from timely_config import raw
from analyze_b1 import read,number


def temperatures(directory,m,power):
    result={};by_zone={}
    for label,file,key in (('start','THERMAL_BEFORE_RUN.json','thermal_start'),('end','THERMAL_AFTER_RUN.json','thermal_end')):
        p=Path(directory)/file
        zones=json.loads(p.read_text()) if p.exists() else m.get(key,[])
        for z in zones:
            if 'temp_millidegrees_C' in z:
                by_zone.setdefault(z['type'].removesuffix('-thermal'),{})[label]=z['temp_millidegrees_C']/1000
    active=[r for r in power if m['active_start_ns']<=number(r,'timestamp_ns')<m['active_end_ns']]
    samples={}
    for row in active:
        for zone,temp in re.findall(r'(\w+)@(-?\d+(?:\.\d+)?)C',row.get('raw_tegrastats','')):
            samples.setdefault(zone,[]).append(float(temp))
    for zone,vals in samples.items():
        by_zone.setdefault(zone,{}).update(mean=statistics.mean(vals),active_first_observed=vals[0],active_last_observed=vals[-1],active_sample_count=len(vals))
    for zone,stats in by_zone.items():
        for field in ('start','mean','end','active_first_observed','active_last_observed','active_sample_count'):
            result[f'{zone}_temperature_{field}']=stats.get(field)
    # Main temperature = tj consistently. GPU/CPU/SoC are separate, never substituted.
    for field in ('start','mean','end'):result['temperature_'+field]=by_zone.get('tj',{}).get(field)
    result['temperature_scope']='tj; separate gpu/cpu/soc012/soc345 columns. Start/end=supervised run boundaries, mean=active tegrastats arithmetic mean.'
    result['temperature_start_source']=str(Path(directory)/'THERMAL_BEFORE_RUN.json') if (Path(directory)/'THERMAL_BEFORE_RUN.json').exists() else 'manifest.thermal_start'
    result['temperature_end_source']=str(Path(directory)/'THERMAL_AFTER_RUN.json') if (Path(directory)/'THERMAL_AFTER_RUN.json').exists() else 'manifest.thermal_end'
    result['temperature_mean_source']='power_trace.csv.gz/raw_tegrastats/tj@...C, actual active timestamp interval'
    vals=[float(r['temperature_C']) for r in active if r.get('temperature_C') not in ('',None)]
    result['legacy_temperature_C_active_mean']=statistics.mean(vals) if vals else None
    return result
