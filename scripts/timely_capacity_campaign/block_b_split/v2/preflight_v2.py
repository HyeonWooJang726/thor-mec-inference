"""Explicit future eight-run Edge-only preflight; no Local inference or clock control."""
import argparse
import json
import time
import traceback
import types
from pathlib import Path
from bootstrap import ROOT,V2,frozen as cfg
import config_v2 as conf
import edge_preflight as original
from reuse import pruning,prior
import wifi_v2

PLAN=V2/'preflight_plan.json'
RESULT=V2/'preflight01'

def hello(c,rid,digest):
    h=original.hello(c,rid,digest);h.update(mode='timely_capacity_preflight_v2',repeat=c['repeat']);return h

def occupancy(rows,left,right):
    def peak(a,b):
        events=[]
        for r in rows:
            x=r.get(a);y=r.get(b) or r.get('expired_drop_ns')
            if x is not None and y is not None:events.extend([(x,1),(y,-1)])
        level=highest=0;area=0;previous=left
        for t,d in sorted(events):
            if t>right:break
            area+=level*max(0,min(t,right)-max(previous,left));level+=d;previous=t;highest=max(highest,level)
        area+=level*max(0,right-max(previous,left))
        return dict(peak=highest,active_mean=area/(right-left))
    return dict(client_pending=peak('logical_arrival_ns','socket_submission_ns'),
        submitted_outstanding=peak('socket_submission_ns','response_completion_ns'))

def require_selected(emax):
    p=conf.load(PLAN);r=json.loads((RESULT/'selection.json').read_text())
    if r['preflight_plan_sha256']!=cfg.sha(PLAN):raise RuntimeError('Wrong preflight evidence')
    actual=conf.select(r['runs'])
    if actual!=r['selection'] or actual['E_max']!=emax or actual['status']!='BRANCH_SELECTED':raise RuntimeError('No approved frozen branch from valid preflight')
    if r['selected_branch_sha256']!=cfg.sha(conf.branch_path(emax)) or p['branches'][str(emax)]['sha256']!=cfg.sha(conf.branch_path(emax)):raise RuntimeError('Selected branch changed')
    for name,h in r['artifact_sha256'].items():
        if cfg.sha(RESULT/name)!=h:raise RuntimeError('Preflight artifact changed')
    return r

def run(approval):
    p=conf.load(PLAN);digest=cfg.sha(PLAN)
    if approval!=digest:raise RuntimeError('Explicit exact preflight SHA required')
    for e in conf.LEVELS:
        conf.load(conf.branch_path(e))
        if cfg.sha(conf.branch_path(e))!=p['branches'][str(e)]['sha256']:raise RuntimeError('Branch not frozen before preflight')
    if cfg.sha(ROOT/p['cache']['path'])!=p['cache']['sha256']:raise RuntimeError('Cache mismatch')
    payloads,_=prior.old.edge_runtime.load_cache(ROOT/p['cache']['path'])
    RESULT.mkdir(exist_ok=False)
    class Link(pruning.EdgeLink):pass
    fn=pruning.EdgeLink.__init__
    Link.__init__=types.FunctionType(fn.__code__,dict(fn.__globals__,hello=hello),fn.__name__,fn.__defaults__,fn.__closure__)
    from run_campaign import read_tx
    from campaign_analysis import write_csv,quantiles
    runs=[]
    for index,c in enumerate(p['order']):
        if index:time.sleep(10)
        d=RESULT/c['run_id'];d.mkdir();rows=[];m={};errors=[];link=None;start=None;tx=[]
        before=wifi_v2.capture()
        try:
            link=Link(dict(c,edge_r=c['rate']//8),c['run_id'],m,d,errors.append,digest,p['edge_host'])
            start=time.monotonic_ns()+200_000_000
            time.sleep(max(0,(start-time.monotonic_ns())/1e9))
            tx.append(dict(timestamp_ns=time.monotonic_ns(),bytes=read_tx('wlP1p1s0')))
            for rid in range(c['rate']*30):
                due=start+rid*10**9//c['rate'];delay=(due-time.monotonic_ns())/1e9
                if delay>0:time.sleep(delay)
                row=dict(edge_request_id=rid,logical_arrival_ns=due,absolute_deadline_ns=due+100_000_000,
                    edge_release_target_ns=due,placement='EDGE',admitted=1,sample_id=rid%len(payloads))
                rows.append(row);link.put(row,payloads[rid%len(payloads)])
            time.sleep(max(0,(start+30*10**9-time.monotonic_ns())/1e9))
            tx.append(dict(timestamp_ns=time.monotonic_ns(),bytes=read_tx('wlP1p1s0')))
            link.finish()
            if not link.done.wait(300):raise RuntimeError('Natural drain timeout')
        except BaseException:errors.append(traceback.format_exc())
        finally:
            if link is not None:link.close()
        after=wifi_v2.capture()
        try:
            s=original.evaluate(rows,m.get('edge_final',{}),errors,c['rate'],start)
            end=start+30*10**9
            s.update(target_FPS=c['rate'],assigned_FPS=len(rows)/30,completed_FPS=sum(start<=(r.get('response_completion_ns') or 0)<end for r in rows)/30,
                completed_cohort_FPS=s['completed']/30,missing=s['after_drain_unfinished'],duplicates=len(rows)-len({r['edge_request_id'] for r in rows}),
                request_errors=errors,network_TX_scope='Interface counter difference over its actual endpoint interval; includes other traffic/overhead',
                network_TX_bytes_per_s=(tx[-1]['bytes']-tx[0]['bytes'])/((tx[-1]['timestamp_ns']-tx[0]['timestamp_ns'])/1e9) if len(tx)==2 and all(x['bytes'] is not None for x in tx) and tx[-1]['bytes']>=tx[0]['bytes'] else None,
                RAW640_submitted_bytes_per_s=sum(start<=(r.get('socket_submission_ns') or 0)<end for r in rows)*691200/30,
                pending_ms=quantiles([(r['socket_submission_ns']-r['logical_arrival_ns'])/1e6 for r in rows if r.get('socket_submission_ns')]),
                outstanding=occupancy(rows,start,end),wifi=wifi_v2.compare(before,after))
        except Exception:s=dict(rate=c['rate'],integrity_status='INVALID',errors=errors+[traceback.format_exc()],wifi=wifi_v2.compare(before,after))
        if rows:write_csv(d/'requests.csv',rows)
        for name,data in [('manifest.json',dict(m,plan_sha256=digest,condition=c,active_start_ns=start,active_end_ns=start+30*10**9 if start else None,
            wifi_start=before,wifi_end=after,network_TX_samples=tx,input_scope='Cached actual RAW64030; expired-only sender; no Local GPU or frequency control')),
            ('summary.json',s),('wifi_start.json',before),('wifi_end.json',after)]:
            with (d/name).open('x') as f:json.dump(data,f,indent=2)
        with (d/'stderr.log').open('x') as f:f.write('\n'.join(s.get('errors',[])))
        runs.append(dict(s,run_id=c['run_id'],repeat=c['repeat']));print(runs[-1],flush=True)
        if s['integrity_status']!='VALID':break
    from campaign_analysis import statistics,flatten
    write_csv(RESULT/'per_run_metrics.csv',[flatten(r) for r in runs])
    write_csv(RESULT/'condition_statistics.csv',statistics([dict(r,cell=f'E{r["rate"]}') for r in runs]))
    selection=conf.select(runs);e=selection['E_max']
    record=dict(preflight_plan_sha256=digest,runs=runs,selection=selection,
        selected_branch_sha256=cfg.sha(conf.branch_path(e)) if e else None,
        artifact_sha256={str(x.relative_to(RESULT)):cfg.sha(x) for x in RESULT.rglob('*') if x.is_file()},
        next_action='STOP. Inspect evidence; launch only the already frozen selected branch. No automatic campaign execution.')
    with (RESULT/'selection.json').open('x') as f:json.dump(record,f,indent=2)
    print(selection);return 0 if e else 1

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--approve-plan-sha256',required=True);a=ap.parse_args();raise SystemExit(run(a.approve_plan_sha256))
