"""Frozen placement unchanged; pruning has explicit terminal states, never fake completions."""
import inspect
import json
from pathlib import Path
import sys
import textwrap
import types

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/canonical_timely_service'))
import timely_common as canonical
import run_timely as canonical_runner
import analyze_timely as canonical_analysis
OUT=ROOT/'results/expired_work_pruning'
PLAN=OUT/'plan.json'
PREFLIGHT=OUT/'frequency_preflight.json'
sha,remaining,prior=canonical.sha,canonical.remaining,canonical.prior
FIELDS=['absolute_deadline_ns','expiry_check_ns','expired_drop_ns','terminal_state','expired_stage']
ORDERS=(((200,100),(240,150),(200,150),(240,100)),
        ((240,100),(200,150),(240,150),(200,100)),
        ((200,150),(200,100),(240,100),(240,150)))


def expected_order():
    rows=[]
    for repeat,order in enumerate(ORDERS,1):
        for target,deadline in order:
            local,edge=(184,16) if target==200 else (200,40)
            rows.append(dict(run_id=f'EWP_R{repeat}_P{target}_D{deadline}_P01',kind='formal',repeat=repeat,
                order_index=len(rows)+1,cell=f'P{target}-D{deadline}',supply_mode='B',
                target_service_FPS=target,local_r=local//8,edge_r=edge//8,deadline_ms=deadline,
                K=8,C=2,r=30,frequency='F1575',frequency_MHz=1575,seconds=60,
                pass_name=f'R{repeat}',**{'pass':f'R{repeat}'}))
    return rows


def decorate(row,start,target,mode,deadline_ms):
    canonical.decorate(row,start,target,mode)
    if row['admitted']:
        row['absolute_deadline_ns']=row['logical_arrival_ns']+deadline_ms*10**6
    return row


def expire(row,stamp,stage):
    if stamp<row['absolute_deadline_ns']:raise ValueError('Early pruning')
    if any(row.get(k) not in ('',None) for k in ('s_ns','inference_start_timestamp_ns',
            'socket_submission_ns','c_ns','completion_timestamp_ns','response_completion_ns')):
        raise ValueError('Cannot prune started/submitted/completed work')
    row.update(expiry_check_ns=stamp,expired_drop_ns=stamp,terminal_state='EXPIRED_DROP',expired_stage=stage)


sys.path.insert(0,str(ROOT/'scripts/local'))
from local_latency_breakdown_metrics import QueueAccounting as PreviousAccounting


class PruningAccounting(PreviousAccounting):
    """Called under the original queue-accounting lock; preserve surviving FIFO order."""
    def __init__(self):
        super().__init__();self.n_expired=0

    def enqueue(self,q,job,clock):
        depth=self.n_enqueue-self.n_start-self.n_expired
        if depth<0:raise RuntimeError('Negative waiting work')
        job['inference_queue_depth_before_enqueue']=depth
        q.put(job);job['r_ns']=clock();self.n_enqueue+=1
        self.events.append(dict(seq=len(self.events),kind='enqueue',ns=job['r_ns'],
            stream_id=job['stream_id'],frame_id=job['frame_id'],depth=depth+1))

    def begin(self,job,clock):
        if self.n_start+self.n_expired>=self.n_enqueue:raise RuntimeError('Unaccounted dequeue')
        stamp=clock();job['expiry_check_ns']=stamp
        if stamp>=job['absolute_deadline_ns']:
            expire(job,stamp,'LOCAL_BEFORE_TRT');self.n_expired+=1;kind='expired'
        else:
            job['s_ns']=stamp;self.n_start+=1;kind='start'
        self.events.append(dict(seq=len(self.events),kind=kind,ns=stamp,stream_id=job['stream_id'],
            frame_id=job['frame_id'],depth=self.n_enqueue-self.n_start-self.n_expired))
        return kind=='start'


def load_plan():
    p=json.loads(PLAN.read_text())
    if p['freeze_status']!='FROZEN_EXPIRED_WORK_PRUNING_V1' or p['order']!=expected_order() or p['smoke']:
        raise RuntimeError('Frozen pruning plan mismatch')
    if p['source_phase_ns']!=[0]*8:raise RuntimeError('Source phase mismatch')
    return p


def hello(c,run_id,plan_sha):
    return dict(mode='expired_work_pruning',repeat=c['repeat'],rate=8*c['edge_r'],seconds=c['seconds'],
        run_id=run_id,pruning_plan_sha256=plan_sha,cell=c['cell'],target_service_FPS=c['target_service_FPS'],
        frequency_MHz=1575,deadline_ms=c['deadline_ms'],
        cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
        payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')


# Only client pruning/accounting differs. Framing, private buffers and server inference do not.
OldLink=prior.transport.EdgeLink
class EdgeLink(OldLink):
    pass

rep=prior.hybrid.replace_once
ns=dict(inspect.getmodule(OldLink).__dict__,hello=hello,expire=expire)
s=textwrap.dedent(inspect.getsource(OldLink.__init__))
s=rep(s,"int(condition['seconds']*40)","int(condition['seconds']*8*condition['edge_r'])")
s=rep(s,'self.submitted = 0','self.submitted = 0\n    self.sent_ids = set()\n    self.expired_ids = []')
exec(compile(s,'<pruning-edge-init>','exec'),ns);EdgeLink.__init__=ns['__init__']
s=textwrap.dedent(inspect.getsource(OldLink.sender))
s=rep(s,"row['socket_submission_ns'] = time.monotonic_ns()",
    "stamp = time.monotonic_ns()\n            row['expiry_check_ns'] = stamp\n"
    "            if stamp >= row['absolute_deadline_ns']:\n"
    "                expire(row, stamp, 'EDGE_BEFORE_SUBMISSION')\n"
    "                self.expired_ids.append(rid)\n                continue\n"
    "            self.sent_ids.add(rid)\n            row['socket_submission_ns'] = stamp")
s=rep(s,"metadata={'submitted':self.submitted}",
    "metadata={'submitted':self.submitted, 'assigned':self.count, 'expired_request_ids':self.expired_ids}")
exec(compile(s,'<pruning-edge-sender>','exec'),ns);EdgeLink.sender=ns['sender']
s=textwrap.dedent(inspect.getsource(OldLink.receiver))
s=rep(s,"if len(seen) != self.count: raise RuntimeError('early Edge FINAL')",
    "if seen != self.sent_ids or len(seen) != self.submitted: raise RuntimeError('early Edge FINAL')\n"
    "                    if meta.get('expired_request_ids') != self.expired_ids or meta.get('client_expired_before_submission') != len(self.expired_ids): raise RuntimeError('Edge pruning ledger mismatch')")
s=rep(s,'meta.get(k) != self.count','meta.get(k) != self.submitted')
s=rep(s,'rid not in self.rows','rid not in self.rows or rid not in self.sent_ids')
s=rep(s,"row['response_completion_ns'] = row['c_ns'] = completion",
    "row['response_completion_ns'] = row['c_ns'] = completion\n                row['terminal_state'] = 'COMPLETED'")
exec(compile(s,'<pruning-edge-receiver>','exec'),ns);EdgeLink.receiver=ns['receiver']


def require_preflight():
    r=json.loads(PREFLIGHT.read_text())
    if r.get('status')!='PASS' or r.get('plan_sha256')!=sha(PLAN):raise RuntimeError('Passing preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)),sha256=sha(PREFLIGHT))
