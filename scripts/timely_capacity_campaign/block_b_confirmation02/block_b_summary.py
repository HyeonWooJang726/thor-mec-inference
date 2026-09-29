"""Block-B-only post-drain summary; frozen V2.2 worker and old analyses untouched."""
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
for relative in ('common/service_phase_b1', 'common/service_phase_b0',
                 'common', 'block_b_split/v2_1', 'block_b_split/v2'):
    sys.path.insert(0, str(HERE.parent / relative))
import b1_summary as b1
from grid_config import PLAN, OUT, decorate, sha

read_csv = b1.read_csv


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Frozen summary anchor changed: ' + old)
    return text.replace(old, new, 1)


def parameterized_source():
    """Patch only fixed Local-only reporting constants in a private summary copy."""
    text = b1.summary_source()
    replacements = (
        ("if duration!=60:raise ValueError('Active duration is not60s')",
         "if duration!=expected_seconds:raise ValueError('Block B active duration mismatch')"),
        ('len(source)==14400 and len(rows)==target*60',
         'len(source)==expected_seconds*240 and len(rows)==expected_seconds*240'),
        ('range(1800)', 'range(expected_seconds*30)'),
        ("m['local_r']*8*60", "m['local_r']*8*expected_seconds"),
        ("m['edge_r']*8*60", "m['edge_r']*8*expected_seconds"),
        ('s.update(counts(rows,14400))', 's.update(counts(rows,expected_seconds*240))'),
        ("counts([r for r in rows if int(r['stream_id'])==k],1800)",
         "counts([r for r in rows if int(r['stream_id'])==k],expected_seconds*30)"),
        ("s['paths']={name:counts(rr,14400)",
         "s['paths']={name:counts(rr,expected_seconds*240)"),
    )
    for old, new in replacements:
        text = replace_one(text, old, new)
    return text


def summarize(m, frames, power):
    plan = json.loads(PLAN.read_text())
    digest = sha(PLAN)
    if digest != (OUT / 'plan.sha256').read_text().strip() or \
            m.get('plan_sha256') != digest or m.get('execution_manifest_sha256') != digest:
        raise ValueError('Block B summary plan SHA mismatch')
    matches = [c for c in plan['order'] if c['run_id'] == m.get('run_id')]
    if len(matches) != 1:
        raise ValueError('Run outside Block B plan')
    c = matches[0]
    for key in ('run_id','deadline_ms','target_service_FPS','admission_pattern',
                'edge_r','local_r','K','C','cell','repeat'):
        if m.get(key) != c.get(key):
            raise ValueError('Block B condition/manifest mismatch: ' + key)
    if m.get('batch_size') != 1 or m.get('pruning_enabled') is not True or \
            m.get('placement_schedule') != plan['placement']:
        raise ValueError('Block B runtime/placement manifest mismatch')

    # The inherited summary names target_service_FPS as total admissions. For
    # this split, total admissions are 240 while c.target_service_FPS is Local.
    # Never mutate the real run manifest; use a private post-drain view only.
    view = dict(m, target_service_FPS=240)

    def parameter_decorate(row, start, target, mode, deadline):
        if target != 240 or mode != 'B' or deadline != 100 or \
                start != m['active_start_ns']:
            raise ValueError('Block B summary binding mismatch')
        return decorate(row, start, c)

    ns = dict(b1.ns, decorate=parameter_decorate, expected_seconds=c['seconds'])
    exec(compile(parameterized_source(), '<Block-B-post-drain-summary-only>', 'exec'), ns)
    map_proxy = types.SimpleNamespace(**dict(b1.campaign.old.__dict__, _summarize=ns['summarize']))
    # campaign_analysis.summarize creates its own decorator and otherwise
    # rebinds the private core back to common campaign_config.decorate. That
    # common decorator only permits old STAGGERED rates 22/23/24 and its
    # placement semantics are not Block B's Edge=Local-complement schedule.
    # Replace the configuration binding in this private summary call only.
    def block_b_decorate(row, start, manifest):
        if manifest is not view or start != m['active_start_ns']:
            raise ValueError('Block B summary manifest/start binding mismatch')
        return decorate(row, start, c)
    config_proxy = types.SimpleNamespace(**dict(b1.campaign.cfg.__dict__,
                                                decorate=block_b_decorate))
    campaign_fn = types.FunctionType(b1.campaign.summarize.__code__,
        dict(b1.campaign.summarize.__globals__, old=map_proxy, cfg=config_proxy))
    campaign_proxy = types.SimpleNamespace(**dict(b1.campaign.__dict__, summarize=campaign_fn))
    v2_fn = types.FunctionType(b1.v2.summarize.__code__,
        dict(b1.v2.summarize.__globals__, old=campaign_proxy))
    v2_proxy = types.SimpleNamespace(**dict(b1.v2.__dict__, summarize=v2_fn))
    v21_fn = types.FunctionType(b1.frozen.summarize.__code__,
        dict(b1.frozen.summarize.__globals__, v2=v2_proxy))
    s = v21_fn(view, frames, power)
    active = [r for r in frames if r.get('phase') == 'active']
    assigned = [r for r in active if int(r.get('admitted') or 0)]
    expected = c['seconds'] * 240
    local = [r for r in assigned if r.get('placement') == 'LOCAL']
    edge = [r for r in assigned if r.get('placement') == 'EDGE']
    if len(active) != expected or len(assigned) != expected or \
            len(local) != c['seconds'] * c['target_service_FPS'] or \
            len(edge) != c['seconds'] * (240-c['target_service_FPS']) or \
            s.get('terminal_accounting_status') != 'PASS' or \
            s.get('true_unfinished_after_drain') != 0:
        s.setdefault('errors', []).append('Block B exact source/split/terminal failure')
        s.update(integrity_status='INVALID', validity='INVALID', pipeline_audit_status='FAIL')
    s['target_service_FPS'] = c['target_service_FPS']
    s['total_offered_FPS'] = 240
    s['admission_r'] = 30
    s['configured_admission_FPS_per_stream'] = 30
    s['legacy_admission_field_note'] = 'All K8x30 source frames assigned exactly once; Local target_service_FPS is the split only.'
    return s
