"""Explicit future network-only preflight; no Local runtime or frequency calls."""
import argparse
import json
from pathlib import Path
import time
import traceback
import types
import campaign_config as cfg
from reuse import pruning,prior


def hello(c,rid,digest):
    return dict(mode='timely_capacity_preflight',rate=8*c['edge_r'],seconds=30,repeat=1,run_id=rid,
        campaign_plan_sha256=digest,cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
        payload_origin='CACHED_REAL_RAW640_30; no decode/Local inference',deadline_ms=100)


def evaluate(rows,final,errors,rate,start):
    from campaign_analysis import quantiles
    duration=30;count=rate*duration
    ids=[r['edge_request_id'] for r in rows]
    failures=list(errors)
    if len(ids)!=count or set(ids)!=set(range(count)):failures.append('Missing/duplicate assigned IDs')
    expired=[r for r in rows if r.get('terminal_state')=='EXPIRED_DROP']
    complete=[r for r in rows if r.get('response_completion_ns') is not None]
    if len(expired)+len(complete)!=count:failures.append('Incomplete drain')
    for r in expired:
        if r.get('socket_submission_ns') or r.get('response_completion_ns') or r['expired_drop_ns']<r['absolute_deadline_ns']:failures.append('Invalid expiry')
    for r in complete:
        if not r['logical_arrival_ns']<=r['payload_ready_ns']<=r['socket_submission_ns']<=r['response_completion_ns']:failures.append('Thor timestamp order')
        if r.get('payload_sha256')!=r.get('raw_sha256'):failures.append('Payload hash')
    dropids=sorted(r['edge_request_id'] for r in expired)
    if final.get('expired_request_ids')!=dropids or final.get('assigned')!=count:failures.append('Expiry ledger')
    if any(final.get(k)!=len(complete) for k in ('received','completed','responses_sent')):failures.append('Server accounting')
    if final.get('integrity_status')!='VALID' or not all(final.get(k) for k in ('drain_completed','cleanup_completed','worker_thread_exited')):failures.append('Server integrity/lifecycle')
    if any(final.get(k) for k in ('drops','duplicates','queue_cap_saturation','errors')):failures.append('Server error/drop/cap')
    lat=[(r['response_completion_ns']-r['logical_arrival_ns'])/1e6 for r in complete]
    timely=sum(x<=100 for x in lat)
    return dict(rate=rate,seconds=30,admitted=count,completed=len(complete),expired=len(expired),timely=timely,
        Edge_timely_ratio=timely/count,timely_FPS=timely/30,Edge_E2E_ms=quantiles(lat),
        errors=failures,integrity_status='INVALID' if failures else 'VALID',after_drain_unfinished=count-len(complete)-len(expired))


def require_pass(plan,output):
    report=json.loads((output/'gate.json').read_text())
    if report.get('plan_sha256')!=cfg.sha(plan) or report.get('verdict')!='PASS':raise RuntimeError('PASS Edge preflight required; EDGE_PATH_LIMITED/invalid requires user decision')
    if len(report['runs'])!=3 or any(r['integrity_status']!='VALID' for r in report['runs']):raise RuntimeError('Incomplete Edge preflight')
    if report['runs'][-1]['rate']!=80 or report['runs'][-1]['Edge_timely_ratio']<.90:raise RuntimeError('E80 below90%')
    for name,h in report['artifact_sha256'].items():
        if cfg.sha(output/name)!=h:raise RuntimeError('Edge preflight artifact changed')


def run(approval):
    plan=cfg.load_plan('B');root=cfg.out('B');digest=cfg.sha(root/'plan.json')
    if approval!=digest:raise RuntimeError('Explicit block-B plan hash required')
    from run_campaign import Context
    Context('B',cfg.ROOT/'scripts/timely_capacity_campaign/block_b_split/run_block.py').check_inputs()
    output=root/'edge_preflight01';output.mkdir(exist_ok=False)
    payloads,_=prior.old.edge_runtime.load_cache(cfg.ROOT/plan['cache']['path'])
    class Link(pruning.EdgeLink):pass
    fn=pruning.EdgeLink.__init__
    Link.__init__=types.FunctionType(fn.__code__,dict(fn.__globals__,hello=hello),fn.__name__,fn.__defaults__,fn.__closure__)
    results=[]
    for index,c in enumerate(plan['edge_preflight_order']):
        if index:time.sleep(plan['idle_seconds'])
        d=output/c['run_id'];d.mkdir();m={};errors=[];rows=[];link=None;start=None
        try:
            cc=dict(c,edge_r=c['rate']//8)
            link=Link(cc,c['run_id'],m,d,errors.append,digest,plan['edge_host'])
            start=time.monotonic_ns()+200_000_000
            for rid in range(c['rate']*30):
                due=start+rid*10**9//c['rate'];delay=(due-time.monotonic_ns())/1e9
                if delay>0:time.sleep(delay)
                row=dict(edge_request_id=rid,logical_arrival_ns=due,absolute_deadline_ns=due+100_000_000,
                    edge_release_target_ns=due,placement='EDGE',admitted=1,sample_id=rid%len(payloads))
                rows.append(row);link.put(row,payloads[rid%len(payloads)])
            delay=(start+30*10**9-time.monotonic_ns())/1e9
            if delay>0:time.sleep(delay)
            link.finish()
            if not link.done.wait(300):raise RuntimeError('Edge drain timeout')
        except BaseException:errors.append(traceback.format_exc())
        finally:
            if link is not None:link.close()
        from campaign_analysis import write_csv
        if rows:write_csv(d/'requests.csv',rows)
        try:s=evaluate(rows,m.get('edge_final',{}),errors,c['rate'],start)
        except Exception:s=dict(rate=c['rate'],integrity_status='INVALID',errors=errors+[traceback.format_exc()])
        with (d/'stderr.log').open('x') as f:f.write('\n'.join(s.get('errors',[])))
        for name,obj in [('manifest.json',dict(m,plan_sha256=digest,active_start_ns=start,active_end_ns=start+30*10**9 if start else None,
            input_scope='Cached RAW64030; expired-only sender; no decode/Local inference')),('summary.json',s)]:
            with (d/name).open('x') as f:json.dump(obj,f,indent=2)
        results.append(dict(run_id=c['run_id'],**s));print(results[-1],flush=True)
        if s['integrity_status']!='VALID':break
    verdict='PASS' if len(results)==3 and all(r['integrity_status']=='VALID' for r in results) and results[-1]['Edge_timely_ratio']>=.90 else 'EDGE_PATH_LIMITED' if len(results)==3 and results[-1]['integrity_status']=='VALID' and results[-1]['Edge_timely_ratio']<.90 else 'INCONCLUSIVE'
    hashes={str(p.relative_to(output)):cfg.sha(p) for p in output.rglob('*') if p.is_file()}
    with (output/'gate.json').open('x') as f:json.dump(dict(plan_sha256=digest,verdict=verdict,runs=results,artifact_sha256=hashes),f,indent=2)
    print(verdict)
    return 0 if verdict=='PASS' else 1


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--approve-plan-sha256',required=True);a=ap.parse_args();raise SystemExit(run(a.approve_plan_sha256))
