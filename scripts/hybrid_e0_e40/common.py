"""Formal E0/E40 configuration; frozen P02 placement and transport reuse."""
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/hybrid_coupling_pilot'))
import pilot_common as prior

OUT = ROOT/'results/hybrid_e0_e40'
PLAN = OUT/'plan.json'
PREFLIGHT = OUT/'frequency_preflight.json'
RATES = (0, 40, 40, 0, 0, 40, 40, 0, 0, 40)
decorate, remaining, sha = prior.decorate, prior.remaining, prior.sha


def load_plan():
    p = json.loads(PLAN.read_text())
    if p['freeze_status'] != 'FROZEN_FORMAL_E0_E40_V1':
        raise RuntimeError('Wrong formal plan')
    assert not p['smoke'] and len(p['order']) == 10
    for i, (c, rate) in enumerate(zip(p['order'], RATES)):
        assert c['run_id'] == f'HEF_R{i//2+1}_E{rate:02d}_P01'
        assert (c['K'], c['C'], c['r'], c['edge_r'], c['frequency'], c['seconds']) == (8, 2, 30, rate//8, 'HIGH', 60)
        assert (c['repeat'], c['pass'], c['order_index']) == (i//2+1, f'R{i//2+1}', i+1)
    assert p['placement'] == json.loads((prior.OUT/'plan_ab02.json').read_text())['placement']
    return p


def hello(c, run_id, plan_sha):
    return dict(mode='formal_e0_e40', repeat=c['repeat'], rate=8*c['edge_r'],
                seconds=c['seconds'], run_id=run_id, formal_plan_sha256=plan_sha,
                cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
                payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')


class ActiveLink(prior.ActiveEdgeLink):
    pass


# Identical count-aware P02 constructor; only the HELLO protocol label/plan key changes.
_init = prior.ActiveEdgeLink.__init__
ActiveLink.__init__ = types.FunctionType(_init.__code__, dict(_init.__globals__, hello=hello),
                                        _init.__name__, _init.__defaults__, _init.__closure__)


def EdgeLink(c, *args, **kwargs):
    return (prior.UnusedEdgeLink if c['edge_r'] == 0 else ActiveLink)(c, *args, **kwargs)


def require_preflight():
    record = json.loads(PREFLIGHT.read_text())
    if record.get('status') != 'PASS' or record.get('plan_sha256') != sha(PLAN):
        raise RuntimeError('Passing current-plan frequency preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)), sha256=sha(PREFLIGHT))
