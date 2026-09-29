#!/usr/bin/env python3
"""Explicit campaign only; check is CPU/read-only and never touches clock control."""
import argparse
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import subprocess
import traceback

from common import ROOT, OUT, PLAN, PREFLIGHT, prior, load_plan, sha, decorate, remaining, EdgeLink, require_preflight
import run_coupling_pilot as pilot
hybrid, base, frequency = prior.hybrid, prior.hybrid.base, prior.hybrid.frequency


def write_json(path, data):
    if Path(path).parent.parent != OUT:
        raise RuntimeError('Run writer outside formal result directory')
    base.write_json(path, data)


def adapted_source():
    s = pilot.adapted_source()
    s = hybrid.replace_once(s, 'from analyze_coupling import summarize', 'from analyze_formal import summarize')
    s = hybrid.replace_once(s, "experiment='HYBRID_COUPLING_PILOT'", "experiment='FORMAL_HYBRID_E0_E40'")
    s = hybrid.replace_once(s, "order_index=condition['order_index'])",
                           "order_index=condition['order_index'], frequency_preflight=require_preflight())")
    return s


def bindings():
    ns = dict(base.__dict__, OUT=OUT, EXECUTION_PLAN=PLAN, CAPABILITY=hybrid.CAPABILITY,
              load_plan=load_plan, write_json=write_json, sha=sha, EdgeLink=EdgeLink, decorate=decorate,
              remaining=remaining, FRAME_FIELDS=base.FRAME_FIELDS+prior.EXTRA_FIELDS,
              require_preflight=require_preflight, __file__=__file__)
    exec(compile(adapted_source(), '<formal-E0-E40-frozen-adapter>', 'exec'), ns)
    s = hybrid.replace_once(inspect.getsource(base.finalize_run),
        'from analyze_rate_dvfs_gate import summarize,read_csv', 'from analyze_formal import summarize,read_csv')
    exec(compile(s, '<formal-E0-E40-finalizer>', 'exec'), ns)
    return ns['run_one'], ns['finalize_run']


def check_inputs():
    if subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() != 'rate-dvfs-gate':
        raise RuntimeError('Wrong branch; no branch change attempted')
    p = load_plan()
    for key in ('source_sha256', 'authoritative_evidence_sha256'):
        for path, digest in p[key].items():
            if sha(ROOT/path) != digest:
                raise RuntimeError('Frozen input hash mismatch: '+path)
    for source in p['inputs']:
        if sha(Path(source['path'])) != source['sha256']:
            raise RuntimeError('Source video hash mismatch: '+source['path'])
    if sha(base.ENGINE) != p['engine_provenance']['sha256'] or sha(ROOT/p['cache']['path']) != p['cache']['sha256']:
        raise RuntimeError('Canonical engine/cache hash mismatch')
    bindings()
    return p


def frequency_preflight():
    """Only called by explicit future campaign, once; use historical helper only."""
    if PREFLIGHT.exists():
        raise RuntimeError('Preflight artifact exists; no retry or overwrite')
    record = dict(status='FAIL', utc=datetime.now(timezone.utc).isoformat(), plan_sha256=sha(PLAN),
                  GPU_workload=False, pin_attempted=False, idle_cur_freq_zero_is_not_failure=True)
    try:
        record['capability'] = frequency.inspect()
        frequency.require_control()
        record['start'] = frequency.read_range()
        if (record['start']['min_freq'], record['start']['max_freq']) != (315000000, 1575000000):
            raise RuntimeError('Default starting range required')
        record['pin_attempted'] = True
        with frequency.pinned(1575):
            record['pinned'] = frequency.read_range()
            if (record['pinned']['min_freq'], record['pinned']['max_freq']) != (1575000000, 1575000000):
                raise RuntimeError('Pin readback mismatch')
        record['restored'] = frequency.read_range()
        if (record['restored']['min_freq'], record['restored']['max_freq']) != (315000000, 1575000000):
            raise RuntimeError('Restore readback mismatch')
        record['status'] = 'PASS'
    except BaseException:
        record['error'] = traceback.format_exc()
        raise
    finally:
        with PREFLIGHT.open('x') as f:
            json.dump(record, f, indent=2)
            f.write('\n')


def campaign():
    plan = check_inputs()
    if any((OUT/c['run_id']).exists() for c in plan['order']):
        raise RuntimeError('Planned run exists; no retry/overwrite')
    frequency_preflight()
    # Reuse the proven sequential child supervisor and its restore/exit finalization.
    ns = dict(hybrid.__dict__, OUT=OUT, PLAN=PLAN, __file__=__file__, check_inputs=check_inputs,
              load_plan=load_plan, bindings=bindings, write_json=write_json)
    s = inspect.getsource(hybrid.campaign)
    s = hybrid.replace_once(s, 'admission_fps_per_stream=30,', "admission_fps_per_stream=25+c['edge_r'], edge_r=c['edge_r'],")
    s = hybrid.replace_once(s, "return 0 if mode=='primary' or smoke_pass(plan) else 1",
        "return 0 if all(json.loads((OUT/c['run_id']/'summary.json').read_text()).get('integrity_status')=='VALID' for c in plan['order']) else 1")
    exec(compile(s, '<formal-E0-E40-supervisor>', 'exec'), ns)
    return ns['campaign']('formal')  # No new smoke or historical pilot is run.


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['check', 'campaign', 'one'])
    ap.add_argument('--run-id')
    a = ap.parse_args()
    if a.action == 'check':
        check_inputs()
        print('Input/plan/adapter PASS; no GPU/network/frequency access')
        return 0
    if a.action == 'campaign':
        return campaign()
    p = check_inputs()
    require_preflight()
    conditions = [c for c in p['order'] if c['run_id'] == a.run_id]
    if len(conditions) != 1:
        raise RuntimeError('Unplanned run')
    # This is the supervisor's child entry, not a retry interface.
    seed = OUT/a.run_id/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):
        raise RuntimeError('Fresh supervisor seed required')
    return bindings()[0](conditions[0], a.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
