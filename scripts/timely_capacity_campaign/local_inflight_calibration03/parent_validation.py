"""Post-child cardinality checks shared with the calibration offline analyzer."""
import json
import csv

from integrity import validate_cardinality


def validate_parent_artifacts(directory, manifest, raw, measured):
    with (directory/'per_frame_phase_timestamps.csv').open(newline='') as source:
        phase = list(csv.DictReader(source))
    workers = json.loads((directory/'phase_instrumentation_manifest.json').read_text())
    report = validate_cardinality({'C': manifest['C']}, manifest, raw, phase, workers)
    if report['status'] != 'PASS':
        measured['errors'] = list(measured.get('errors', [])) + report['errors']
        measured.update(integrity_status='INVALID', validity='INVALID',
                        pipeline_audit_status='FAIL')
    return measured
