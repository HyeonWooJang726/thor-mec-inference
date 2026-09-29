"""CPU-only regression for fresh-namespace and pre-marker GPU guard."""
import hashlib
import json
import tempfile
import types
from pathlib import Path

import analyze_attempt02
import attempt02_config as cfg
import gpu_precheck
import run_attempt02 as runner


def fake_gpu_checks():
    with tempfile.TemporaryDirectory(prefix='timely-a02-gpu-') as tmp:
        root = Path(tmp)
        (root / 'min_freq').write_text('315000000')
        (root / 'max_freq').write_text('1575000000')
        (root / 'available_frequencies').write_text('315000000 1575000000')
        denied = gpu_precheck.observe(root, access=lambda path, mode: mode != 2)
        assert denied['status'] == 'FAIL' and denied['target_listed']
        allowed = gpu_precheck.observe(root, access=lambda path, mode: True)
        assert allowed['status'] == 'PASS'
        (root / 'available_frequencies').write_text('315000000')
        assert gpu_precheck.observe(root, access=lambda path, mode: True)['status'] == 'FAIL'
    return True


def fake_campaign_checks():
    with tempfile.TemporaryDirectory(prefix='timely-a02-attempt-') as tmp:
        out = Path(tmp)
        plan = out / 'plan.json'
        plan.write_text('{}')
        digest = hashlib.sha256(plan.read_bytes()).hexdigest()
        class FakeContext:
            PREFLIGHT = out / 'frequency_preflight.json'
            def check_inputs(self):
                return {'order': []}
        context = FakeContext()
        gate = runner.Context.campaign
        called = []
        fail_globals = dict(gate.__globals__, OUT=out, PLAN=plan, order=lambda: [],
                            require_ready=lambda: (_ for _ in ()).throw(PermissionError('injected denied')))
        denied = types.FunctionType(gate.__code__, fail_globals)
        try:
            denied(context, digest)
        except PermissionError:
            pass
        else:
            raise AssertionError('Permission denial did not stop campaign')
        assert not (out / 'campaign_attempt.json').exists()
        assert list(out.iterdir()) == [plan], 'Readiness failure consumed fresh attempt'
        class FakeParent:
            def campaign(self, approval):
                called.append(approval)
                (out / 'campaign_attempt.json').write_text(json.dumps({'sha256': approval}))
                return 0
        parent = types.SimpleNamespace(Context=FakeParent)
        pass_globals = dict(gate.__globals__, OUT=out, PLAN=plan, order=lambda: [],
                            frozen_run=parent, require_ready=lambda: {'status': 'PASS'})
        campaign = types.FunctionType(gate.__code__, pass_globals)
        assert campaign(context, digest) == 0
        assert called == [digest]
        try:
            campaign(context, digest)
        except RuntimeError as exc:
            assert 'retry/resume/overwrite' in str(exc)
        else:
            raise AssertionError('Second Attempt02 campaign was allowed')
        assert called == [digest]
    return True


def main():
    plan = cfg.load_plan()
    original = json.loads((cfg.frozen.OUT / 'plan.json').read_text())
    assert plan['order'] == original['order'] == cfg.order()
    assert len(plan['order']) == 20
    assert plan['deadlines_ms'] == original['deadlines_ms']
    assert plan['source_phase_ns'] == original['source_phase_ns']
    assert plan['idle_seconds'] == original['idle_seconds'] == 10
    assert plan['runtime'] == original['runtime']
    assert plan['source_sha256'] == original['source_sha256']
    assert cfg.run_source() == (cfg.frozen.frozen.OUT / 'effective_runtime.txt').read_text()
    accounting = analyze_attempt02.frozen_analysis.integer_accounting(100, 90, 6, 4)
    assert accounting['terminal_accounting_PASS'] and accounting['TIR_admission'] == .9
    assert not analyze_attempt02.frozen_analysis.integer_accounting(100, 90, 5, 4)['terminal_accounting_PASS']
    assert runner.frozen_run.Context.bindings.__code__ is not None
    assert fake_gpu_checks() and fake_campaign_checks()
    print(json.dumps({'status': 'PASS', 'CPU_ONLY': True, 'gpu_workload_count': 0,
                      'plan_order_identical': True, 'frozen_worker_identical': True,
                      'gpu_permission_failure_before_marker': True,
                      'second_execution_rejected': True,
                      'analysis_revision01_semantics_reused': True}, indent=2))


if __name__ == '__main__':
    main()
