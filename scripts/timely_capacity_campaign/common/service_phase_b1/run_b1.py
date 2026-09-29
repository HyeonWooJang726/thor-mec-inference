"""Future explicit B1 ABBA execution only. `check` is CPU/read-only."""
import argparse
import inspect
import json
import textwrap
from b1_common import HERE, ROOT, OUT, PLAN, sha, load_plan, run_source, runtime_record
import run_b0 as b0

v2, old = b0.v2, b0.old


class Context(b0.Context):
    def __init__(self):
        super().__init__()
        self.OUT, self.PLAN = OUT, PLAN
        self.PREFLIGHT, self.entry = OUT/'frequency_preflight.json', HERE/'run_b1.py'

    def load_plan(self):
        runtime_record()
        return load_plan()

    def bindings(self):
        source = textwrap.dedent(inspect.getsource(v2.Context.bindings))
        source = source.replace("'from analysis_v2 import summarize,read_csv'", "'from b1_summary import summarize,read_csv'")
        source = old.rep(source, 'wifi_capture=wifi_v2.capture)',
                         'wifi_capture=wifi_v2.capture,SnapshotManifest=checkpoint_21.Manifest,runtime_record=runtime_record)')
        ns = dict(v2.__dict__, adapted_source=run_source, checkpoint_21=b0.checkpoint_21, runtime_record=runtime_record)
        exec(compile(source, '<B1-frozen-B0-bindings>', 'exec'), ns)
        return ns['bindings'](self)

    def campaign(self, approval):
        p = self.check_inputs()
        if approval != sha(PLAN):
            raise RuntimeError('B1 execution requires exact plan approval SHA')
        if self.PREFLIGHT.exists() or any((OUT/c['run_id']).exists() for c in p['order']):
            raise RuntimeError('Existing B1 attempt; no retry/resume/overwrite')
        self.frequency_preflight()  # Existing helper; never called by check/CPU tests.
        ns = dict(old.prior.hybrid.__dict__, OUT=OUT, PLAN=PLAN, __file__=str(self.entry),
                  check_inputs=self.check_inputs, load_plan=self.load_plan, bindings=self.bindings,
                  write_json=self.write_json, frequency=old.frequency, validate_finished=validate_finished)
        s = inspect.getsource(old.prior.hybrid.campaign)
        s = old.rep(s, "        d=OUT/c['run_id'];d.mkdir(exist_ok=False)",
                    "        if c['order_index']>1:time.sleep(plan['idle_seconds'])\n        d=OUT/c['run_id'];d.mkdir(exist_ok=False)")
        s = old.rep(s, 'admission_fps_per_stream=30,',
                    "admission_fps_per_stream=25, edge_r=0,local_r=25,cell=c['cell'],target_service_FPS=200,supply_mode='A',deadline_ms=100,block='B1',admission_pattern='ALIGNED',pruning_enabled=c['pruning_enabled'],")
        s = old.rep(s, '        if interrupted or recovery_error or not s.get(\'frequency_restore_ok\'):return 2',
                    "        if interrupted or recovery_error or not s.get('frequency_restore_ok') or s.get('integrity_status')!='VALID':return 2\n        if not validate_finished(d,c):return 2")
        s = old.rep(s, "return 0 if mode=='primary' or smoke_pass(plan) else 1", 'return 0')
        exec(compile(s, '<B1-original-supervisor-ABBA>', 'exec'), ns)
        return ns['campaign']('formal')


def validate_finished(directory, condition):
    # After natural drain/worker join only; instrumentation validity does not
    # change runtime decisions. Stop, preserve and never retry on failure.
    from analyze_b1 import validate_run, read
    d = directory
    report = validate_run(condition, json.loads((d/'manifest.json').read_text()),
        json.loads((d/'summary.json').read_text()), read(d/'per_frame.csv.gz'),
        read(d/'per_frame_phase_timestamps.csv'), json.loads((d/'phase_instrumentation_manifest.json').read_text()))
    with (d/'b1_instrumentation_validation.json').open('x') as f:
        json.dump(report, f, indent=2, allow_nan=False)
    return report['status'] == 'PASS'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['check', 'campaign', 'one'])
    ap.add_argument('--approve-plan-sha256'); ap.add_argument('--run-id')
    a = ap.parse_args(); ctx = Context()
    if a.action == 'check':
        ctx.check_inputs(); print('PASS: B1 CPU/input/binding check; no GPU/network/frequency action'); return 0
    if a.action == 'campaign':
        return ctx.campaign(a.approve_plan_sha256)
    p = ctx.check_inputs(); ctx.require_preflight()
    candidates = [c for c in p['order'] if c['run_id']==a.run_id]
    if len(candidates)!=1:raise RuntimeError('Run outside B1 ABBA plan')
    seed = OUT/a.run_id/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):
        raise RuntimeError('Fresh B1 supervisor seed required')
    return ctx.bindings()[0](candidates[0], a.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
