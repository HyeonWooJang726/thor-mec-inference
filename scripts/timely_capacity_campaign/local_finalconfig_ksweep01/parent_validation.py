"""Post-child cardinality checks shared with the calibration offline analyzer."""
import json
import csv

from integrity import validate_cardinality, validate_source
from config import load_plan


def validate_parent_artifacts(directory, manifest, raw, measured):
    with (directory/'per_frame_phase_timestamps.csv').open(newline='') as source:
        phase = list(csv.DictReader(source))
    workers = json.loads((directory/'phase_instrumentation_manifest.json').read_text())
    c = validate_cardinality({'C': manifest['C']}, manifest, raw, phase, workers)
    matches = [row for row in load_plan()['order'] if row['run_id'] == manifest['run_id']]
    if len(matches) != 1:
        raise RuntimeError('Parent finalizer run outside frozen K-sweep plan')
    k = validate_source(matches[0], manifest, raw, measured)
    errors = c['errors'] + k['errors']
    if errors:
        measured['errors'] = list(measured.get('errors', [])) + errors
        measured.update(integrity_status='INVALID', validity='INVALID',
                        pipeline_audit_status='FAIL')
    return measured
