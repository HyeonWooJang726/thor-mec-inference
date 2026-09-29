"""Read-only reconstruction of within-slot dispatch positions from source logs.

This module performs no scheduling. It is used only after a run has written raw
source-frame rows. Position is the observed source dispatch order within the
same destination and source slot, not a GPU or network completion order.
"""
from collections import defaultdict


def positions(rows, destination_field='placement'):
    groups = defaultdict(list)
    for row in rows:
        if row.get(destination_field) in ('LOCAL', 'EDGE'):
            groups[(int(row['frame_id']), row[destination_field])].append(row)
    out = {}
    for (frame, destination), group in groups.items():
        ordered = sorted(group, key=lambda row: int(row['admission_observed_ns']))
        timestamps = [int(row['admission_observed_ns']) for row in ordered]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError('Source dispatch timestamp tie; position ambiguous')
        for position, row in enumerate(ordered):
            identity = (int(row['stream_id']), frame)
            if identity in out:
                raise ValueError('Duplicate source identity')
            out[identity] = {'destination': destination,
                             'source_slot': frame, 'dispatch_position': position}
    return out
