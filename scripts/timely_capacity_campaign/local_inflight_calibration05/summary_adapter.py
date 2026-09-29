"""Calibration-only C-dependent summary validation; no runtime hot-path changes."""
import types

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
exec(compile(summary_source(), '<calibration05-C-dependent-summary>', 'exec'), _namespace)
_map_proxy = types.SimpleNamespace(**dict(prior.campaign.old.__dict__,
                                          _summarize=_namespace['summarize']))
_campaign_fn = types.FunctionType(prior.campaign.summarize.__code__,
    dict(prior.campaign.summarize.__globals__, old=_map_proxy))
_campaign_proxy = types.SimpleNamespace(**dict(prior.campaign.__dict__,
                                               summarize=_campaign_fn))
_v2_fn = types.FunctionType(prior.v2.summarize.__code__,
    dict(prior.v2.summarize.__globals__, old=_campaign_proxy))
_v2_proxy = types.SimpleNamespace(**dict(prior.v2.__dict__, summarize=_v2_fn))
_v21_fn = types.FunctionType(prior.frozen.summarize.__code__,
    dict(prior.frozen.summarize.__globals__, v2=_v2_proxy))


def summarize(manifest, frames, power):
    """Identical B1 wrapper; C-dependent cardinalities come from manifest C."""
    summary = _v21_fn(manifest, frames, power)
    if manifest.get('pruning_enabled') is False and summary.get('expired_dropped_frames', 0):
        summary.setdefault('errors', []).append('OFF control expired work')
        summary.update(integrity_status='INVALID', validity='INVALID',
                       pipeline_audit_status='FAIL')
    return summary
