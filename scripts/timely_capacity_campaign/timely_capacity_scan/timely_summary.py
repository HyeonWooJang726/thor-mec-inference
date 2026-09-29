"""Post-drain log accounting only. Reuses frozen integrity core with plan parameters."""
import types
from timely_config import decorate
import b1_summary as b1
from analysis_21 import terminal_partition
read_csv=b1.read_csv


def summarize(m,frames,power):
    def parameter_decorate(row,start,target,mode,D):return decorate(row,start,m)
    fn=b1.ns['summarize']
    core=types.FunctionType(fn.__code__,dict(fn.__globals__,decorate=parameter_decorate))
    s=core(m,frames,power)
    part=terminal_partition(frames);s['terminal_partition']=part
    s['true_unfinished_after_drain']=part['TOTAL']['true_unfinished']
    terminal=all(x['terminal_identity_ok'] and x['true_unfinished']==0 and x['duplicate_IDs']==0 for x in part.values())
    s['terminal_accounting_status']='PASS' if terminal else 'FAIL'
    if not terminal or m.get('pruning_enabled') is not True:
        s['errors'].append('terminal accounting or required pruning ON failed')
        s.update(integrity_status='INVALID',validity='INVALID',pipeline_audit_status='FAIL')
    s['configured_admission_FPS_per_stream']=m['target_service_FPS']/8
    s['legacy_admission_field_note']='Frozen worker admission_fps_per_stream uses integer division; for212 use configured_admission_FPS_per_stream=26.5 and exact IDs/counts.'
    return s
