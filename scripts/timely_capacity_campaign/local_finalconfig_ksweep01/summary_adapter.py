"""Strict K/C-aware summary binding for the frozen full Local path."""
import types
import inspect
from ksweep_schedule import decorate as ksweep_decorate

import config as _config  # Initialize the frozen B1/V2.2 read-only import paths.
import b1_summary as prior

read_csv = prior.read_csv


def summary_source():
    source = prior.summary_source()
    replacements = {
        "check(len(warm)==60 and all(val(r,'completion_timestamp_ns') is not None and val(r,'completion_timestamp_ns')<t0 for r in warm),'warmup')":
            "check(len(warm)==m['C']*m['warmup_inferences_per_worker'] and all(val(r,'completion_timestamp_ns') is not None and val(r,'completion_timestamp_ns')<t0 for r in warm),'warmup')",
        "check(overlap['peak']<=2,'Local C exceeded')":
            "check(overlap['peak']<=m['C'],'Local C exceeded')",
        "check(len(source)==14400 and len(rows)==target*60,'source/admission count')":
            "check(len(source)==m['K']*30*m['measurement_seconds'] and len(rows)==target*m['measurement_seconds'],'source/admission count')",
        "for sid in range(8):": "for sid in range(m['K']):",
        "list(range(1800))": "list(range(30*m['measurement_seconds']))",
        "m['local_r']*8*60": "m['local_r']*m['K']*m['measurement_seconds']",
        "m['edge_r']*8*60": "m['edge_r']*m['K']*m['measurement_seconds']",
        "s.update(counts(rows,14400))": "s.update(counts(rows,m['K']*30*m['measurement_seconds']))",
        "],1800)) for k in range(8)": "],30*m['measurement_seconds'])) for k in range(m['K'])",
        "counts(rr,14400)": "counts(rr,m['K']*30*m['measurement_seconds'])",
        "st.stdev(rates)": "st.stdev(rates) if len(rates)>1 else None",
        "st.stdev(tirs)": "st.stdev(tirs) if len(tirs)>1 else None",
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise RuntimeError('Frozen C-dependent summary anchor changed: ' + old)
        source = source.replace(old, new)
    return source


# Rebind the same B1/D100/V2.1/pruning summary wrapper chain. The only
# predicate changes are the two exact anchors above; the original modules
# remain unchanged for their historical campaigns.
_namespace = dict(prior.ns)
exec(compile(summary_source(), '<ksweep-C-and-K-dependent-summary>', 'exec'), _namespace)
_map_proxy = types.SimpleNamespace(**dict(prior.campaign.old.__dict__,
                                          _summarize=_namespace['summarize']))
_diagnostics_source = inspect.getsource(prior.campaign.diagnostics)
_old_rank = "list(range(1,9))"
if _diagnostics_source.count(_old_rank) != 1:
    raise RuntimeError('Frozen K-rank diagnostics anchor changed')
_diagnostics_namespace = dict(prior.campaign.__dict__)
exec(compile(_diagnostics_source.replace(_old_rank, "list(range(1,m['K']+1))"),
             '<ksweep-K-rank-diagnostics>', 'exec'), _diagnostics_namespace)
_campaign_fn = types.FunctionType(prior.campaign.summarize.__code__,
    dict(prior.campaign.summarize.__globals__, old=_map_proxy,
         cfg=types.SimpleNamespace(decorate=ksweep_decorate),
         diagnostics=_diagnostics_namespace['diagnostics']))
_campaign_proxy = types.SimpleNamespace(**dict(prior.campaign.__dict__,
                                               summarize=_campaign_fn))
_v2_fn = types.FunctionType(prior.v2.summarize.__code__,
    dict(prior.v2.summarize.__globals__, old=_campaign_proxy))
_v2_proxy = types.SimpleNamespace(**dict(prior.v2.__dict__, summarize=_v2_fn))
_v21_fn = types.FunctionType(prior.frozen.summarize.__code__,
    dict(prior.frozen.summarize.__globals__, v2=_v2_proxy))


def summarize(manifest, frames, power):
    """Keep B1 accounting with exact planned K and C cardinalities."""
    summary = _v21_fn(manifest, frames, power)
    active = [r for r in frames if r.get('phase') == 'active']
    expected = set(range(int(manifest['K'])))
    observed = [int(r['stream_id']) for r in active]
    per_stream = summary.get('per_stream', [])
    if (len(per_stream) != len(expected) or
            {int(r['stream_id']) for r in per_stream} != expected or
            len(active) != int(manifest['K'])*30*int(manifest['measurement_seconds']) or
            set(observed) != expected):
        summary.setdefault('errors', []).append('K-specific stream/cardinality mismatch')
        summary.update(integrity_status='INVALID', validity='INVALID',
                       pipeline_audit_status='FAIL')
    if manifest.get('pruning_enabled') is False and summary.get('expired_dropped_frames', 0):
        summary.setdefault('errors', []).append('OFF control expired work')
        summary.update(integrity_status='INVALID', validity='INVALID',
                       pipeline_audit_status='FAIL')
    return summary
