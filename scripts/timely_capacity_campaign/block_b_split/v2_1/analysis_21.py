"""Add explicit terminal partition; preserve legacy B and all preexisting errors."""
import bootstrap_21
import analysis_v2 as v2
from collections import Counter
read_csv=v2.read_csv

def terminal_partition(frames):
    rows=[r for r in frames if r.get('phase')=='active' and int(r.get('admitted') or 0)]
    out={}
    for label,group in [('TOTAL',rows),('LOCAL',[r for r in rows if r.get('placement')=='LOCAL']),('EDGE',[r for r in rows if r.get('placement')=='EDGE'])]:
        completed=[];expired=[];unfinished=[];conflicting=[]
        for r in group:
            end=v2.old.val(r,'completion_timestamp_ns');drop=v2.old.val(r,'expired_drop_ns')
            if r.get('terminal_state')=='COMPLETED' and end is not None and drop is None:completed.append(r)
            elif r.get('terminal_state')=='EXPIRED_DROP' and drop is not None and end is None:expired.append(r)
            elif (end is not None and drop is not None):conflicting.append(r)
            else:unfinished.append(r)
        ids=Counter((int(r['stream_id']),int(r['frame_id'])) for r in group)
        out[label]=dict(assigned=len(group),completed=len(completed),expired_dropped=len(expired),true_unfinished=len(unfinished),
            conflicting_terminal_states=len(conflicting),duplicate_IDs=sum(n-1 for n in ids.values()),
            terminal_identity_ok=len(group)==len(completed)+len(expired)+len(unfinished) and not conflicting)
    return out

def summarize(m,frames,power):
    s=v2.summarize(m,frames,power);part=terminal_partition(frames);t=part['TOTAL']
    s.update(terminal_partition=part,true_unfinished_after_drain=t['true_unfinished'],
        terminal_accounting_definition='assigned = completed + expired_dropped + true_unfinished; legacy completion-only backlog preserved',
        terminal_accounting_status='PASS' if all(p['terminal_identity_ok'] and p['true_unfinished']==0 and p['duplicate_IDs']==0 for p in part.values()) else 'FAIL')
    if s['terminal_accounting_status']!='PASS':
        s.setdefault('errors',[]).append('pruning-aware terminal partition/drain failure')
        s.update(integrity_status='INVALID',validity='INVALID',pipeline_audit_status='FAIL')
    return s

def analyze(destination):
    import inspect
    from run_21 import runtime_record
    source=inspect.getsource(v2.analyze)
    source=v2.old.old.prior.hybrid.replace_once(source,'root=planpath.parent','root=V21_RUN_ROOT')
    source=v2.old.old.prior.hybrid.replace_once(source,"m=json.loads((d/'manifest.json').read_text())",
        "m=json.loads((d/'manifest.json').read_text())\n            if m.get('execution_runtime')!=runtime_record():raise ValueError('V2.1 runtime provenance mismatch')")
    ns=dict(v2.__dict__,summarize=summarize,V21_RUN_ROOT=bootstrap_21.OUT/'E_MAX_72',runtime_record=runtime_record)
    exec(compile(source,'<V2.1-log-only-analysis>','exec'),ns)
    return ns['analyze'](72,destination)

if __name__=='__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();analyze(args.output)
