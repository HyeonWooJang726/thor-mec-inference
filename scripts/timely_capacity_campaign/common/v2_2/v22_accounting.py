"""Same B1 ON/OFF expiry comparison and lock usage; no detailed event dictionaries."""
import ast
import inspect
import textwrap
import sys
from v22_config import ROOT
sys.path.insert(0,str(ROOT/'scripts/expired_work_pruning'))
from pruning_common import PruningAccounting,expire


def method_source(name,enabled):
    s=textwrap.dedent(inspect.getsource(getattr(PruningAccounting,name)))
    tree=ast.parse(s)
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='self.events.append')
    lines=s.splitlines(keepends=True);s=''.join(lines[:node.lineno-1]+lines[node.end_lineno:])
    if name=='begin' and not enabled:
        assert s.count("if stamp>=job['absolute_deadline_ns']:")==1
        s=s.replace("if stamp>=job['absolute_deadline_ns']:",'if False:  # OFF: expiry predicate only')
    return s


def expire_source():
    s=inspect.getsource(expire)
    old="row.update(expiry_check_ns=stamp,expired_drop_ns=stamp,terminal_state='EXPIRED_DROP',expired_stage=stage)"
    new="row['expiry_check_ns']=stamp;row['expired_drop_ns']=stamp;row['terminal_state']='EXPIRED_DROP';row['expired_stage']=stage"
    assert s.count(old)==1;return s.replace(old,new)


def make_accounting(enabled):
    class RecordingLightAccounting(PruningAccounting):pass
    ns=dict(expire.__globals__);exec(compile(expire_source(),'<V22-expire-state-identical>','exec'),ns)
    for name in ('enqueue','begin'):
        env=dict(getattr(PruningAccounting,name).__globals__,expire=ns['expire'])
        exec(compile(method_source(name,enabled),'<V22-accounting-'+name+'>','exec'),env)
        setattr(RecordingLightAccounting,name,env[name])
    return RecordingLightAccounting()
