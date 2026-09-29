"""Frozen synchronous source due times and deterministic equal-admission placement."""
from functools import lru_cache
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/equal_service_map'))
import common as equal
import run_map as proven_runner
import analyze_map as proven_analysis

OUT = ROOT/'results/canonical_timely_service'
PLAN = OUT/'plan.json'
PREFLIGHT = OUT/'frequency_preflight.json'
sha, remaining, prior = equal.sha, equal.remaining, equal.prior
DEADLINES = (40, 60, 80, 100, 150, 200)
CELLS = {'T160-A': (160, 160, 0), 'T160-B': (160, 144, 16),
         'T200-A': (200, 200, 0), 'T200-B': (200, 184, 16),
         'T240-A': (240, 240, 0), 'T240-B': (240, 200, 40)}
ORDERS = (('T160-A','T160-B','T200-B','T200-A','T240-A','T240-B'),
          ('T240-B','T240-A','T200-A','T200-B','T160-B','T160-A'),
          ('T200-A','T200-B','T240-B','T240-A','T160-A','T160-B'))


def expected_order():
    rows = []
    for repeat, order in enumerate(ORDERS, 1):
        for cell in order:
            target, local, edge = CELLS[cell]
            mode = cell[-1]
            rows.append(dict(run_id=f'CTSM_R{repeat}_{cell.replace("-", "_")}_P01',
                kind='formal', repeat=repeat, order_index=len(rows)+1, cell=cell,
                supply_mode=mode, target_service_FPS=target, local_r=local//8, edge_r=edge//8,
                K=8, C=2, r=30, frequency='F1575', frequency_MHz=1575, seconds=60,
                pass_name=f'R{repeat}', **{'pass': f'R{repeat}'}))
    return rows


@lru_cache(None)
def schedule(target, mode):
    # Same phase-accumulator/eligibility rule as frozen Equal-Service, extended to240.
    total, local, edge = CELLS[f'T{target}-{mode}']
    r = total//8
    admitted = tuple(f for f in range(30) if (f+1)*r//30 > f*r//30)
    slots = {}
    if edge:
        first = admitted[0]*10**9//30
        for q in range(edge):
            release = first + q*10**9//edge
            f = max(f for f in admitted if f*10**9//30 <= release)
            key = (q % 8, f)
            if key in slots:
                raise RuntimeError('Duplicate Edge identity')
            slots[key] = (q, release)
    return admitted, slots


def decorate(row, start, target, mode):
    sid, f = int(row['stream_id']), int(row['frame_id'])
    if sid not in range(8) or int(row['logical_arrival_ns']) != start+f*10**9//30:
        raise ValueError('Canonical source phase/due timestamp mismatch')
    second, within = divmod(f, 30)
    admitted, slots = schedule(target, mode)
    row['admitted'] = int(within in admitted)
    row['placement'] = 'LOCAL' if row['admitted'] else 'SKIP'
    row.pop('edge_request_id', None)
    row.pop('edge_release_target_ns', None)
    if (sid, within) in slots:
        q, offset = slots[sid, within]
        edge = CELLS[f'T{target}-{mode}'][2]
        row.update(placement='EDGE', edge_request_id=second*edge+q,
                   edge_release_target_ns=start+second*10**9+offset)
        if row['edge_release_target_ns'] < row['logical_arrival_ns']:
            raise ValueError('Early Edge eligibility')
    return row


def placement_manifest():
    return dict(source_FPS_per_stream=30, common_decode_resize_FPS=240,
        source_phase_ns=[0]*8, source_clock='t0 + stream_phase_ns + floor(frame_index*1e9/30)',
        t0='After worker warmup, empty queue and source PLAYING: Thor monotonic_ns()+200ms',
        admission='floor((f+1)*r/30)>floor(f*r/30), r=target/8; same A/B IDs',
        exclusion='SKIP only after common decode AND resize; no deadline-aware dropping',
        A_network='NO_CONNECTION',
        edge_eligibility='Uniform slots from first admitted due time; q%8 stream, latest admitted frame <= slot; logical arrival unchanged',
        cells={cell: dict(admitted_frame_ids_mod30=list(schedule(target, cell[-1])[0]),
            edge_slots=[dict(stream_id=sid, frame_id_mod30=f, request_id_mod_second=q,
                             release_offset_ns=ns)
                        for (sid,f),(q,ns) in sorted(schedule(target,cell[-1])[1].items(), key=lambda x:x[1][0])])
               for cell,(target,_,_) in CELLS.items()})


def load_plan():
    p = json.loads(PLAN.read_text())
    if (p['freeze_status'] != 'FROZEN_CANONICAL_TIMELY_SERVICE_V1'
        or p['order'] != expected_order() or p['smoke']
        or p['placement'] != placement_manifest() or p['deadlines_ms'] != list(DEADLINES)):
        raise RuntimeError('Frozen plan/order/arrival/deadline mismatch')
    return p


def hello(c, run_id, plan_sha):
    return dict(mode='canonical_timely_service', repeat=c['repeat'], rate=8*c['edge_r'],
        seconds=c['seconds'], run_id=run_id, timely_plan_sha256=plan_sha, cell=c['cell'],
        target_service_FPS=c['target_service_FPS'], frequency_MHz=1575,
        cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
        payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')


class ActiveLink(prior.ActiveEdgeLink):
    pass


_init = prior.ActiveEdgeLink.__init__
ActiveLink.__init__ = types.FunctionType(_init.__code__, dict(_init.__globals__, hello=hello),
    _init.__name__, _init.__defaults__, _init.__closure__)


def EdgeLink(c, *args, **kwargs):
    return (prior.UnusedEdgeLink if c['edge_r'] == 0 else ActiveLink)(c, *args, **kwargs)


def require_preflight():
    record = json.loads(PREFLIGHT.read_text())
    if record.get('status') != 'PASS' or record.get('plan_sha256') != sha(PLAN):
        raise RuntimeError('Current passing frequency preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)), sha256=sha(PREFLIGHT))
