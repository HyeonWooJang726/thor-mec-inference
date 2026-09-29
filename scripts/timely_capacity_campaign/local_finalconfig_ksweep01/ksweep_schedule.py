"""Strict K-aware Local-only specialization of the frozen r=30 ALIGNED rule.

At r=30 the historical floor mask admits every source slot. This adapter
changes only the number of physical streams; it rejects non-Local conditions.
"""


def decorate(row, start, condition):
    k = int(condition['K'])
    sid, frame = int(row['stream_id']), int(row['frame_id'])
    if not (1 <= k <= 8 and 0 <= sid < k and frame >= 0):
        raise ValueError('K-specific source ID mismatch')
    rate = condition.get('r', condition.get('admission_fps_per_stream'))
    if (condition['C'] != 3 or condition['local_r'] != 30 or
            condition['edge_r'] != 0 or rate != 30 or
            condition['target_service_FPS'] != 30*k or
            condition['admission_pattern'] != 'ALIGNED' or
            condition['deadline_ms'] != 100 or
            row['logical_arrival_ns'] != start + frame*10**9//30):
        raise ValueError('K-sweep Local source/condition mismatch')
    row['admitted'] = 1
    row['placement'] = 'LOCAL'
    for key in ('edge_request_id', 'edge_release_target_ns',
                'absolute_deadline_ns'):
        row.pop(key, None)
    row['absolute_deadline_ns'] = row['logical_arrival_ns'] + 100_000_000
    return row
