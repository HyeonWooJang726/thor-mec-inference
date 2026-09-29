"""CPU-only fake-child replay of the exact eight-run parent source binding."""
import hashlib
import json
import tempfile
import types
from pathlib import Path

from pilot02_config import order
from run_pilot02 import supervisor_source
import run_validation as original


def main():
    events = []
    runs = order()
    with tempfile.TemporaryDirectory(prefix='block-a-supervisor-') as temporary:
        out = Path(temporary)
        path = out / 'plan.json'
        path.write_text('{}')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        frozen = {'order': runs, 'smoke': [], 'idle_seconds': 10}

        class Context:
            PREFLIGHT = out / 'frequency_preflight.json'
            entry = out / 'entry.py'
            def check_inputs(self):
                return frozen
            def load_plan(self):
                return frozen
            def frequency_preflight(self):
                events.append(('GPU_PREFLIGHT_STUB',))
            def write_json(self, destination, value):
                destination.write_text(json.dumps(value))
            def bindings(self):
                def finalize(directory, information, stdout, stderr):
                    manifest = json.loads((directory / 'manifest.json').read_text())
                    manifest['edge_ready'] = True
                    (directory / 'manifest.json').write_text(json.dumps(manifest))
                    events.append(('cleanup', directory.name))
                    return {'integrity_status': 'VALID', 'frequency_restore_ok': True}
                return None, finalize

        class Process:
            pid = 321
            returncode = 0
            def __init__(self, command, **kwargs):
                run_id = command[-1]
                condition = next(row for row in runs if row['run_id'] == run_id)
                seed = json.loads((out / run_id / 'manifest.json').read_text())
                assert seed['target_service_FPS'] == 208
                assert seed['admission_fps_per_stream'] == 26
                assert seed['admission_pattern'] == condition['admission_pattern']
                assert seed['deadline_ms'] == condition['deadline_ms']
                assert seed['edge_r'] == 0 and seed['pruning_enabled'] is True
                events.append(('fake_child', run_id))
            def communicate(self, **kwargs):
                return '', ''

        hybrid = types.SimpleNamespace(**original.prior.old.prior.hybrid.__dict__)
        hybrid.subprocess = types.SimpleNamespace(Popen=Process, TimeoutExpired=TimeoutError, PIPE=-1)
        hybrid.time = types.SimpleNamespace(monotonic_ns=lambda: 0,
                                            sleep=lambda seconds: events.append(('idle', seconds)))
        old = types.SimpleNamespace(prior=types.SimpleNamespace(hybrid=hybrid),
                                    rep=original.prior.old.rep,
                                    frequency=types.SimpleNamespace(read_range=lambda: {'min_freq': 315000000,
                                                                                          'max_freq': 1575000000}))
        namespace = dict(original.__dict__,
                         prior=types.SimpleNamespace(old=old), OUT=out, PLAN=path,
                         order=lambda: runs, cpu=types.SimpleNamespace(require_pinned=lambda: {'status': 'PASS'}),
                         before_run=lambda condition, directory: events.append(('before', condition['run_id'])),
                         after_run=lambda directory: True,
                         validate_finished=lambda directory, condition: True)
        exec(compile(supervisor_source(), '<block-a-CPU-only-supervisor>', 'exec'), namespace)
        assert namespace['campaign'](Context(), digest) == 0
        assert [event[1] for event in events if event[0] == 'fake_child'] == [row['run_id'] for row in runs]
        assert [event[1] for event in events if event[0] == 'idle'] == [10] * 7
        for index, event in enumerate(events):
            if event[0] == 'idle':
                assert events[index - 1][0] == 'cleanup'
        try:
            namespace['campaign'](Context(), digest)
        except RuntimeError as exc:
            assert 'retry/resume/overwrite' in str(exc)
        else:
            raise AssertionError('Synthetic second campaign was allowed')
    print(json.dumps({'status': 'PASS', 'provenance': 'CPU_ONLY_FAKE_CHILDREN',
                      'real_workloads_executed': 0, 'frozen_run_count': 8,
                      'run_order_exact': True, 'dynamic_ALIGNED_STAGGERED_seed': True,
                      'deadline_seed_exact': True, 'no_Edge': True,
                      'cleanup_before_idle': True, 'retry_rejected': True}, indent=2))


if __name__ == '__main__':
    main()
