"""Preserve V2.1 replay; allow late starts ONLY in the explicit pruning-OFF control."""
import types
import run_b0  # Proven CPU-safe bootstrap, never calls campaign on import.
import analysis_21 as frozen
import campaign_analysis as campaign
import analysis_v2 as v2

read_csv = frozen.read_csv


def summary_source():
    s = campaign.old.summary_source()
    return run_b0.old.rep(s, "check(stamp is not None and stamp<deadline,'expired waiting work executed')",
        "check(stamp is not None and (not m.get('pruning_enabled',True) or stamp<deadline),'expired waiting work executed')")


# Clone function namespaces rather than mutating any imported module/global.
ns = dict(campaign.old.ns)
exec(compile(summary_source(), '<B1-pruning-aware-OFF-validation>', 'exec'), ns)
map_proxy = types.SimpleNamespace(**dict(campaign.old.__dict__, _summarize=ns['summarize']))
campaign_fn = types.FunctionType(campaign.summarize.__code__, dict(campaign.summarize.__globals__, old=map_proxy))
campaign_proxy = types.SimpleNamespace(**dict(campaign.__dict__, summarize=campaign_fn))
v2_fn = types.FunctionType(v2.summarize.__code__, dict(v2.summarize.__globals__, old=campaign_proxy))
v2_proxy = types.SimpleNamespace(**dict(v2.__dict__, summarize=v2_fn))
v21_fn = types.FunctionType(frozen.summarize.__code__, dict(frozen.summarize.__globals__, v2=v2_proxy))


def summarize(m, frames, power):
    s = v21_fn(m, frames, power)
    if m.get('pruning_enabled') is False and s.get('expired_dropped_frames', 0):
        s.setdefault('errors', []).append('OFF control expired work')
        s.update(integrity_status='INVALID', validity='INVALID', pipeline_audit_status='FAIL')
    return s
