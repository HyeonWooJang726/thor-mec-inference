"""Attempt02 path binding around the preserved timely scan configuration."""
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import timely_config as frozen

ROOT = frozen.ROOT
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/timely_capacity_scan02'
PLAN = OUT / 'plan.json'
sha = frozen.sha
order = frozen.order
decorate = frozen.decorate
run_source = frozen.run_source


def _bound(fn, **replacements):
    return types.FunctionType(fn.__code__, dict(fn.__globals__, **replacements),
                              fn.__name__, fn.__defaults__, fn.__closure__)


def runtime_record():
    # Keep the frozen worker and parameter adapter. Only the attempt output and
    # plan paths change; all original source hashes are rechecked.
    return _bound(frozen.runtime_record, OUT=OUT, PLAN=PLAN)()


def load_plan():
    p = _bound(frozen.load_plan, OUT=OUT, PLAN=PLAN,
               runtime_record=runtime_record)()
    for relative, digest in json.loads((OUT / 'attempt02_source_sha256.json').read_text()).items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError('Attempt02 orchestration/analysis source drift: ' + relative)
    if p.get('attempt_namespace') != 'timely_capacity_scan02':
        raise RuntimeError('Attempt02 plan namespace mismatch')
    if p.get('prior_attempt_status') != 'PRE_WORKLOAD_FREQUENCY_PERMISSION_FAILURE':
        raise RuntimeError('Attempt01 failure reference mismatch')
    return p
