#!/usr/bin/env python3
"""Read-only raw replay and C comparisons; writes only new campaign aggregates."""
import csv
import itertools
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/rate_dvfs_gate'))
from analyze_rate_dvfs_gate import summarize, read_csv, write_csv, FIELDS
from run_c_robustness_gate import load_plan, OUT


def comparison(a, b, runs):
    same = a['stability']==b['stability']=='STABLE'
    throughput_gap = abs(a['aggregate_completed_fps']-b['aggregate_completed_fps'])/max(a['aggregate_completed_fps'],b['aggregate_completed_fps'])
    equivalent = same and throughput_gap<=.01
    ar = {s['repeat']:s for s in runs if s['operating_point']==a['operating_point'] and s['C']==a['C'] and s['integrity_status']=='VALID'}
    br = {s['repeat']:s for s in runs if s['operating_point']==b['operating_point'] and s['C']==b['C'] and s['integrity_status']=='VALID'}
    repeats = sorted(ar.keys() & br.keys())
    power_gap = 1-min(a['avg_power_W'],b['avg_power_W'])/max(a['avg_power_W'],b['avg_power_W'])
    energy_gap = 1-min(a['energy_per_frame_J'],b['energy_per_frame_J'])/max(a['energy_per_frame_J'],b['energy_per_frame_J']) if equivalent else None
    protection_contrast = len(repeats)>=2 and (
        all(ar[i]['OC3_delta']==0 and br[i]['OC3_delta']>0 for i in repeats)
        or all(br[i]['OC3_delta']==0 and ar[i]['OC3_delta']>0 for i in repeats))
    return dict(operating_point=a['operating_point'], C_pair=[a['C'],b['C']],
                service_equivalent=equivalent, throughput_difference_fraction=throughput_gap,
                throughput_gain_fraction=max(a['aggregate_completed_fps'],b['aggregate_completed_fps'])/min(a['aggregate_completed_fps'],b['aggregate_completed_fps'])-1,
                power_saving_fraction=power_gap, energy_saving_fraction=energy_gap,
                matched_repeats=repeats, repeated_clean_vs_protected=protection_contrast,
                OC3_by_repeat_a=[ar[i]['OC3_delta'] for i in repeats],
                OC3_by_repeat_b=[br[i]['OC3_delta'] for i in repeats],
                lower_power_C=a['C'] if a['avg_power_W']<b['avg_power_W'] else b['C'],
                power_direction_consistent=len(repeats)>=2 and (
                    all(ar[i]['avg_power_W']<br[i]['avg_power_W'] for i in repeats)
                    or all(br[i]['avg_power_W']<ar[i]['avg_power_W'] for i in repeats)))


def analyze():
    plan = load_plan()
    runs = []
    for condition in plan['smoke']+plan['order']:
        directory = OUT/condition['run_id']
        if not (directory/'summary.json').exists():
            continue
        m = json.loads((directory/'manifest.json').read_text())
        s = json.loads((directory/'summary.json').read_text())
        if not s.get('status_finalized'):
            continue
        if s['integrity_status']=='VALID':
            replay = summarize(m,read_csv(directory/'per_frame.csv.gz'),read_csv(directory/'power_trace.csv.gz'))
            for key,value in replay.items():
                if s.get(key)!=value:
                    raise RuntimeError(f'raw replay mismatch: {directory.name} {key}')
            if s['child_returncode']!=0 or s.get('active_concurrency_peak',0)>s['C']:
                raise RuntimeError('invalid lifecycle/concurrency marked valid')
        s['per_stream_completed_fps'] = json.dumps([p['R_k'] for p in s.get('per_stream',[])])
        runs.append(s)
    write_csv(OUT/'aggregate_summary.csv',
              ['run_id','operating_point','kind','repeat']+FIELDS+
              ['per_stream_completed_fps','backlog_after_drain','child_returncode','child_exit_signal','frequency_restore_ok','PROCESS_LIFECYCLE'],runs)
    primary = [s for s in runs if s['kind']=='primary']
    cells = []
    for point in plan['operating_points']:
        for c in (1,2,4):
            group = [s for s in primary if s['operating_point']==point['name'] and s['C']==c]
            valid = [s for s in group if s['integrity_status']=='VALID']
            cell = dict(operating_point=point['name'],K=point['K'],admission_fps_per_stream=point['r'],
                        aggregate_demand_fps=point['K']*point['r'],frequency_MHz=point['MHz'],C=c,
                        attempted_repetitions=len(group),valid_repetitions=len(valid),invalid_repetitions=len(group)-len(valid))
            flags = [s['queue_stable'] for s in valid]
            usable = len(valid)>=2
            cell['integrity_status'] = 'VALID' if usable else 'INCONCLUSIVE'
            cell['stability'] = ('STABLE' if all(flags) else 'UNSTABLE' if not any(flags) else 'MIXED') if usable else 'INCONCLUSIVE'
            mapping = {'aggregate_completed_fps':'aggregate_completed_fps','min_per_stream_completed_fps':'min_per_stream_completed_fps',
                       'mean_per_stream_completed_fps':'mean_per_stream_completed_fps','backlog_slope_g_B':'g_B',
                       'avg_power_W':'avg_power_W','active_energy_J':'active_energy_J',
                       'energy_per_frame_J':'energy_per_frame_J','mean_active_concurrency':'active_concurrency_mean',
                       'actual_freq_mean_MHz':'actual_freq_mean_MHz','OC3_delta':'OC3_delta',
                       'temperature_C':'temperature','backlog_at_active_end':'backlog_at_active_end'}
            for target,source in mapping.items():
                values = [s.get(source) for s in valid]
                cell[target] = statistics.mean(values) if usable and all(isinstance(v,(float,int)) for v in values) else None
            if cell['stability']!='STABLE':cell['energy_per_frame_J']=None
            cell['peak_active_concurrency'] = max((s.get('active_concurrency_peak',0) for s in valid),default=None)
            cell['OC3_total'] = sum(s.get('OC3_delta',0) for s in valid)
            cell['OC3_by_repeat'] = json.dumps([s.get('OC3_delta') for s in sorted(valid,key=lambda x:x['repeat'])])
            cell['clean_runs'] = sum(s['hardware_status']=='CLEAN' for s in valid)
            cell['protection_limited_runs'] = sum(s['hardware_status']=='PROTECTION_LIMITED' for s in valid)
            cell['hardware_status'] = 'PROTECTION_LIMITED' if cell['protection_limited_runs'] else 'CLEAN' if valid else 'UNAVAILABLE'
            cell['frontend_limited_runs'] = sum(s.get('supply_status')=='FRONTEND_LIMITED' for s in valid)
            cell['frontend_status'] = 'FRONTEND_LIMITED' if cell['frontend_limited_runs'] else 'NORMAL' if valid else 'UNAVAILABLE'
            cell['per_stream_completed_fps'] = json.dumps([statistics.mean(s['per_stream'][i]['R_k'] for s in valid) for i in range(point['K'])]) if usable else None
            cells.append(cell)
    write_csv(OUT/'c_configuration_table.csv',list(cells[0]),cells)
    complete = len(primary)==27 and all(c['integrity_status']=='VALID' and c['stability']!='MIXED' for c in cells)
    pairs=[];frontier={};selection={};effects={}
    for point in ('A','B','C'):
        group=[c for c in cells if c['operating_point']==point]
        if not all(c['integrity_status']=='VALID' for c in group):
            frontier[point]=[];continue
        ps=[comparison(a,b,primary) for a,b in itertools.combinations(group,2)]
        pairs.extend(ps)
        effects[point] = dict(stable_vs_unstable=len({c['stability'] for c in group})>1,
                             throughput_5pct=any(p['throughput_gain_fraction']>=.05 for p in ps),
                             equivalent_service_cost_5pct=any(p['service_equivalent'] and (p['power_saving_fraction']>=.05 or p['energy_saving_fraction']>=.05) for p in ps),
                             repeated_clean_vs_protected=any(p['repeated_clean_vs_protected'] for p in ps))
        stable = [c for c in group if c['stability']=='STABLE']
        def dominates(a,b):
            rate_diff=abs(a['aggregate_completed_fps']-b['aggregate_completed_fps'])/max(a['aggregate_completed_fps'],b['aggregate_completed_fps'])
            costs=('avg_power_W','energy_per_frame_J','OC3_delta')
            return rate_diff<=.01 and all(a[k]<=b[k] for k in costs) and any(a[k]<b[k] for k in costs)
        frontier[point] = [b['C'] for b in stable if not any(a is not b and dominates(a,b) for a in stable)]
    common = set.intersection(*(set(frontier.get(p,[])) for p in ('A','B','C')))
    if not complete:
        verdict='INCONCLUSIVE'
    elif not any(any(v.values()) for v in effects.values()) and all(c['stability']=='STABLE' for c in cells):
        verdict='C_EFFECT_SMALL';selection={'static_C':min(common) if common else 1}
    elif common:
        verdict='STATIC_C_SUFFICIENT';selection={'static_C':min(common)}
    elif all(len(frontier.get(p,[]))==1 for p in ('A','B','C')):
        verdict='OFFLINE_C_MAP_SUFFICIENT';selection={p:frontier[p][0] for p in ('A','B','C')}
    else:
        verdict='C_COUPLING_MATERIAL_BUT_UNRESOLVED'
    fmt=lambda v:'N/A' if v is None else f'{v:.4f}'
    lines=['# C robustness / offline configuration Gate','',f'Overall: **{verdict}**','',
           f'Primary completed/finalized: {len(primary)}/27; integrity VALID {sum(s["integrity_status"]=="VALID" for s in primary)}, INVALID {sum(s["integrity_status"]!="VALID" for s in primary)}. Smoke excluded from primary statistics.',
           f'Hardware counts: CLEAN {sum(s.get("hardware_status")=="CLEAN" for s in primary)}, PROTECTION_LIMITED {sum(s.get("hardware_status")=="PROTECTION_LIMITED" for s in primary)}. FRONTEND_LIMITED {sum(s.get("supply_status")=="FRONTEND_LIMITED" for s in primary)}.',
           '', 'B(t)=logical admissions minus completions, all local stages included. g_B uses only active t=30..60 s. Stable requires g_B<=0.5 frames/s, valid integrity and no cap/drop. Drain is accounting only. All valid raw summaries replay identically. VDD_GPU is measured rail power; J/frame is reported only for stable conditions. Condition values are means of valid repetitions (minimum two), peak concurrency is the maximum observed peak. OC3_delta in CSV is the per-run mean; OC3_total and per-repeat counts are separate.',
           '', '| Point | C | completed FPS | min/mean stream FPS | g_B | stability | GPU W | active J | J/frame | peak/mean concurrency | OC3 by repeat | frontend limited | valid/attempted |',
           '|---|---:|---:|---|---:|---|---:|---:|---:|---|---|---:|---|']
    for c in cells:
        lines.append(f"| {c['operating_point']} | {c['C']} | {fmt(c['aggregate_completed_fps'])} | {fmt(c['min_per_stream_completed_fps'])}/{fmt(c['mean_per_stream_completed_fps'])} | {fmt(c['backlog_slope_g_B'])} | {c['stability']} | {fmt(c['avg_power_W'])} | {fmt(c['active_energy_J'])} | {fmt(c['energy_per_frame_J'])} | {c['peak_active_concurrency']}/{fmt(c['mean_active_concurrency'])} | {c['OC3_by_repeat']} | {c['frontend_limited_runs']} | {c['valid_repetitions']}/{c['attempted_repetitions']} |")
    lines += ['', 'Service-equivalent comparisons and material effects (frozen definitions):']
    for pair in pairs:lines.append('- '+json.dumps(pair))
    lines += ['', 'Material effect flags by point: '+json.dumps(effects),
              '', 'Non-dominated stable C values by point: '+json.dumps(frontier),
              'Offline selection under the frozen descriptive rules: '+json.dumps(selection),
              '', 'Dominance is descriptive at these fixed operating points: among stable configurations providing service within 1%, a configuration dominates another if mean power, J/frame and mean OC3 are all no greater and at least one is lower. Differences and repeat consistency are reported; small numerical dominance is not a statistical significance claim. Counts may expose power/protection trade-offs, for which no unmeasured preference or objective weighting is invented.']
    if verdict in ('STATIC_C_SUFFICIENT','OFFLINE_C_MAP_SUFFICIENT','C_EFFECT_SMALL'):
        lines += ['', 'These three fixed points support keeping C as offline execution configuration and retaining r_k(t), s(t) as the proposed runtime actions. This is conditional evidence within the measured grid, not a proof for dynamic traces or other workloads. No controller or Dynamic-C was implemented.']
    else:
        lines += ['', 'The available C comparisons do not resolve a sufficient offline configuration across all three points. This is not authorization or evidence to implement Dynamic-C immediately; the action choice remains unresolved within this Gate.']
    lines += ['', 'mu(s,C) interpretation: reported changes are Local system completed capacity at fixed demand/frequency, not ready-queue improvement or a fitted GPU-only service law. FRONTEND_LIMITED and protection behavior remain part of the operating result.',
              '', 'Historical rate-DVFS references (not pooled with the new campaign):']
    for ref in plan['historical_reference']:
        old=[json.loads((ROOT/'results/rate_dvfs_gate'/rid/'summary.json').read_text()) for rid in ref['run_ids']]
        new=next(c for c in cells if c['operating_point']==ref['operating_point'] and c['C']==ref['C'])
        lines.append('- '+json.dumps(dict(operating_point=ref['operating_point'],C=ref['C'],historical_run_ids=ref['run_ids'],historical_completed_fps=statistics.mean(s['aggregate_completed_fps'] for s in old),new_completed_fps=new['aggregate_completed_fps'],historical_power_W=statistics.mean(s['avg_power_W'] for s in old),new_power_W=new['avg_power_W'])))
    invalid=[s for s in runs if s['integrity_status']!='VALID']
    lines += ['', 'Invalid runs retained without automatic retry:']+(['- '+s['run_id']+': '+str(s.get('errors')) for s in invalid] or ['- None.'])
    (OUT/'gate_verdict.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'verdict':verdict,'selection':selection,'frontier':frontier,'effects':effects,'primary_count':len(primary)}))


if __name__=='__main__':
    analyze()
