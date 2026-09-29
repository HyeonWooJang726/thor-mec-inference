#!/usr/bin/env python3
"""Correct only the Gate evaluator's accidental full-coverage prerequisite.

Preserve original outputs and M4 v1 predictions/specification. The user's FF>=2
SURVIVES branch is independent of completing all twelve frequency decisions.
No profile fitting, queue simulation, target replay, or measurement is performed.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def verdict(score, n, near_majority=False):
    # Missing predictions must not be fabricated, but existing independently
    # supported false-feasible observations remain evidence for the OR branch.
    if int(score['FALSE_FEASIBLE']) >= 2:
        return 'GATE0_MODEL_GAP_SURVIVES'
    if n == 12 and int(score['mismatches']) >= 3:
        return 'GATE0_MODEL_GAP_SURVIVES'
    if (n == 12 and int(score['known_frequency_decisions']) == 12
            and int(score['exact_matches']) >= 11
            and int(score['FALSE_FEASIBLE']) <= 1 and near_majority):
        return 'GATE0_KILL_MODEL_GAP'
    return 'GATE0_INCONCLUSIVE'


def main(source, output):
    if output.exists(): raise RuntimeError('New review destination required')
    paths=[p for p in source.rglob('*') if p.is_file()]
    before={str(p):sha(p) for p in paths}
    original=json.loads((source/'gate_verdict.json').read_text())
    with (source/'model_scores.csv').open() as f: scores=list(csv.DictReader(f))
    full=next(s for s in scores if s['model']=='M4' and s['scope']=='FULL-7')
    direct=next(s for s in scores if s['model']=='M4' and s['scope']=='DIRECT-ONLY')
    # Do not misuse the restricted-domain mismatch count as a FULL-7 mismatch.
    primary=dict(full, FALSE_FEASIBLE=direct['FALSE_FEASIBLE'])
    result=verdict(primary,original['PRIMARY']['usable_points'])
    assert result=='GATE0_MODEL_GAP_SURVIVES'
    assert json.loads((source/'verification.json').read_text())['status']=='PASS'
    assert all(x['status']=='INDEPENDENT_PARTIAL_TRANSFER_ASSUMPTIONS' for x in
               csv.DictReader((source/'leakage_audit.csv').open()) if x['model']=='M4')
    # Evaluator regression cases are synthetic, not added to measured results.
    base=dict(FALSE_FEASIBLE=0,mismatches=0,known_frequency_decisions=12,exact_matches=12)
    assert verdict(base,12,True)=='GATE0_KILL_MODEL_GAP'
    assert verdict(dict(base,FALSE_FEASIBLE=2,known_frequency_decisions=0,exact_matches=0),12)=='GATE0_MODEL_GAP_SURVIVES'
    assert verdict(dict(base,mismatches=3,exact_matches=9),12)=='GATE0_MODEL_GAP_SURVIVES'
    assert verdict(dict(base,known_frequency_decisions=0,exact_matches=0),12)=='GATE0_INCONCLUSIVE'
    output.mkdir()
    record=dict(created_UTC=datetime.now(timezone.utc).isoformat(),
        evaluator_version=2,model_version=1,model_modified=False,
        original_verdict=original['PRIMARY']['verdict'],corrected_verdict=result,
        reason='Remove accidental all-seven-anchors prerequisite from independent false-feasible>=2 OR branch; user criterion unchanged',
        direct_M4_false_feasible=int(direct['FALSE_FEASIBLE']),direct_endpoint_conditions=int(direct['confusion_conditions']),
        available_M4_false_feasible=int(full['FALSE_FEASIBLE']),available_endpoint_conditions=int(full['confusion_conditions']),
        FULL7_frequency_decisions_known=int(full['known_frequency_decisions']),
        direct_domain_frequency_mismatches_NOT_used=int(direct['mismatches']),
        M4_SPEC_SHA256=sha(source/'M4_SPEC.md'),prediction_SHA256=sha(source/'model_capacity_predictions.csv'),
        queue_prediction_SHA256=sha(source/'m4_queue_predictions.csv'),
        limits='Partial frequency coverage; K6->K8 concurrent-service and unlocked frontend transfer assumptions. Not a proof all possible queue models fail.',
        secondary_used_to_trigger_gate=False,input_hashes=before)
    with (output/'gate_verdict.json').open('x') as f:json.dump(record,f,indent=2)
    text=(source/'gate_verdict.md').read_text()
    text=text.replace(original['PRIMARY']['verdict'],result,1)
    text=text.replace(original['PRIMARY']['reason'],
        'The unchanged M4 produces3 false-feasible conditions out of6 confirmed endpoints at DIRECT-ONLY frequencies. '
        'Thus the original false-feasible>=2 OR criterion is met without interpolated parameters, secondary metrics, '
        'or a claim of complete seven-anchor frequency-selection coverage. Available5-frequency M4 has5/10 false-feasible endpoints.')
    text=text.replace('GATE0_INCONCLUSIVE does not authorize KILL or advancement to D100 Gate2. First resolve independent630/792 C2 profile coverage and '
        'the frontend transfer assumption in a separately authorized step; no new experiment is run here.',
        'Proceed to design of D100 timely Gate2, not execution. Complete630/792 independent profiles would still be needed '
        'for a full seven-anchor minimum-frequency comparison; do not fill them from target outcomes. '
        'This result applies to the specified transferred-profile M4, not every possible non-learned model.')
    text=text.replace('See SECONDARY.md', 'See ../SECONDARY.md')
    text += ('\n\n## Evaluator correction (original artifacts retained)\n\n'
        'The first evaluator incorrectly required full frequency coverage before either OR branch. '
        'Its GATE0_INCONCLUSIVE output remains in the parent directory as failed evaluator evidence. '
        'This review applies the original user criterion. M4 v1 equations, independent parameters, '
        'predictions and raw measurements are byte-identical; there is no M4-v2 model or refit. '
        'Only the evaluator is v2. The frozen M4_SPEC evaluation paragraph documented that erroneous '
        'extra prerequisite; this correction supersedes that paragraph, not the model specification.\n')
    with (output/'gate_verdict.md').open('x') as f:f.write(text)
    with (output/'D100_GATE2_DESIGN.md').open('x') as f:
        f.write('# Next step: D100 timely-feasibility Gate2 — proposal only\n\n'
        'Use a single canonical live-video harness and source logical due-time definition. '
        'Begin with held-out existing canonical FIFO T160-A/T200-A/T240-A raw cohorts at1575/C2/B1; '
        'do not pool earlier formal Local and canonical timely harness latencies. '
        'No GPU or network runs are authorized by this proposal.\n\n'
        'Before evaluation, freeze a queue model with the canonical physical240-FPS decode/resize workload, '
        'synchronized source phases and exact admitted masks. Carry independent service parameters forward '
        'without fitting target service, queue or latency. Resolve/label the frontend transfer assumption. '
        'For each admitted frame compute predicted completion minus source due time, including drain. '
        'At D100 report predicted/observed timely FPS, source-normalized TIR, worst-stream timely FPS/TIR, '
        'and all3repeats. Admission exclusions remain failures under the source denominator.\n\n'
        'Keep expired-pruning and Edge placement as separate follow-up mechanisms; they alter the queue process. '
        'Freeze any Gate2 acceptance rule before comparison; Gate0 supplies no arbitrary timely-good threshold. '
        'No controller, scheduler, new experiment, or superiority claim is implemented.\n')
    changed=[p for p,h in before.items() if sha(Path(p))!=h]
    assert not changed
    with (output/'verification.json').open('x') as f:json.dump(dict(status='PASS',original_files_preserved=len(before),
        model_predictions_identical=True,evaluator_CPU_tests='PASS',changed=changed,
        GPU_executed=False,network_executed=False),f,indent=2)
    print(json.dumps({k:v for k,v in record.items() if k!='input_hashes'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('results/gate0_model_ladder'))
    parser.add_argument('--output',type=Path,default=Path('results/gate0_model_ladder/criterion_review01'))
    args=parser.parse_args();main(args.source,args.output)
