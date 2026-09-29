"""Optional post-campaign descriptive comparison; no cross-block prerequisite or verdict."""
import argparse
import json
from pathlib import Path
from campaign_analysis import write_csv


def report(a,b,output):
    if output.exists():raise RuntimeError('No overwrite')
    output.mkdir(parents=True)
    rows=[]
    for block,path in [('A',a),('B',b)]:
        for r in json.loads(path.read_text()):
            if 8*r['local_r'] not in (176,184) or block=='A' and r['admission_pattern']!='ALIGNED':continue
            rows.append(dict(block=block,cell=r['cell'],repeat=r['repeat'],integrity_status=r['integrity_status'],
                total_admitted_FPS=r['target_service_FPS'],local_assigned_FPS=8*r['local_r'],
                Local_timely_FPS=r.get('path_timely',{}).get('LOCAL',{}).get('timely_FPS'),
                Local_queue_p95=r.get('local_queue_ms',{}).get('p95'),Local_slot_counts=r.get('slot_counts',{}).get('local'),
                comparison_scope='Different admitted demand and Local slot patterns; descriptive only; no causal verdict'))
    write_csv(output/'cross_block_local_176_184.csv',rows)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--a',type=Path,required=True);ap.add_argument('--b',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    x=ap.parse_args();report(x.a,x.b,x.output)
