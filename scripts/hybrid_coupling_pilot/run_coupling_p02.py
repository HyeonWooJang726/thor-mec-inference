#!/usr/bin/env python3
"""P02 entry point: unchanged A/B pilot with a new immutable execution plan.

No copied pipeline or frequency implementation. Parent and child use this same
entry point. check/verify/analyze do not perform frequency control or inference.
"""
import argparse
import json
from pathlib import Path
import sys

import pilot_common as common
import run_coupling_pilot as pilot

P02_PLAN = common.OUT / 'plan_ab02.json'
# Scoped to this process; original source and P01 plan stay byte-identical.
common.PLAN = P02_PLAN
pilot.PLAN = P02_PLAN
pilot.__file__ = str(Path(__file__).resolve())
original_check = pilot.check_inputs


def check_inputs():
    plan = original_check()
    expected = [f'COUPLING_AB_{p}_E{e:02d}_P02'
                for p, rates in [('A', (0, 8, 16, 24, 40)), ('B', (40, 24, 16, 8, 0))]
                for e in rates]
    if [c['run_id'] for c in plan['order']] != expected:
        raise RuntimeError('P02 run identity/order mismatch')
    evidence = plan['frequency_preflight']
    path = common.ROOT / evidence['path']
    if common.sha(path) != evidence['sha256']:
        raise RuntimeError('Frequency preflight provenance mismatch')
    preflight = json.loads(path.read_text())
    if any(preflight.get(k) != 'PASS' for k in ('status', 'pin_status', 'restore_status')):
        raise RuntimeError('Passing frequency preflight required')
    return plan


pilot.check_inputs = check_inputs


def execution_permission_check():
    """Existing helper's read-only check before child creation/Edge handshake.

    A historical PASS is not a guarantee that permissions still hold at execution.
    Actual pin/restore remains inside the unchanged workload context manager.
    """
    pilot.hybrid.frequency.require_control()
    bounds = pilot.hybrid.frequency.read_range()
    if (bounds['min_freq'], bounds['max_freq']) != (315000000, 1575000000):
        raise RuntimeError('Default 315–1575 MHz range required before execution')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['check', 'verify', 'pilot', 'one', 'analyze'])
    ap.add_argument('--run-id')
    ap.add_argument('--output')
    args = ap.parse_args()
    plan = check_inputs()
    if args.action == 'check':
        pilot.bindings()
        print('P02 plan/input/adapter PASS; CPU only; no frequency-control action')
        return 0
    if args.action == 'verify':
        if not args.output:
            ap.error('verify requires a new --output path')
        output = Path(args.output)
        if output.exists():
            raise RuntimeError('Refusing to overwrite CPU verification')
        from verify_coupling_cpu import verify
        result = verify()
        result.update(execution_plan=str(P02_PLAN), execution_plan_sha256=common.sha(P02_PLAN))
        with output.open('x') as f:
            json.dump(result, f, indent=2)
            f.write('\n')
        print(json.dumps(result, indent=2))
        return 0
    if args.action == 'analyze':
        if not args.output:
            ap.error('analyze requires a new --output directory')
        import analyze_coupling
        sys.argv = [sys.argv[0], '--output', args.output]
        analyze_coupling.main()
        return 0
    # These branches are supplied for later authorized pilot execution only.
    execution_permission_check()
    if args.action == 'one':
        matches = [c for c in plan['order'] if c['run_id'] == args.run_id]
        if len(matches) != 1:
            raise RuntimeError('Run outside P02 plan')
        return pilot.bindings()[0](matches[0], args.run_id)
    if any((common.OUT / c['run_id']).exists() for c in plan['order']):
        raise RuntimeError('P02 attempt already exists; no automatic retry/overwrite')
    return pilot.campaign()


if __name__ == '__main__':
    raise SystemExit(main())
