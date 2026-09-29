"""Synthetic boundary/accounting tests only; never connects or accesses GPU controls."""
import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import campaign_config as cfg
import edge_preflight as ep
import run_campaign as runner


def fixture(rate, timely_fraction):
    count = rate * 30
    rows = []
    for i in range(count):
        due = 1_000_000_000 + i * 10**9 // rate
        latency = 90_000_000 if i < int(count * timely_fraction) else 110_000_000
        rows.append(dict(edge_request_id=i, logical_arrival_ns=due,
            absolute_deadline_ns=due+100_000_000, payload_ready_ns=due+1,
            socket_submission_ns=due+2, response_completion_ns=due+latency,
            payload_sha256='CPU_SYNTHETIC', raw_sha256='CPU_SYNTHETIC'))
    final = dict(expired_request_ids=[], assigned=count, received=count,
        completed=count, responses_sent=count, integrity_status='VALID',
        drain_completed=True, cleanup_completed=True, worker_thread_exited=True,
        drops=0, duplicates=0, queue_cap_saturation=0, errors=[])
    return rows, final


def main():
    scratch = Path(tempfile.mkdtemp(prefix='tcc_preflight_CPU_'))
    plan = scratch/'plan.json'
    plan.write_text('CPU_SYNTHETIC_NOT_A_CAMPAIGN_PLAN')
    summaries = []
    for rate in (56, 72, 80):
        rows, final = fixture(rate, .90)
        s = ep.evaluate(rows, final, [], rate, 1_000_000_000)
        assert s['integrity_status']=='VALID' and s['Edge_timely_ratio']==.90
        summaries.append(s)
        bad = copy.deepcopy(rows); bad[1]['edge_request_id']=bad[0]['edge_request_id']
        assert ep.evaluate(bad, final, [], rate, 1_000_000_000)['integrity_status']=='INVALID'
    gate = dict(plan_sha256=cfg.sha(plan), verdict='PASS', runs=summaries, artifact_sha256={})
    (scratch/'gate.json').write_text(json.dumps(gate))
    ep.require_pass(plan, scratch)
    gate['runs'][-1]['Edge_timely_ratio']=.90-1/2400
    (scratch/'gate.json').write_text(json.dumps(gate))
    try: ep.require_pass(plan, scratch)
    except RuntimeError: pass
    else: raise AssertionError('Sub90% must block primary')
    # Exact client/server handshake compatibility, without opening a socket.
    spec=importlib.util.spec_from_file_location('pruning_edge_server',cfg.ROOT/'scripts/expired_work_pruning/edge_server.py')
    old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    spec=importlib.util.spec_from_file_location('tcc_edge_launcher',cfg.ROOT/'scripts/timely_capacity_campaign/block_b_split/edge_server.py')
    edge=importlib.util.module_from_spec(spec);spec.loader.exec_module(edge)
    ctx=runner.Context('B',cfg.ROOT/'scripts/timely_capacity_campaign/block_b_split/run_block.py')
    cache=ep.prior.old.edge_runtime.CACHE_SHA256
    for c in cfg.expected_order('B'):
        assert ctx.hello(c,c['run_id'],'CPU')==edge.expected(c,'CPU','primary',cache)
    for c in cfg.preflight_order():
        assert ep.hello(dict(c,edge_r=c['rate']//8),c['run_id'],'CPU')==edge.expected(c,'CPU','preflight',cache)
    report=dict(status='PASS',provenance='CPU_SYNTHETIC_NOT_MEASUREMENT',scratch=str(scratch),
        checks=['E56/E72/E80 accounting and missing/duplicate rejection',
            'E80 exactly90% passes; one frame below90% blocks',
            '35 primary plus3 preflight client/server HELLO dictionaries identical'],
        GPU_executed=False,network_executed=False,frequency_control_executed=False)
    with (cfg.out('B')/'edge_preflight_cpu_validation.json').open('x') as f:json.dump(report,f,indent=2)
    print('PASS: CPU preflight boundary, accounting, all38 handshake dictionaries')


if __name__=='__main__':main()
