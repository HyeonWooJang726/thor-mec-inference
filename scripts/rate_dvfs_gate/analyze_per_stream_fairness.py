#!/usr/bin/env python3
"""A1: CPU-only raw replay of the 45 amended Rate-DVFS runs.

Never imports the GPU runner or writes an input artifact. The final assessment
is a descriptive reading of this campaign's reported traces, not a fairness
threshold classifier or a statistical-significance test.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess

import numpy as np
from analyze_rate_dvfs_gate import read_csv, summarize

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT/'results/rate_dvfs_gate'
DEFAULT_OUTPUT = ROOT/'results/per_stream_fairness_analysis'
IDS = [f'RDVG_B_20260919_P{i:02}' for i in range(1,37)]+[f'RDVG_B_20260919_S{i:02}' for i in range(1,10)]
REQUIRED = ['stream_id','frame_id','phase','admitted','logical_arrival_ns',
            'admission_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns']
KEYS = ['K','C','freq_state','requested_freq_MHz','admission_fps_per_stream']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packed(value):
    return json.dumps(value, separators=(',',':'), sort_keys=True)


def write_table(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def key(row):
    return tuple(row[k] for k in KEYS)


def longest_interval(mask, boundaries):
    switches = np.diff(np.r_[False,mask,False].astype(int))
    starts, ends = np.flatnonzero(switches==1), np.flatnonzero(switches==-1)
    if not len(starts):
        return 0., None, None
    lengths = boundaries[ends]-boundaries[starts]
    i = int(np.argmax(lengths))
    return float(lengths[i])/1e9, float(boundaries[starts[i]])/1e9, float(boundaries[ends[i]])/1e9


def temporal(completions, duration_ns):
    """Exact post-event states, grouping equal timestamps before comparing IDs."""
    k = len(completions)
    times = np.unique(np.concatenate(([0],*completions)))
    counts = np.array([np.searchsorted(c,times,side='right') for c in completions])
    bounds = np.r_[times,duration_ns]
    durations = np.diff(bounds)
    gaps = np.ptp(counts,axis=0)
    peak = int(gaps.max())
    peak_index = int(np.flatnonzero(gaps==peak)[0])
    peak_pairs = set()
    for j in np.flatnonzero(gaps==peak):
        low, high = np.flatnonzero(counts[:,j]==counts[:,j].min()), np.flatnonzero(counts[:,j]==counts[:,j].max())
        peak_pairs.update((int(a),int(b)) for a in high for b in low if a!=b)
    seconds = np.arange(duration_ns//10**9+1,dtype=np.int64)*10**9
    # C_k(t) snapshots count [t0,t0+t); the final snapshot is exactly primary R*T.
    curves = np.array([np.searchsorted(c,seconds,side='left') for c in completions])
    windows = np.diff(curves,axis=1)
    stream_info=[]
    for stream in range(k):
        below = k*counts[stream]<counts.sum(axis=0)  # integer comparison, including ties
        longest, start, end = longest_interval(below,bounds)
        stream_info.append(dict(
            cumulative_completed_at_seconds_json=packed(curves[stream].tolist()),
            completed_per_1s_json=packed(windows[stream].tolist()),
            min_completed_in_1s=int(windows[stream].min()),
            max_completed_in_1s=int(windows[stream].max()),
            zero_completion_1s_windows=int(np.sum(windows[stream]==0)),
            cumulative_below_mean_time_s=float(durations[below].sum())/1e9,
            longest_cumulative_below_mean_s=longest,
            longest_cumulative_below_mean_start_s=start,
            longest_cumulative_below_mean_end_s=end,
            max_lag_behind_leader_frames=int((counts.max(axis=0)-counts[stream]).max())))
    gap_duration, _, _ = longest_interval(gaps>1,bounds)
    return stream_info, dict(
        end_cumulative_gap_frames=int(gaps[-1]),
        max_pairwise_cumulative_gap_frames=peak,
        first_max_gap_time_s=float(times[peak_index])/1e9,
        max_gap_leader_laggard_pairs_json=packed(sorted(peak_pairs)),
        minimum_gap_after_first_peak_frames=int(gaps[peak_index:].min()),
        time_with_gap_gt_one_frame_s=float(durations[gaps>1].sum())/1e9,
        longest_gap_gt_one_frame_s=gap_duration,
        last_all_equal_time_s=float(times[gaps==0][-1])/1e9 if np.any(gaps==0) else None,
        cumulative_gap_at_seconds_json=packed(np.ptp(curves,axis=0).tolist()),
        min_completed_in_any_1s=int(windows.min()),
        zero_completion_stream_1s_windows=int(np.sum(windows==0)))


def inventory(before):
    rows=[]
    directories=sorted(d for d in INPUT.glob('RDVG_*') if d.is_dir())
    for d in directories:
        hashes={p.name:before[str(p.relative_to(ROOT))] for p in d.iterdir() if p.is_file()}
        row=dict(run_id=d.name,primary_included=d.name in IDS,
                 category='AMENDED_PRIMARY' if d.name in IDS and '_P' in d.name else 'AMENDED_SANITY' if d.name in IDS else 'EXCLUDED_SMOKE' if 'SMOKE' in d.name else 'EXCLUDED_RECOVERY' if 'RECOVERY' in d.name else 'EXCLUDED_HISTORICAL',
                 artifact_sha256_before_json=packed(hashes),artifact_sha256_after_json='',preserved=None)
        loaded={}
        for name in ('manifest.json','per_frame.csv.gz','summary.json'):
            row[name+'_exists']=(d/name).is_file()
            try:
                if name.endswith('.json'):
                    loaded[name]=json.loads((d/name).read_text())
                    row[name+'_keys_json']=packed(sorted(loaded[name]))
                else:
                    with gzip.open(d/name,'rt',newline='') as source:
                        reader=csv.DictReader(source)
                        fields=reader.fieldnames or []
                        phases={r['phase'] for r in reader}
                    row['per_frame_schema_json']=packed(fields)
                    row['phases_json']=packed(sorted(phases))
                    row['missing_required_fields_json']=packed(sorted(set(REQUIRED)-set(fields)))
                row[name+'_readability']='OK'
            except Exception as error:
                row[name+'_readability']=repr(error)
        m,s=loaded.get('manifest.json',{}),loaded.get('summary.json',{})
        row.update(protocol_version=m.get('protocol_version',1),protocol_amendment=m.get('protocol_amendment',''),
                   stored_integrity_status=s.get('integrity_status',s.get('validity','UNAVAILABLE')),
                   stored_status_finalized=s.get('status_finalized',False),
                   stored_child_returncode=m.get('child_returncode'),
                   kind=m.get('kind'),plan_sha256=m.get('plan_sha256'),
                   provenance='manifest/raw/summary inspected; excluded histories are not reinterpreted or pooled' if d.name not in IDS else 'raw replay required before inclusion',
                   exclusion_reason='' if d.name in IDS else 'SMOKE_NOT_PRIMARY' if 'SMOKE' in d.name else 'OLD_PROTOCOL_ABORT_ON_SOURCE_LAG' if d.name=='RDVG_V2_20260919_P02' else 'PROTOCOL_V1_ABORT_ON_OC3' if d.name=='RDVG_20260919_P01' else 'PRE_AMENDED_PRIMARY_PROTOCOL')
        rows.append(row)
    return rows


def replay_run(run_id, condition, plan_hash, mismatches):
    d=INPUT/run_id
    m,s=json.loads((d/'manifest.json').read_text()),json.loads((d/'summary.json').read_text())
    frames=read_csv(d/'per_frame.csv.gz')
    def check(field, stored, replay):
        equal=math.isclose(stored,replay,rel_tol=1e-12,abs_tol=1e-12) if isinstance(stored,float) and isinstance(replay,(float,int)) else stored==replay
        if not equal:mismatches.append(dict(run_id=run_id,field=field,stored=stored,replay=replay))
    for field in ('K','C','repeat','kind'):
        check('manifest.'+field,m.get(field),condition[field])
    check('manifest.admission_fps_per_stream',m['admission_fps_per_stream'],condition['r'])
    check('manifest.freq_state',m['freq_state'],condition['frequency'])
    check('manifest.plan_sha256',m['plan_sha256'],plan_hash)
    check('manifest.child_returncode',m.get('child_returncode'),0)
    check('manifest.status_finalized',m.get('status_finalized'),True)
    check('summary.integrity_status',s['integrity_status'],'VALID')
    check('summary.status_finalized',s.get('status_finalized'),True)
    t0,t1=m['active_start_ns'],m['active_end_ns']
    duration_ns=t1-t0;duration=duration_ns/1e9;k=m['K']
    check('measurement_seconds',s['measurement_seconds'],duration)
    check('manifest.measurement_seconds',duration,condition['seconds'])
    active=[r for r in frames if r['phase']=='active']
    source=[r for r in active if t0<=int(r['logical_arrival_ns'])<t1]
    admitted=[r for r in source if int(r['admitted']) and t0<=int(r['admission_timestamp_ns'])<t1]
    finished=[r for r in admitted if r['completion_timestamp_ns'] and t0<=int(r['completion_timestamp_ns'])<t1]
    for name,value in [('source_frames',len(source)),('admitted_frames',len(admitted)),('completed_active_frames',len(finished))]:check(name,s[name],value)
    check('all active-cohort source arrivals inside interval',len(active),len(source))
    check('stream IDs',sorted({int(r['stream_id']) for r in source}),list(range(k)))
    completions=[np.array(sorted(int(r['completion_timestamp_ns'])-t0 for r in finished if int(r['stream_id'])==i),dtype=np.int64) for i in range(k)]
    counts=[len(c) for c in completions];total=sum(counts)
    temporal_stream,temporal_run=temporal(completions,duration_ns)
    common={field:m[field] for field in KEYS}
    common.update(run_id=run_id,repeat=m['repeat'],kind=m['kind'],measurement_seconds=duration,
                  stability='STABLE' if s['queue_stable'] else 'UNSTABLE',supply_status=s['supply_status'],hardware_status=s['hardware_status'])
    per_stream=[]
    for i in range(k):
        ns=sum(int(r['stream_id'])==i for r in source)
        na=sum(int(r['stream_id'])==i for r in admitted)
        rate=counts[i]/duration;lam=ns/duration
        values=dict(stream_id=i,source_frames=ns,admitted_frames=na,completed_active=counts[i],R_k=rate,eta_k=rate/lam)
        stored=next(p for p in s['per_stream'] if p['stream_id']==i)
        for field,value in values.items():check(f'per_stream[{i}].{field}',stored.get(field),value)
        check(f'per_stream[{i}].eta_source_vs_requested',rate/lam,rate/30)
        row=dict(common,**values,lambda_k=lam,r_k=na/duration,active_admitted_service_ratio=counts[i]/na,
                 centered_service_fps=(k*counts[i]-total)/(k*duration),
                 source_video_path=m['inputs'][i]['path'],**temporal_stream[i])
        per_stream.append(row)
    rates=[c/duration for c in counts]
    check('min_per_stream_completed_fps',s['min_per_stream_completed_fps'],min(rates))
    check('mean_per_stream_completed_fps',s['mean_per_stream_completed_fps'],statistics.mean(rates))
    check('aggregate_completed_fps',s['aggregate_completed_fps'],sum(counts)/duration)
    # Full frozen-analyzer replay also rechecks IDs, timestamps, admission,
    # drain, B, trace integrity and classification, without writing summaries.
    replay=summarize(m,frames,read_csv(d/'power_trace.csv.gz'))
    for field,value in replay.items():check('frozen_replay.'+field,s.get(field),value)
    worst=[i for i,c in enumerate(counts) if c==min(counts)]
    best=[i for i,c in enumerate(counts) if c==max(counts)]
    eta=[row['eta_k'] for row in per_stream]
    fair=dict(common,source_frames=len(source),admitted_frames=len(admitted),completed_active_frames=total,
              min_stream_fps=min(rates),max_stream_fps=max(rates),mean_stream_fps=total/(k*duration),
              fps_spread=(max(counts)-min(counts))/duration,eta_spread=max(eta)-min(eta),
              min_mean_service_ratio=k*min(counts)/total,min_max_service_ratio=min(counts)/max(counts),
              jain_index=total**2/(k*sum(c*c for c in counts)),
              worst_stream_ids_json=packed(worst),best_stream_ids_json=packed(best),all_streams_tied=len(worst)==k,
              g_B=s['g_B'],replay_status='PASS' if not any(x['run_id']==run_id for x in mismatches) else 'MISMATCH',**temporal_run)
    return per_stream,fair


def aggregate(streams,runs):
    cells=[]
    for condition in sorted({key(r) for r in runs}):
        rs=sorted([r for r in runs if key(r)==condition],key=lambda r:r['repeat'])
        k=condition[0]
        row=dict(zip(KEYS,condition),repetitions=len(rs),run_ids_json=packed([r['run_id'] for r in rs]),
                 stability=rs[0]['stability'] if len({r['stability'] for r in rs})==1 else 'MIXED',
                 frontend_limited_runs=sum(r['supply_status']=='FRONTEND_LIMITED' for r in rs))
        for field in ('min_stream_fps','fps_spread','min_mean_service_ratio','end_cumulative_gap_frames'):
            row[field+'_mean']=statistics.mean(r[field] for r in rs)
            row[field+'_sd']=statistics.stdev(r[field] for r in rs) if len(rs)>1 else None
        row['mean_jain_index']=statistics.mean(r['jain_index'] for r in rs)
        row['fps_spread_each_repeat_json']=packed([r['fps_spread'] for r in rs])
        row['max_pairwise_cumulative_gap_frames']=max(r['max_pairwise_cumulative_gap_frames'] for r in rs)
        row['worst_ids_each_repeat_json']=packed([json.loads(r['worst_stream_ids_json']) for r in rs])
        row['worst_id_occurrence_including_ties_json']=packed({i:sum(i in json.loads(r['worst_stream_ids_json']) for r in rs) for i in range(k)})
        row['worst_id_occurrence_excluding_all_equal_runs_json']=packed({i:sum(not r['all_streams_tied'] and i in json.loads(r['worst_stream_ids_json']) for r in rs) for i in range(k)})
        centered={};negative={}
        for i in range(k):
            ss=sorted([s for s in streams if key(s)==condition and s['stream_id']==i],key=lambda s:s['repeat'])
            values=[s['centered_service_fps'] for s in ss]
            negative[i]=sum(v<0 for v in values)
            centered[i]=dict(mean=statistics.mean(values),sd=statistics.stdev(values),by_repeat=values,
                             below_cumulative_mean_seconds=[s['cumulative_below_mean_time_s'] for s in ss],
                             longest_below_cumulative_mean_seconds=[s['longest_cumulative_below_mean_s'] for s in ss])
        row['stream_centered_service_json']=packed(centered)
        row['negative_centered_repetitions_by_stream_json']=packed(negative)
        cells.append(row)
    return cells


def report(streams,runs,cells,inv,preservation,shared_hashes):
    largest=max(runs,key=lambda r:r['fps_spread'])
    stable=[r for r in runs if r['stability']=='STABLE']
    normal=[r for r in runs if r['supply_status']=='NORMAL']
    lines=['# A1 — Existing Rate-DVFS Per-Stream Fairness Analysis','',
           '**Verdict: PERSISTENT_IMBALANCE_OBSERVED — localized to some historical K7/C4 frontend-limited conditions; not universal ID starvation.**','',
           '## Data scope and integrity','',
           f'Inventory: {len(inv)} run directories; primary statistics use exactly {len(runs)} amended runs (P01–P36 and S01–S09). Other {len(inv)-len(runs)} smoke/recovery/historical directories are inventoried only. No historical pooling. C remains its measured value (K7/C4, K6/C2); the completed C robustness Gate supports future offline C2 but does not rewrite these runs.',
           '', 'All 57 manifest/raw/summary sets exist and are readable. All required per-frame fields are present in the 45 amended runs. Three excluded V1 runs (RDVG_20260919_P01, RDVG_20260919_SMOKE01 and RDVG_20260919_SMOKE02) lack admission_timestamp_ns; this historical schema difference is preserved in the inventory and is not filled or pooled. Independent raw source/admission/completion counts, per-stream R_k/eta_k and min/mean rates match stored summaries for all 45 runs. The full unchanged frozen analyzer also replays every derived summary field, including source identity, timestamps, admission, drain, B and telemetry integrity. Zero mismatches; floating comparison tolerance 1e-12 only handles serialization/arithmetic, not fairness.',
           '',f'Input preservation: {preservation} existing result/source files SHA-256 checked before and after, unchanged. Per-run before/after hashes of all five artifacts are in input_inventory.csv. Shared provenance hashes: `{packed(shared_hashes)}`.',
           '', '## Definitions and limitations','',
           'Active interval is exactly [active_start_ns, active_end_ns), 60 s. Raw phase=active marks the source cohort; a completion in drain is excluded even if its row has phase=active. Source/admission use logical timestamps, independent of decode progress. lambda_k=source_count/T; r_k=admitted_count/T; R_k=active_completion_count/T; eta_k=R_k/lambda_k. All lambda_k=30, so eta_k matches R_k/30. active_admitted_service_ratio=completed_active/admitted_active is a distinct denominator and is not eta_k.',
           '', 'Run fairness uses integer completion counts to preserve all ties and avoid floating-point tie breaking. Spread=(max_count-min_count)/60; one-frame granularity is 1/60=0.0166667 FPS. Jain is secondary and may remain close to 1 even when a multi-frame gap persists. Condition SD is sample SD (n−1, three repeats). Worst occurrence counts credit every tied ID; all-equal runs are explicitly identified and an additional count excludes those uninformative all-ID ties.',
           '', 'Temporal gap=max_k C_k(t)−min_k C_k(t), using exact completion events, grouped at equal timestamps. Per-stream cumulative curves at seconds 0..60 and 1-s window counts are embedded in per_run_stream_metrics.csv. Exact event-time peaks and durations are separate from these snapshots. Below-mean time uses K*C_k(t)<sum C_j(t); no unfairness threshold. “Gap >1 frame” is a duration diagnostic relative to measurement granularity, never an automatic PASS/FAIL rule. No regression, statistical significance test or fairness scheduler is introduced.',
           '', 'Homogeneous here means the same FPS/admission/model/resolution/protocol, not identical video contents: IDs 0..6 are fixed to different camera videos. Repetition of an ID association cannot separate scheduler-ID bias from camera/decode/preprocess cost. The results are Local system service disparities, not causal proof of GPU-worker discrimination.',
           '', '## Stable and overloaded condition results','',
           '| K/C | MHz | r | state | min FPS mean ± SD | spread FPS mean ± SD | min/mean mean ± SD | mean Jain | end gap mean ± SD (frames) | exact peak gap (frames) | worst IDs by repeat | FE runs |',
           '|---|---:|---:|---|---|---|---|---:|---|---:|---|---:|']
    for c in cells:
        lines.append(f"| {c['K']}/{c['C']} | {c['requested_freq_MHz']} | {c['admission_fps_per_stream']} | {c['stability']} | {c['min_stream_fps_mean']:.6f} ± {c['min_stream_fps_sd']:.6f} | {c['fps_spread_mean']:.6f} ± {c['fps_spread_sd']:.6f} | {c['min_mean_service_ratio_mean']:.8f} ± {c['min_mean_service_ratio_sd']:.8f} | {c['mean_jain_index']:.8f} | {c['end_cumulative_gap_frames_mean']:.3f} ± {c['end_cumulative_gap_frames_sd']:.3f} | {c['max_pairwise_cumulative_gap_frames']} | {c['worst_ids_each_repeat_json']} | {c['frontend_limited_runs']}/3 |")
    lines += ['',f"Largest end-window spread: {largest['run_id']}, K={largest['K']}/C={largest['C']}, {largest['requested_freq_MHz']} MHz/r={largest['admission_fps_per_stream']}: {largest['fps_spread']:.6f} FPS, {largest['end_cumulative_gap_frames']} end-gap frames; exact temporal maximum {largest['max_pairwise_cumulative_gap_frames']} frames. min/mean={largest['min_mean_service_ratio']:.8f}, min/max={largest['min_max_service_ratio']:.8f}, Jain={largest['jain_index']:.8f}.",
              '',f"All {len(stable)} stable runs have end gaps at most {max(r['end_cumulative_gap_frames'] for r in stable)} frame and spread at most {max(r['fps_spread'] for r in stable):.6f} FPS. Their exact transient peak gaps range {min(r['max_pairwise_cumulative_gap_frames'] for r in stable)}–{max(r['max_pairwise_cumulative_gap_frames'] for r in stable)} frames and recover to 0–1 at the endpoint. All {len(normal)} frontend-NORMAL runs, including K6/LOW overload and K7/MID/r30 P23, also end within {max(r['end_cumulative_gap_frames'] for r in normal)} frame. Reduced absolute FPS under overload is therefore not itself unfairness.",
              '', '## Repeated ID associations and temporal evidence','',
              'The following are explicit descriptive witnesses; their magnitudes and durations are shown instead of applying a new fairness cutoff. Stream 6 at LOW/r24 has negative centered whole-run service in all three repeats; its worst-ID sets are not identical across all repeats. Stream 5 at LOW/r27 is below the run mean in all three repeats although another ID is often the worst. Neither is globally the worst ID across the campaign.',
              '', '| condition / ID | run | R_k−mean FPS | time below cumulative mean (s) | longest uninterrupted below-mean interval (s) | centered cumulative frames at 10/20/30/40/50/60s | pairwise gap at 10/20/30/40/50/60s |',
              '|---|---|---:|---:|---|---|---|']
    for admission,stream in ((24,6),(27,5)):
        witness=sorted([s for s in streams if s['K']==7 and s['requested_freq_MHz']==945 and s['admission_fps_per_stream']==admission and s['stream_id']==stream],key=lambda s:s['repeat'])
        if len(witness)!=3 or not all(s['centered_service_fps']<0 for s in witness):
            raise RuntimeError('descriptive witness changed; review verdict before reuse')
        for s in witness:
            peers=[p for p in streams if p['run_id']==s['run_id']]
            curves=np.array([json.loads(p['cumulative_completed_at_seconds_json']) for p in peers])
            centered=(7*np.array(json.loads(s['cumulative_completed_at_seconds_json']))-curves.sum(axis=0))/7
            f=next(r for r in runs if r['run_id']==s['run_id'])
            gaps=json.loads(f['cumulative_gap_at_seconds_json'])[10::10]
            bounds=f"{s['longest_cumulative_below_mean_s']:.3f} [{s['longest_cumulative_below_mean_start_s']:.3f}, {s['longest_cumulative_below_mean_end_s']:.3f}]"
            lines.append(f"| LOW/r{admission}, ID{s['stream_id']} | {s['run_id']} | {s['centered_service_fps']:+.6f} | {s['cumulative_below_mean_time_s']:.3f} | {bounds} | {packed(np.round(centered[10::10],3).tolist())} | {packed(gaps)} |")
    lines += ['', 'P13 and P36 show stream 6 progressively falling behind for most of the active interval. P02 is a counterexample to an always-growing ID6 lag: it temporarily recovers above the mean before finishing below it; stream 4 is its worst ID. LOW/r27 P22 develops a large persistent gap with ID2 worst, while ID5 also remains below the mean. P11 has a smaller gap that partially recovers. These contrasts support localized repeated imbalance, not a single permanently starved stream or monotonic growth at every completion event.',
              '', 'Worst IDs rotate: LOW/r24 has [4], [6], [6]; LOW/r27 [4,5], [2], [6]; LOW/r30 [5], [5,6], [1]. MID/r30 has [5], all IDs tied, [4]. Endpoint-only recurrence also occurs in essentially equal service: K6 LOW includes ID1 in the worst tie set in all three repeats, but all three spreads are exactly one frame and cumulative gap does not drift. Thus ID occurrence alone cannot establish material bias.',
              '',f"No stream has a zero-completion 1-s window: observed minimum is {min(r['min_completed_in_any_1s'] for r in runs)} completions/s across these nonoverlapping windows. This describes the inspected nonoverlapping windows only; it does not rule out differently aligned pauses, subsecond stalls or future starvation. All admitted frames eventually drain. The finding is relative service imbalance, not complete starvation.",
              '', '## Verdict and research implication','',
              'PERSISTENT_IMBALANCE_OBSERVED is a descriptive verdict based on repeated negative deviations and sustained multi-frame cumulative gaps in the cited frontend-limited K7/C4 traces. It is not a universal stream-ID bias or a statistical significance claim. Stable conditions and the K6/C2 overload case show near-equal service despite lower aggregate throughput in overload.',
              '', 'The raw data justify retaining per-stream service measurement and an imbalance diagnostic. They do not justify keeping a Min-Max/service-deficit scheduler as a core contribution on this evidence alone: the substantial gaps coincide with frontend-limited historical C4 operation, IDs remain confounded with camera input, and future common C2 at K7 is outside this A1 sample. A GPU-ready scheduling mechanism has not been shown to remove a deficit originating before readiness. Reduce the mechanism to a secondary hypothesis; no controller, deficit state, scheduling policy, C experiment or new GPU run is implemented. The existing rate-DVFS and C-robustness verdicts remain unchanged.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='rate-dvfs-gate':
        raise RuntimeError('wrong branch; no checkout attempted')
    output=args.output.resolve()
    if output.exists():
        raise RuntimeError('output already exists; refusing to overwrite: '+str(output))
    output.mkdir(parents=True)
    protected=[]
    for root in ('scripts/rate_dvfs_gate','results/rate_dvfs_gate','scripts/c_robustness_gate','results/c_robustness_gate'):
        protected.extend(p for p in (ROOT/root).rglob('*') if p.is_file() and p.resolve()!=Path(__file__).resolve())
    before={str(p.relative_to(ROOT)):digest(p) for p in protected}
    inv=inventory(before)
    write_table(output/'input_inventory.csv',inv)  # persist before-analysis hashes
    mismatches=[];streams=[];runs=[]
    plan_path=INPUT/'EXPERIMENT_PLAN_V2.md'
    plan=json.loads(plan_path.read_text().split('## Protocol Amendment — Unified Backlog B(t)\n',1)[1].split('```json\n',1)[1].split('\n```',1)[0])
    try:
        if len(inv)!=57 or set(IDS)!={r['run_id'] for r in inv if r['primary_included']} or set(IDS)!={c['run_id'] for c in plan['order']}:
            raise RuntimeError('input campaign inventory differs from requested scope')
        for run_id in IDS:
            condition=next(c for c in plan['order'] if c['run_id']==run_id)
            try:
                ss,rr=replay_run(run_id,condition,digest(plan_path),mismatches)
                streams.extend(ss);runs.append(rr)
            except Exception as error:
                mismatches.append(dict(run_id=run_id,field='raw replay exception',stored=None,replay=repr(error)))
    finally:
        changed=[str(p.relative_to(ROOT)) for p in protected if not p.exists() or digest(p)!=before[str(p.relative_to(ROOT))]]
        for row in inv:
            old=json.loads(row['artifact_sha256_before_json'])
            new={name:digest(INPUT/row['run_id']/name) if (INPUT/row['run_id']/name).exists() else None for name in old}
            row.update(artifact_sha256_after_json=packed(new),preserved=old==new)
        write_table(output/'input_inventory.csv',inv)
        if changed:mismatches.append(dict(run_id='ALL',field='artifact SHA256 preservation',stored='unchanged',replay=changed))
    if mismatches:
        (output/'fairness_verdict.md').write_text('# A1 stopped before fairness interpretation\n\nRaw replay mismatch; no correction or fairness conclusion.\n\n```json\n'+json.dumps(mismatches,indent=2)+'\n```\n')
        print(packed({'status':'STOPPED_RAW_REPLAY_MISMATCH','mismatches':mismatches}))
        return 2
    for row in inv:
        row['replay_status']='PASS' if row['primary_included'] else 'EXCLUDED_NOT_REPLAYED'
    write_table(output/'input_inventory.csv',inv)
    cells=aggregate(streams,runs)
    write_table(output/'per_run_stream_metrics.csv',streams)
    write_table(output/'per_run_fairness.csv',runs)
    write_table(output/'condition_fairness.csv',cells)
    shared={name:before[name] for name in ('results/rate_dvfs_gate/EXPERIMENT_PLAN_V2.md','results/rate_dvfs_gate/gate_verdict.md','scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py','results/c_robustness_gate/gate_verdict.md')}
    shared['analysis_script_sha256']=digest(Path(__file__))
    (output/'fairness_verdict.md').write_text(report(streams,runs,cells,inv,len(before),shared))
    print(packed({'primary_runs':len(runs),'excluded_runs':len(inv)-len(runs),'stream_rows':len(streams),'conditions':len(cells),'raw_replay':'PASS','preserved_files':len(before),'verdict':'PERSISTENT_IMBALANCE_OBSERVED'}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
