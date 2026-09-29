"""Pure CPU-only 208-FPS admission masks and deterministic phase search."""
import hashlib
import math
from collections import Counter

PERIOD = 30
STREAMS = 8
RATE_PER_STREAM = 26
CANONICAL_BITS = '011111101111111011111101111111'
P = tuple(int(bit) for bit in CANONICAL_BITS)
assert len(P) == PERIOD and sum(P) == RATE_PER_STREAM
PATTERN_SHA256 = hashlib.sha256(CANONICAL_BITS.encode('ascii')).hexdigest()


def mask(delta):
    if not isinstance(delta, int) or not 0 <= delta < PERIOD:
        raise ValueError('Cyclic phase must be an integer in 0..29')
    return tuple(P[(slot - delta) % PERIOD] for slot in range(PERIOD))


def masks(phases):
    if len(phases) != STREAMS or phases[0] != 0:
        raise ValueError('Exactly eight phases, delta_1=0 fixed')
    return tuple(mask(int(phase)) for phase in phases)


def slot_counts(phases):
    current = tuple(mask(int(phase)) for phase in phases)
    return tuple(sum(row[slot] for row in current) for slot in range(PERIOD))


def score(phases):
    counts = slot_counts(phases)
    total = sum(counts)
    # Integer variance numerator avoids floating-point tie instability.
    variance_numerator = sum((PERIOD * value - total) ** 2 for value in counts)
    return max(counts), variance_numerator


def summarize(phases):
    counts = slot_counts(phases)
    maximum, variance_numerator = score(phases)
    ordered = sorted(counts)
    p95 = ordered[math.ceil(.95 * PERIOD) - 1]
    return {'phases': list(phases), 'max_m_n': maximum,
            'variance_population': variance_numerator / PERIOD**3,
            'variance_integer_numerator': variance_numerator,
            'mean_m_n': sum(counts) / PERIOD, 'p95_m_n': p95,
            'm_n': list(counts), 'histogram': dict(sorted(Counter(counts).items())),
            'theoretical_primary_lower_bound': math.ceil(STREAMS * RATE_PER_STREAM / PERIOD),
            'primary_lower_bound_achieved': maximum == math.ceil(STREAMS * RATE_PER_STREAM / PERIOD),
            'global_variance_optimum_claim': False, 'global_phase_optimum_claim': False}


def search():
    phases = [0]
    greedy = []
    for stream_index in range(1, STREAMS):
        candidates = []
        for delta in range(PERIOD):
            maximum, variance_numerator = score(phases + [delta])
            candidates.append({'delta': delta, 'candidate_max': maximum,
                               'candidate_variance': variance_numerator / PERIOD**3,
                               'variance_integer_numerator': variance_numerator})
        selected = min(candidates, key=lambda row:(row['candidate_max'], row['variance_integer_numerator'], row['delta']))
        phases.append(selected['delta'])
        greedy.append({'stream_index_zero_based': stream_index, 'candidates': candidates,
                       'selected_delta': selected['delta'],
                       'selected_score': [selected['candidate_max'], selected['variance_integer_numerator']]})
    greedy_phases = phases.copy()
    sweeps = []
    for sweep_index in range(1, 101):
        steps = []
        updates = 0
        for stream_index in range(1, STREAMS):
            candidates = []
            for delta in range(PERIOD):
                trial = phases.copy()
                trial[stream_index] = delta
                maximum, variance_numerator = score(trial)
                candidates.append({'delta': delta, 'candidate_max': maximum,
                                   'candidate_variance': variance_numerator / PERIOD**3,
                                   'variance_integer_numerator': variance_numerator})
            best = min(candidates, key=lambda row:(row['candidate_max'], row['variance_integer_numerator'], row['delta']))
            old = (*score(phases), phases[stream_index])
            proposed = (best['candidate_max'], best['variance_integer_numerator'], best['delta'])
            changed = proposed < old
            if changed:
                phases[stream_index] = best['delta']
                updates += 1
            steps.append({'stream_index_zero_based': stream_index, 'old_score_with_phase': list(old),
                          'best_score_with_phase': list(proposed), 'strict_improvement': changed,
                          'selected_delta': phases[stream_index], 'candidates': candidates})
        sweeps.append({'sweep': sweep_index, 'updates': updates, 'steps': steps,
                       'phase_set_after_sweep': phases.copy()})
        if not updates:
            break
    return {'algorithm': 'greedy_then_coordinate_descent',
            'stream_order': list(range(STREAMS)), 'fixed_phase': {'stream_id': 0, 'delta': 0},
            'candidate_phases_per_stream': list(range(PERIOD)),
            'maximum_sweeps_frozen': 100, 'greedy_history': greedy,
            'greedy_selected_phases': greedy_phases, 'coordinate_descent_sweeps': sweeps,
            'coordinate_descent_stopped_no_improvement': sweeps[-1]['updates'] == 0,
            'tie_break': 'minimize (max_m_n, integer_variance_numerator, smallest_delta) lexicographically; strictly improving updates only',
            'canonical_pattern_sha256': PATTERN_SHA256, **summarize(phases)}


def skip_gap_multiset(binary):
    skips = [i for i, value in enumerate(binary) if not value]
    if len(skips) != PERIOD - RATE_PER_STREAM:
        raise ValueError('Expected four skipped source slots')
    return sorted((skips[(i + 1) % len(skips)] - skips[i]) % PERIOD for i in range(len(skips)))


def decorate(row, active_start_ns, condition, phases):
    sid, frame_id = int(row['stream_id']), int(row['frame_id'])
    if sid not in range(STREAMS) or not 0 <= frame_id < 60 * PERIOD:
        raise ValueError('Source frame outside frozen 8×60×30 universe')
    logical = active_start_ns + frame_id * 10**9 // 30
    if int(row['logical_arrival_ns']) != logical:
        raise ValueError('Source logical arrival changed')
    if condition['target_service_FPS'] != 208 or condition['edge_r'] != 0:
        raise ValueError('Outside Local-only 208 pilot')
    pattern = condition['admission_pattern']
    if pattern not in ('ALIGNED', 'STAGGERED'):
        raise ValueError('Unknown phase pattern')
    delta = 0 if pattern == 'ALIGNED' else phases[sid]
    admitted = P[(frame_id % PERIOD - delta) % PERIOD]
    row['admitted'] = admitted
    row['placement'] = 'LOCAL' if admitted else 'SKIP'
    for name in ('edge_request_id', 'edge_release_target_ns', 'absolute_deadline_ns'):
        row.pop(name, None)
    if admitted:
        row['absolute_deadline_ns'] = logical + condition['deadline_ms'] * 1_000_000
    return row
