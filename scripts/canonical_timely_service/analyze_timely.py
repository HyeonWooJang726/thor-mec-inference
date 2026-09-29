#!/usr/bin/env python3
"""Canonical raw backlog replay plus source-due deadline cohort, never a timely-good gate."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import traceback
import types
from timely_common import ROOT, OUT, PLAN, DEADLINES, load_plan, decorate, sha, proven_analysis as existing

read_csv, flatten, write_csv, finite = existing.read_csv, existing.flatten, existing.write_csv, existing.finite
_ns = dict(existing.original.h.__dict__, decorate=decorate)
exec(compile(existing.adapted_summary_source(), '<timely-existing-backlog-replay>', 'exec'), _ns)
_fn = existing.summarize
_summary = types.FunctionType(_fn.__code__, dict(_fn.__globals__, _replay=_ns['summarize']))


def due_cohort(manifest, frames):
    t0, t1 = manifest['active_start_ns'], manifest['active_end_ns']
    result, seen = [], set()
    for r in frames:
        if r['phase'] != 'active' or int(r.get('admitted') or 0) != 1:
            continue
        sid, fid = int(r['stream_id']), int(r['frame_id'])
        a = int(r['logical_arrival_ns'])
        if (sid,fid) in seen or sid not in range(8):
            raise ValueError('Duplicate/invalid admitted stream/frame identity')
        seen.add((sid,fid))
        if not (t0 <= a < t1 and a == t0+fid*10**9//30 and int(r['admission_timestamp_ns']) == a):
            raise ValueError('Arrival/cohort/source phase mismatch')
        end = int(r['completion_timestamp_ns']) if r.get('completion_timestamp_ns') not in ('',None) else None
        if end is not None and end < a:
            raise ValueError('Negative source-due E2E')
        path = r['placement']
        if path not in ('LOCAL','EDGE'):
            raise ValueError('Admitted frame without execution path')
        if path == 'EDGE':
            response = int(r['response_completion_ns']) if r.get('response_completion_ns') not in ('',None) else None
            if end != response:
                raise ValueError('Thor returned/completion timestamp disagreement')
        result.append(dict(stream_id=sid, frame_id=fid, arrival=a, completion=end, path=path))
    return result


def deadline_metrics(cohort, duration, d, energy):
    completed = [r for r in cohort if r['completion'] is not None]
    ontime = sum(r['completion']-r['arrival'] <= d*1_000_000 for r in completed)
    return dict(deadline_ms=d, admitted_frames=len(cohort), completed_frames=len(completed),
        on_time_frames=ontime, late_frames=len(completed)-ontime,
        missing_frames=len(cohort)-len(completed), admitted_FPS=len(cohort)/duration,
        timely_FPS=ontime/duration, late_FPS=(len(completed)-ontime)/duration,
        TIR=ontime/len(cohort) if cohort else None,
        VIN_J_per_timely_frame=energy/ontime if energy is not None and ontime else None,
        VIN_timely_energy_status='AVAILABLE' if energy is not None and ontime else
            'ZERO_TIMELY_FRAMES' if not ontime else 'VIN_UNAVAILABLE')


def timely_rows(manifest, frames, summary):
    cohort = due_cohort(manifest, frames)
    duration = (manifest['active_end_ns']-manifest['active_start_ns'])/1e9
    t0,t1 = manifest['active_start_ns'],manifest['active_end_ns']
    energy = summary.get('E_device_J')
    runs, streams, paths = [], [], []
    for d in DEADLINES:
        row = deadline_metrics(cohort,duration,d,energy)
        stream = []
        for k in range(8):
            sk = dict(stream_id=k, **deadline_metrics([r for r in cohort if r['stream_id']==k],duration,d,None))
            # No per-stream or per-path attribution of whole-device VIN energy.
            sk.pop('VIN_J_per_timely_frame'); sk.pop('VIN_timely_energy_status')
            stream.append(sk)
        tir = [r['TIR'] for r in stream]
        row.update(raw_completed_FPS=sum(r['completion'] is not None and t0<=r['completion']<t1 for r in cohort)/duration,
            mean_stream_TIR=statistics.mean(tir), worst_stream_TIR=min(tir),
            maximum_stream_TIR=max(tir), stream_TIR_sample_SD=statistics.stdev(tir))
        runs.append(row); streams.extend(stream)
        for p in ('LOCAL','EDGE'):
            pr = dict(path=p, **deadline_metrics([r for r in cohort if r['path']==p],duration,d,None))
            pr.pop('VIN_J_per_timely_frame'); pr.pop('VIN_timely_energy_status')
            paths.append(pr)
    return runs, streams, paths


def summarize(manifest, frames, power):
    try:
        s = _summary(manifest,frames,power)
    except (ValueError,TypeError,KeyError):
        s = dict(errors=['Canonical replay failure: '+traceback.format_exc()])
        invalidate(s)
    s['experiment'] = 'CANONICAL_TIMELY_SERVICE'
    s['timely_good_threshold'] = None
    if s['integrity_status'] != 'VALID':
        return s
    try:
        runs, streams, paths = timely_rows(manifest,frames,s)
        s.update(deadlines=runs, stream_deadlines=streams, path_deadlines=paths,
            admitted_identity_sha256=hashlib.sha256(json.dumps(sorted(
                (r['stream_id'],r['frame_id']) for r in due_cohort(manifest,frames)),separators=(',',':')).encode()).hexdigest(),
            timely_population='active source-due admitted frames; completion includes drain; all E2E uses Thor clock',
            timely_energy_scope='active Thor VIN module+carrier input / on-time active-admitted cohort; excludes drain energy and Edge energy; not all-system energy')
    except (ValueError,TypeError,KeyError,statistics.StatisticsError):
        s.setdefault('errors',[]).append('Deadline accounting failure: '+traceback.format_exc())
        invalidate(s)
    return s


def invalidate(s):
    s.update(integrity_status='INVALID', validity='INVALID', queue_stable=False,
             backlog_stable=False, queue_classification='INVALID', pipeline_audit_status='FAIL')


def aggregate(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    result=[]
    for group_key, all_rows in sorted(groups.items()):
        valid = [r for r in all_rows if r['integrity_status']=='VALID']
        metrics = sorted({k for r in all_rows for k,v in r.items() if finite(v)}-set(keys)-{'repeat','order_index'})
        for key in metrics:
            values=[r[key] for r in valid if finite(r.get(key))]
            result.append(dict(zip(keys,group_key), metric=key,planned=3,present=len(all_rows),
                integrity_valid_n=len(valid), metric_available_n=len(values),
                mean=statistics.mean(values) if values else None,
                sample_SD=statistics.stdev(values) if len(values)>1 else None))
    return result


def verify_lifecycle(m,c):
    for k in ('run_id','repeat','cell','supply_mode','target_service_FPS','local_r','edge_r'):
        if m.get(k)!=c[k]:raise ValueError('Condition mismatch: '+k)
    if m.get('requested_freq_MHz')!=1575 or m.get('execution_manifest_sha256')!=sha(PLAN):
        raise ValueError('Frequency/plan provenance mismatch')
    if m.get('child_returncode')!=0 or m.get('PROCESS_LIFECYCLE')!='PASS':
        raise ValueError('Child lifecycle failed')
    if not all(m.get(k) for k in ('status_finalized','active_phase_completed','drain_completed',
                                  'cleanup_started','cleanup_completed','frequency_restore_ok')):
        raise ValueError('Incomplete lifecycle/drain/restore')
    pre=OUT/'frequency_preflight.json'; record=json.loads(pre.read_text())
    if record.get('status')!='PASS' or record.get('plan_sha256')!=sha(PLAN) or m.get('frequency_preflight',{}).get('sha256')!=sha(pre):
        raise ValueError('Frequency preflight mismatch')
    pin=m.get('pin_readback_Hz',{})
    if (pin.get('min_freq'),pin.get('max_freq'))!=(1575000000,)*2:
        raise ValueError('Pin readback mismatch')


def comparisons(deadlines):
    lookup={(r['cell'],r['repeat'],r['deadline_ms']):r for r in deadlines}
    rows=[]
    metrics=('raw_completed_FPS','timely_FPS','TIR','worst_stream_TIR','late_FPS','VIN_J_per_timely_frame')
    pairs=[('PLACEMENT',f'T{s}-A',f'T{s}-B') for s in (160,200,240)]
    pairs += [('ADMISSION',f'T{a}-{mode}',f'T{b}-{mode}') for mode in ('A','B') for a,b in ((240,200),(200,160),(240,160))]
    for kind,a,b in pairs:
        for repeat in (1,2,3):
            for d in DEADLINES:
                ar,br=lookup[a,repeat,d],lookup[b,repeat,d]
                for metric in metrics:
                    valid=ar['integrity_status']==br['integrity_status']=='VALID' and finite(ar.get(metric)) and finite(br.get(metric))
                    rows.append(dict(comparison=kind,from_cell=a,to_cell=b,repeat=repeat,deadline_ms=d,
                        metric=metric,from_value=ar.get(metric),to_value=br.get(metric),
                        to_minus_from=br[metric]-ar[metric] if valid else None,
                        comparison_eligible=valid))
    return rows


def analyze(output):
    if output.exists():raise RuntimeError('No existing analysis overwrite')
    plan=load_plan(); before={str(PLAN):sha(PLAN)}; summaries=[]; runs=[]; streams=[]; paths=[]
    for c in plan['order']:
        d=OUT/c['run_id']; s={}
        for p in d.rglob('*'):
            if p.is_file():before[str(p)]=sha(p)
        try:
            m=json.loads((d/'manifest.json').read_text())
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            verify_lifecycle(m,c)
            stored=json.loads((d/'summary.json').read_text())
            if stored.get('integrity_status')!='VALID':raise ValueError('Stored final integrity is not VALID')
            for k in ('admitted_frames','total_completed_active_frames','completed_frames_including_drain','g_B_H','g_B_L','g_B_E'):
                if not math.isclose(stored[k],s[k],rel_tol=0,abs_tol=1e-9):raise ValueError('Replay mismatch: '+k)
        except Exception:
            s.setdefault('errors',[]).append(traceback.format_exc()); invalidate(s)
        meta={k:c[k] for k in ('run_id','cell','target_service_FPS','supply_mode','repeat','order_index')}
        s.update(meta); summaries.append(s)
        meta.update(integrity_status=s['integrity_status'],raw_queue_stable=s.get('queue_stable',False))
        for field,dest in [('deadlines',runs),('stream_deadlines',streams),('path_deadlines',paths)]:
            rows=s.get(field,[])
            if field=='deadlines' and not rows:
                rows=[dict(deadline_ms=d) for d in DEADLINES]
            dest.extend(dict(meta,**row) for row in rows)
    # Actual paired raw identity check, not just equal frame counts.
    identity_checks=[]
    for target in (160,200,240):
        for repeat in (1,2,3):
            pair=[s for s in summaries if s['target_service_FPS']==target and s['repeat']==repeat]
            hashes=[s.get('admitted_identity_sha256') for s in pair]
            status='UNAVAILABLE' if len(pair)!=2 or None in hashes else 'PASS' if len(set(hashes))==1 else 'MISMATCH'
            identity_checks.append(dict(target_service_FPS=target,repeat=repeat,status=status))
            # Missing B does not invalidate otherwise valid A evidence (or vice versa).
            if status=='MISMATCH':
                for s in pair:
                    s.setdefault('errors',[]).append('A/B admitted identity mismatched'); invalidate(s)
                for rows in (runs,streams,paths):
                    for r in rows:
                        if r['target_service_FPS']==target and r['repeat']==repeat:
                            r.update(integrity_status='INVALID',raw_queue_stable=False)
    assert all(sha(Path(p))==v for p,v in before.items()),'Input changed during replay'
    output.mkdir(parents=True,exist_ok=False)
    flat=[flatten({k:v for k,v in s.items() if k not in ('deadlines','stream_deadlines','path_deadlines')}) for s in summaries]
    for name,rows in [('per_run_metrics',flat),('per_run_deadlines',runs),('per_stream_deadlines',streams),
                      ('per_path_deadlines',paths),('condition_metrics',aggregate(flat,['cell'])),
                      ('condition_deadlines',aggregate(runs,['cell','deadline_ms'])),
                      ('paired_differences',comparisons(runs))]:
        if rows:write_csv(output/(name+'.csv'),rows)
    with (output/'replay.json').open('x') as f:json.dump(summaries,f,indent=2)
    text=['# Canonical timely-service map','',
        'Only these 18 planned runs; no historical pooling. All invalid/missing runs retained and excluded from numerical aggregation with explicit valid_n. No deadline pass/fail threshold or automatic winner.',
        'Raw FPS counts active completions. Timely/late FPS and TIR use all active-admitted frames including drain; missing is separate from late. Equal repeat weighting, sample SD. VIN energy is active Thor input only; no drain/Edge energy or per-path allocation. Zero timely frames => N/A J/timely frame.',
        'Admission comparisons in B mode also change the frozen Local/Edge allocation (40 or16 Edge FPS); they are whole-configuration comparisons, not isolated causal effects of admission.', '',
        '|Cell|Valid|Raw stable|D40 FPS/TIR|D60|D80|D100|D150|D200|',
        '|---|---|---|---|---|---|---|---|---|']
    for cell in sorted({c['cell'] for c in plan['order']}):
        ss=[s for s in summaries if s['cell']==cell]
        cells=[]
        for d in DEADLINES:
            rr=[r for r in runs if r['cell']==cell and r['deadline_ms']==d and r['integrity_status']=='VALID']
            if not rr:cells.append('N/A');continue
            def ms(k):
                vs=[r[k] for r in rr];return f'{statistics.mean(vs):.4f} ± '+(f'{statistics.stdev(vs):.4f}' if len(vs)>1 else 'N/A')
            cells.append(ms('timely_FPS')+' / '+ms('TIR'))
        text.append(f'|{cell}|{sum(s["integrity_status"]=="VALID" for s in ss)}/3|{sum(s.get("queue_stable",False) for s in ss)}/3|'+'|'.join(cells)+'|')
    with (output/'timely_service_map.md').open('x') as f:f.write('\n'.join(text)+'\n')
    with (output/'verification.json').open('x') as f:json.dump(dict(input_sha256=before,preservation='PASS',
        plan_sha256=sha(PLAN),planned=18,valid=sum(s['integrity_status']=='VALID' for s in summaries),
        paired_identity_checks=identity_checks),f,indent=2)
    print('\n'.join(text))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    analyze(ap.parse_args().output)
