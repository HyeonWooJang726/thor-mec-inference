"""Frozen hybrid placement and CPU-only shared helpers; no hardware on import."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'results/hybrid_capacity_extension'
PLAN = OUT/'plan.json'
sys.path.insert(0, str(ROOT/'scripts/edge_raw_capacity_gate'))
import formal_protocol as wire
import profile_edge_concurrency as edge_runtime

RESIDUES = (0, 0, 1, 2, 3, 3, 4, 5)
EXTRA_FIELDS = ['placement','edge_request_id','edge_release_target_ns',
                'resize_start_ns','resize_end_ns','payload_ready_ns','socket_submission_ns',
                'socket_send_complete_ns','response_completion_ns','payload_sha256','raw_sha256',
                'edge_receive_complete_ns','edge_queue_enter_ns','edge_queue_start_ns',
                'edge_preprocess_start_ns','edge_preprocess_end_ns','edge_inference_start_ns',
                'edge_inference_end_ns','edge_response_ready_ns']


def sha(path):
    return wire.sha(path)


def load_plan():
    plan = json.loads(PLAN.read_text())
    if plan['freeze_status'] != 'FROZEN_HYBRID_200_LOCAL_40_EDGE':
        raise RuntimeError('hybrid plan not frozen')
    assert tuple(plan['placement']['edge_frame_residues_mod6']) == RESIDUES
    assert len(plan['smoke']) == 1 and len(plan['order']) == 3
    for c in plan['smoke'] + plan['order']:
        assert (c['K'], c['C'], c['r'], c['frequency']) == (8, 2, 30, 'HIGH')
        assert c['seconds'] == (10 if c['kind']=='smoke' else 60)
    return plan


def decorate(row, start):
    """Keep source cadence unchanged. Delay only Edge eligibility, not arrivals.

    One Edge frame per 6 frames per stream; sender targets exactly 25 ms apart.
    A late earlier frame blocks later IDs, preserving the frozen temporal order.
    """
    s, f = int(row['stream_id']), int(row['frame_id'])
    edge = f % 6 == RESIDUES[s]
    row['placement'] = 'EDGE' if edge else 'LOCAL'
    if edge:
        rid = (f//6)*8+s
        row['edge_request_id'] = rid
        row['edge_release_target_ns'] = start+rid*25_000_000
        if row['edge_release_target_ns'] < row['logical_arrival_ns']:
            raise RuntimeError('invalid Edge release before source arrival')
    return row


def remaining(raw):
    return edge_runtime.remaining_preprocess(raw)


def hello(condition, run_id, plan_sha):
    return dict(mode='hybrid_smoke' if condition['kind']=='smoke' else 'hybrid_primary',
                repeat=condition.get('repeat', 0), rate=40, seconds=condition['seconds'],
                run_id=run_id, cache_sha256=edge_runtime.CACHE_SHA256,
                hybrid_plan_sha256=plan_sha,
                payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
