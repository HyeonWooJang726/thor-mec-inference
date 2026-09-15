"""Pure validation of CSV evidence IDs before adding an image metadata row."""
import re


def image_metadata(sid, evidence):
    """Match a selected integer index to its canonical decimal CSV ID.

    Evidence CSV IDs are strings '0' through '299', without signs, whitespace
    or leading zeroes. Preserve all other fields and leave the input unchanged.
    """
    if type(sid) is not int or not 0 <= sid < 300:
        raise ValueError('Selected sample_id must be an integer index in 0..299')
    if 'sample_id' not in evidence:
        raise ValueError('Evidence is missing required sample_id')
    raw = evidence['sample_id']
    if type(raw) is not str or re.fullmatch(r'0|[1-9][0-9]{0,2}', raw) is None:
        raise ValueError(f'Evidence sample_id must be a canonical decimal CSV string: {raw!r}')
    normalized = int(raw)
    if not 0 <= normalized < 300:
        raise ValueError(f'Evidence sample_id outside 0..299: {raw!r}')
    if normalized != sid:
        raise ValueError(f'Evidence sample_id {normalized} does not match selected sample_id {sid}')
    result = dict(evidence)
    result['sample_id'] = normalized  # Only after validating identity; no silent overwrite.
    return result
