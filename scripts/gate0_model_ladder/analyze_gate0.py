#!/usr/bin/env python3
"""CPU-only Gate 0 replay. Independent predictor stage precedes target loading.

No runtime imports, inference, device access, or network actions. All writes are
exclusive and confined to a new output directory containing a frozen M4_SPEC.
"""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import heapq
import importlib.util
import json
import math
from pathlib import Path
import statistics as st
import subprocess

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[2]
LEGACY = Path('/home/ainet/research/thor-mec-inference')
FREQS = [630, 792, 945, 1107, 1260, 1413, 1575]
DIRECT = [945, 1260, 1575]
ENGINE = '9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff'
INPUTS = {}
SCHEMAS = {}
REPLAYS = []


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def record(p, role):
    p = Path(p).resolve()
    if role == 'PREDICTOR' and 'local_capacity_characterization' in p.parts:
        raise RuntimeError('Target trace forbidden in predictor stage')
    entry = INPUTS.setdefault(str(p), dict(sha256=sha(p), roles=[]))
    if role not in entry['roles']: entry['roles'].append(role)
    return p


def read_json(p, role):
    return json.loads(record(p, role).read_text())


def read_csv(p, role):
    p = record(p, role)
    with (gzip.open(p, 'rt', newline='') if p.suffix == '.gz' else p.open(newline='')) as f:
        reader = csv.DictReader(f)
        SCHEMAS[str(p)] = reader.fieldnames
        return list(reader)


def write_json(out, name, value):
    with (out / name).open('x') as f: json.dump(value, f, indent=2, allow_nan=False)


def write_csv(out, name, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (out / name).open('x', newline='') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()})


def close(a, b):
    return math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-10)


def canonical():
    path = record(ROOT / 'scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py', 'REPLAY_SOURCE')
    spec = importlib.util.spec_from_file_location('gate0_canonical_replay', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay(d, role, analyzer):
    m = read_json(d / 'manifest.json', role)
    stored = read_json(d / 'summary.json', role)
    frames = read_csv(d / 'per_frame.csv.gz', role)
    power = read_csv(d / 'power_trace.csv.gz', role)
    raw = analyzer.summarize(m, frames, power)
    bad = [k for k, v in raw.items() if stored.get(k) != v]
    if bad: raise RuntimeError(f'{d.name}: raw/summary mismatch {bad}')
    assert raw['integrity_status'] == 'VALID' and m['child_returncode'] == 0 and m['frequency_restore_ok']
    assert m['engine_provenance']['sha256'] == ENGINE
    REPLAYS.append(dict(run_id=d.name, role=role, status='PASS', checked_fields=len(raw)))
    return m, raw, frames


def queue_model(r, tconc_ms, shape, frontend_fps):
    """Profile-driven simulation, not a measured workload or measured capacity."""
    front = np.zeros(8)
    jobs = []
    for n in range(1800):
        due = (n * 10**9 // 30) / 1e9
        admitted = (n + 1) * r // 30 > n * r // 30
        for k in range(8):
            front[k] = max(due, front[k]) + 8 / frontend_fps
            if admitted: jobs.append((front[k], due, k))
    jobs.sort()
    workers = [(0., 0), (0., 1)]
    arrival, completed = [], []
    for i, (ready, due, _) in enumerate(jobs):
        free, worker = heapq.heappop(workers)
        end = max(free, ready) + tconc_ms / 1000 * shape[i % len(shape)]
        heapq.heappush(workers, (end, worker))
        arrival.append(due)
        completed.append(end)
    a, c = np.array(arrival), np.array(completed)
    left, right = np.maximum(a, 30.) - 45., np.minimum(c, 60.) - 45.
    mask = right > left
    g = float(np.sum((right[mask]**2 - left[mask]**2) / 2) / (30**3 / 12))
    return dict(demand_FPS=8 * r, g_B_model=g,
                predicted_feasible=bool(g <= .5 and frontend_fps >= 240),
                active_end_backlog_model=int(np.sum(c >= 60)),
                provenance='CPU_QUEUE_MODEL_NOT_MEASUREMENT')


def build_predictions(out, analyzer):
    iso, iso_ids, source_rows = {}, {}, []
    for f in FREQS:
        means, ids = [], []
        for d in sorted((ROOT / 'results/capacity_model_validity').glob(f'ISO_*_F{f:04d}_REP*')):
            m = read_json(d / 'manifest.json', 'PREDICTOR')
            s = read_json(d / 'summary.json', 'PREDICTOR')
            rows = read_csv(d / 'latency_samples.csv.gz', 'PREDICTOR')
            active = [x for x in rows if x['phase'] == 'measurement']
            values = [(int(x['completion_ns']) - int(x['start_ns'])) / 1e6 for x in active]
            assert m['engine']['sha256'] == ENGINE and m['C'] == m['batch_size'] == 1
            assert m['child_returncode'] == 0 and m['frequency_restore_ok'] and s['integrity_status'] == 'VALID'
            assert len(active) == s['measurement_count'] and close(st.mean(values), s['service_ms']['mean'])
            assert all(close(v, float(x['service_ms'])) for v, x in zip(values, active))
            assert all(int(a['completion_ns']) <= int(b['start_ns']) for a, b in zip(rows, rows[1:]))
            means.append(st.mean(values)); ids.append(d.name)
            REPLAYS.append(dict(run_id=d.name, role='PREDICTOR', status='PASS', checked_fields='service/count/order'))
        assert len(means) == 3
        iso[f], iso_ids[f] = st.mean(means), ids
    concurrent, shapes, conc_ids = {}, {}, {}
    for f in DIRECT:
        vals, seqs, ids = [], [], []
        for d in [ROOT / 'results/rate_dvfs_gate' / f'RDVG_B_20260919_S{i:02d}' for i in range(1, 10)]:
            m = read_json(d / 'manifest.json', 'PREDICTOR')
            if m['requested_freq_MHz'] != f: continue
            m, s, frames = replay(d, 'PREDICTOR', analyzer)
            assert (m['K'], m['C'], m['admission_fps_per_stream']) == (6, 2, 30)
            active = [x for x in frames if x['phase'] == 'active' and x['inference_start_timestamp_ns']
                      and m['active_start_ns'] <= int(x['inference_start_timestamp_ns']) < m['active_end_ns']]
            active.sort(key=lambda x: (int(x['inference_start_timestamp_ns']), int(x['worker_id'])))
            values = np.array([(int(x['completion_timestamp_ns']) - int(x['inference_start_timestamp_ns'])) / 1e6 for x in active])
            mean = float(values.mean())
            vals.append(mean); seqs.extend(values / mean); ids.append(d.name)
            source_rows.append(dict(frequency_MHz=f, T_iso_source_runs=iso_ids[f], T_conc_source_run=d.name,
                T_conc_mean_ms=mean, workload='K6/r30/180FPS live pipeline', C=2,
                interval='Inference START inside active 60s; allow finish in drain',
                active_start_ns=m['active_start_ns'], active_end_ns=m['active_end_ns'],
                samples=len(values), independent_target_campaign=True, primary_parameter=True,
                same_target_K8_condition=False, OC3=s['OC3_delta'],
                decode_acquisition_mean_ms=st.mean((int(x['source_pulled_ns'])-int(x['b_ns']))/1e6 for x in active),
                preprocess_to_enqueue_mean_ms=st.mean((int(x['ready_timestamp_ns'])-int(x['source_pulled_ns']))/1e6 for x in active)))
        assert len(vals) == 3
        concurrent[f], shapes[f], conc_ids[f] = st.mean(vals), np.array(seqs), ids
    # Separate, stratified diagnostics: do not mix operating points in a predictor.
    for d in sorted((ROOT / 'results/c_robustness_gate').glob('CRG_*_P*')):
        m = read_json(d / 'manifest.json', 'INVENTORY_ONLY')
        if m['C'] != 2: continue
        m, s, frames = replay(d, 'INDEPENDENT_DIAGNOSTIC', analyzer)
        active = [x for x in frames if x['phase'] == 'active' and x['inference_start_timestamp_ns']
                  and m['active_start_ns'] <= int(x['inference_start_timestamp_ns']) < m['active_end_ns']]
        source_rows.append(dict(frequency_MHz=m['requested_freq_MHz'], T_iso_source_runs=iso_ids[m['requested_freq_MHz']],
            T_conc_source_run=d.name, T_conc_mean_ms=st.mean((int(x['completion_timestamp_ns'])-int(x['inference_start_timestamp_ns']))/1e6 for x in active),
            workload=f"K{m['K']}/r{m['admission_fps_per_stream']}/{m['operating_point']}", C=2,
            interval='Inference START inside active60s', independent_target_campaign=True,
            primary_parameter=False, same_target_K8_condition=False, OC3=s['OC3_delta']))
    for f in FREQS:
        if f not in DIRECT:
            source_rows.append(dict(frequency_MHz=f, T_iso_source_runs=iso_ids[f], T_conc_source_run=None,
                primary_parameter=False, independent_target_campaign=None, interval=None,
                status='INTERPOLATED_ONLY' if min(DIRECT)<f<max(DIRECT) else 'MISSING_NO_EXTRAPOLATION'))
    write_csv(out, 'tconc_sources.csv', source_rows)
    front_profiles = {}
    for name in ['decode_preprocess_profiling', 'preprocess_profiling']:
        rows = read_csv(LEGACY / 'results' / name / 'formal_runs.csv', 'PREDICTOR')
        values = [float(x['aggregate_fps']) for x in rows if int(x['streams']) == 8]
        assert len(values) == 3
        front_profiles[name] = dict(FPS_mean=st.mean(values), FPS_by_repeat=values,
                                   provenance='Measured K8 replicated Warehouse000, unlocked GPU; transfer assumption')
    frontfps = front_profiles['decode_preprocess_profiling']['FPS_mean']
    write_json(out, 'frontend_parameters.json', front_profiles)
    x = np.array(DIRECT) / 1000
    y = np.array([concurrent[f] for f in DIRECT])
    fit = least_squares(lambda p: p[0]*x**(-p[1])+p[2]-y, [5., 1., 1.],
                        bounds=([0., .01, 0.], [np.inf, 10., np.inf]),
                        xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=10000)
    write_json(out, 'power_law_sensitivity_fit.json', dict(a_ms_scaled=float(fit.x[0]), b=float(fit.x[1]),
        c_ms=float(fit.x[2]), success=bool(fit.success), residuals_ms=fit.fun.tolist(),
        frequencies=DIRECT, no_extrapolation=True, primary=False, degrees_of_freedom=0))
    capacities, details, models = [], [], {}
    for variant in ['PRIMARY', 'POWER_LAW_SENSITIVITY']:
        for f in FREQS:
            tc = None
            if min(DIRECT) <= f <= max(DIRECT):
                tc = (float(np.interp(f, DIRECT, [concurrent[g]/iso[g] for g in DIRECT])) * iso[f]
                      if variant == 'PRIMARY' else float(fit.x[0]*(f/1000)**(-fit.x[1])+fit.x[2]))
            if variant == 'PRIMARY':
                for model, mu in [('M1', 1000/iso[f]), ('M2', 2000/iso[f])]:
                    models[model, f] = mu
                    capacities.append(dict(model=model, variant=variant, frequency_MHz=f, mu_hat_FPS=mu,
                        provenance='ISOLATED_MEASURED_PARAMETER', T_iso_ms=iso[f], T_conc_ms=None))
            suffix = '' if variant == 'PRIMARY' else '_POWER_LAW'
            m3, m4 = 'M3'+suffix, 'M4'+suffix
            mu4 = None
            if tc is not None:
                donor = min(DIRECT, key=lambda g: (abs(g-f), g))
                simulations = [queue_model(r, tc, shapes[donor], frontfps) for r in range(1, 31)]
                flags = [x['predicted_feasible'] for x in simulations]
                downward = flags == sorted(flags, reverse=True)
                mu4 = max((x['demand_FPS'] for x in simulations if x['predicted_feasible']), default=0) if downward else None
                details.extend(dict(model=m4, frequency_MHz=f, donor_frequency=donor,
                                    downward_closed=downward, **row) for row in simulations)
            for model, mu in [(m3, 2000/tc if tc is not None else None), (m4, mu4)]:
                models[model, f] = mu
                capacities.append(dict(model=model, variant=variant, frequency_MHz=f, mu_hat_FPS=mu,
                    provenance=('NO_INDEPENDENT_COVERAGE' if tc is None else
                                'DIRECT_CONCURRENT_PARAMETER' if f in DIRECT and variant=='PRIMARY' else 'ESTIMATED_PARAMETER'),
                    T_iso_ms=iso[f], T_conc_ms=tc,
                    note='M4 is simulated; direct refers to service parameter, never measured M4 capacity'))
    write_csv(out, 'model_capacity_predictions.csv', capacities)
    write_csv(out, 'm4_queue_predictions.csv', details)
    write_json(out, 'prediction_freeze.json', dict(created_UTC=datetime.now(timezone.utc).isoformat(),
        M4_SPEC_SHA256=sha(out/'M4_SPEC.md'), prediction_SHA256=sha(out/'model_capacity_predictions.csv'),
        queue_prediction_SHA256=sha(out/'m4_queue_predictions.csv'),
        target_trace_used=False, predictor_inputs={p:v for p,v in INPUTS.items() if 'PREDICTOR' in v['roles']}))
    return models, capacities, details


def load_targets(analyzer):
    base = ROOT / 'results/local_capacity_characterization'
    anchors = read_csv(base/'capacity_anchor_map.csv', 'EVALUATION_ONLY')
    bounds = {int(x['frequency_MHz']):(int(x['highest_stable_aggregate_admission_FPS']),
              8*int(x['lowest_unstable_r_per_stream'])) for x in anchors if x['boundary_status']=='CONFIRMED'}
    assert bounds == dict(zip(FREQS, [(96,104),(120,128),(144,152),(160,168),(176,184),(184,192),(200,208)]))
    groups = {}
    for d in sorted(base.glob('LCCA_*')):
        if not d.is_dir(): continue
        m, s, _ = replay(d, 'EVALUATION_ONLY', analyzer)
        groups.setdefault((m['requested_freq_MHz'], 8*m['admission_fps_per_stream']), []).append(s)
    endpoints = []
    for f, (stable, unstable) in bounds.items():
        for load, expect in [(stable, True), (unstable, False)]:
            rows = groups[f,load]
            assert len(rows)==3 and all(x['queue_stable']==expect and x['supply_status']=='NORMAL' for x in rows)
            endpoints.append(dict(frequency_MHz=f, demand_FPS=load, observed_stable=expect,
                run_ids=[x['run_id'] for x in rows], g_B=[x['g_B'] for x in rows],
                active_end_backlog=[x['backlog_at_active_end'] for x in rows],
                completed_FPS=[x['aggregate_completed_fps'] for x in rows],
                queue_wait_p95_ms=[x['queue_wait_ms']['p95'] for x in rows],
                frontend=[x['supply_status'] for x in rows], OC3=[x['OC3_delta'] for x in rows],
                hardware=[x['hardware_status'] for x in rows]))
    return bounds, groups, endpoints


def truth_selection(demand, bounds, domain):
    for f in domain:
        lo, hi = bounds[f]
        if demand <= lo: return f, 'BRACKET_CONFIRMED_MINIMUM_ANCHOR'
        if demand < hi: return None, 'INSIDE_UNTESTED_BRACKET'
    return None, 'NO_CONFIRMED_FEASIBLE_ANCHOR'


def selection(model, demand, models, domain, margin=0):
    missing = False
    for f in domain:
        mu = models[model,f]
        if mu is None: missing=True; continue
        if demand <= (1-margin/100)*mu:
            return (None, 'UNKNOWN_MISSING_LOWER_FREQUENCY') if missing else (f, 'PREDICTED')
    return None, 'UNKNOWN_MISSING_MODEL' if missing else 'PREDICTED_NONE_FEASIBLE'


def evaluate(model, scope, domain, models, demands, bounds, endpoints, margin=0):
    cases = []
    for ep in endpoints:
        if ep['frequency_MHz'] not in domain: continue
        mu = models[model,ep['frequency_MHz']]
        if mu is None: continue
        pred = ep['demand_FPS'] <= (1-margin/100)*mu
        label = ('TRUE_FEASIBLE' if ep['observed_stable'] else 'FALSE_FEASIBLE') if pred else (
                 'FALSE_INFEASIBLE' if ep['observed_stable'] else 'TRUE_INFEASIBLE')
        cases.append(dict(model=model, scope=scope, margin_percent=margin, mu_hat_FPS=mu, decision=label, **ep))
    freqrows = []
    for d in demands:
        actual, ast = truth_selection(d, bounds, domain)
        if actual is None: continue
        predicted, status = selection(model, d, models, domain, margin)
        base, _ = selection(model, d, models, domain, 0)
        decision = ('UNKNOWN' if status.startswith('UNKNOWN') else 'NO_FEASIBLE_PREDICTION' if predicted is None else
                    'EXACT' if predicted==actual else 'OVER_PROVISION' if predicted>actual else 'UNDER_PROVISION')
        error = abs(predicted-actual)/9 if predicted is not None else None
        freqrows.append(dict(model=model, scope=scope, margin_percent=margin, demand_FPS=d,
            actual_minimum_MHz=actual, predicted_MHz=predicted, status=status, decision=decision,
            absolute_physical_DVFS_steps=error,
            absolute_anchor_steps=abs(domain.index(predicted)-domain.index(actual)) if predicted is not None else None,
            over_provision_steps=max(0,(predicted-actual)/9) if predicted is not None else None,
            additional_DVFS_steps=(predicted-base)/9 if predicted is not None and base is not None else None))
    counts = {name:sum(x['decision']==name for x in cases) for name in
              ['FALSE_FEASIBLE','FALSE_INFEASIBLE','TRUE_FEASIBLE','TRUE_INFEASIBLE']}
    errors = [x['absolute_physical_DVFS_steps'] for x in freqrows if x['absolute_physical_DVFS_steps'] is not None]
    added = [x['additional_DVFS_steps'] for x in freqrows if x['additional_DVFS_steps'] is not None]
    over = [x['over_provision_steps'] for x in freqrows if x['over_provision_steps'] is not None]
    score = dict(model=model, scope=scope, margin_percent=margin,
        frequencies_with_prediction=sum(models[model,f] is not None for f in domain), domain_frequencies=domain,
        N=len(freqrows), known_frequency_decisions=sum(x['decision']!='UNKNOWN' for x in freqrows),
        exact_matches=sum(x['decision']=='EXACT' for x in freqrows),
        mismatches=sum(x['decision'] not in ('EXACT','UNKNOWN') for x in freqrows),
        unknown=sum(x['decision']=='UNKNOWN' for x in freqrows),
        over_provision=sum(x['decision']=='OVER_PROVISION' for x in freqrows),
        under_provision=sum(x['decision']=='UNDER_PROVISION' for x in freqrows),
        no_feasible_prediction=sum(x['decision']=='NO_FEASIBLE_PREDICTION' for x in freqrows),
        confusion_conditions=len(cases), **counts,
        absolute_DVFS_step_error_mean=st.mean(errors) if errors else None,
        absolute_DVFS_step_error_sum=sum(errors) if errors else None,
        additional_DVFS_steps_sum=sum(added) if added else None,
        additional_DVFS_steps_mean=st.mean(added) if added else None,
        additional_DVFS_steps_max=max(added) if added else None,
        over_provision_steps_mean=st.mean(over) if over else None)
    return score, freqrows, cases


def fmt(x):
    if x is None: return 'N/A'
    if isinstance(x,float): return f'{x:.3f}'
    if isinstance(x,list): return ', '.join(fmt(v) for v in x)
    return str(x)


def table(rows, fields):
    return '\n'.join(['| '+' | '.join(fields)+' |','| '+' | '.join(['---']*len(fields))+' |']+
        ['| '+' | '.join(fmt(r.get(f)) for f in fields)+' |' for r in rows])


def main(out):
    if (out/'model_capacity_predictions.csv').exists(): raise RuntimeError('No overwrite; use fresh directory with frozen spec')
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='rate-dvfs-gate'
    spec_record = json.loads((out/'m4_spec_record.json').read_text())
    assert sha(out/'M4_SPEC.md') == spec_record['M4_SPEC_SHA256']
    analyzer = canonical()
    models, capacities, simulations = build_predictions(out, analyzer)
    print('Independent predictions frozen; now loading evaluation targets.', flush=True)
    bounds, groups, endpoints = load_targets(analyzer)
    old = read_csv(ROOT/'results/capacity_model_validity/frequency_decision_map.csv','EVALUATION_ONLY')
    candidates = sorted({int(x['demand_FPS']) for x in old})
    preferred = sorted({int(x['demand_FPS']) for x in old if x['within_confirmed_map_demand_coverage']=='True'})
    demand_rows, demands = [], []
    for d in candidates:
        chosen, status = truth_selection(d, bounds, FREQS)
        usable = d in preferred and chosen is not None
        if usable: demands.append(d)
        actual = {f:rows for (f,load),rows in groups.items() if load==d and f in FREQS}
        # Do not silently override any directly observed contradiction.
        for f,rows in actual.items():
            expected = True if d<=bounds[f][0] else False if d>=bounds[f][1] else None
            if expected is not None: assert all(x['queue_stable']==expected for x in rows)
        demand_rows.append(dict(demand_FPS=d,K=8,per_stream_rate=d/8,source_campaign='local_capacity_characterization',
            actual_tested_frequencies=sorted(actual),
            confirmed_stable_evidence=[x['run_id'] for rows in actual.values() for x in rows if x['queue_stable']],
            confirmed_unstable_evidence=[x['run_id'] for rows in actual.values() for x in rows if not x['queue_stable']],
            actual_minimum_feasible_frequency_MHz=chosen, usable_primary=usable,
            status=status if usable else 'EXCLUDED_'+status,
            confidence='Minimum among 7 anchors under downward-closed demand-bracket assumption; not full141-state minimum',
            selected_frequency_direct_measurement=chosen in actual))
    write_csv(out,'demand_points.csv',demand_rows)
    write_csv(out,'empirical_endpoints.csv',endpoints)
    scores,frequency_rows,cases,sweeps = [],[],[],[]
    model_names = ['M1','M2','M3','M4','M3_POWER_LAW','M4_POWER_LAW']
    for model in model_names:
        scopes = [('FULL-7',FREQS)] + ([('DIRECT-ONLY',DIRECT)] if model.startswith(('M3','M4')) else [])
        for scope,domain in scopes:
            for margin in [0,5,10,15]:
                score,fr,ca = evaluate(model,scope,domain,models,demands,bounds,endpoints,margin)
                sweeps.append(score)
                if margin==0: scores.append(score);frequency_rows.extend(fr);cases.extend(ca)
    write_csv(out,'model_scores.csv',scores)
    write_csv(out,'frequency_selections.csv',frequency_rows)
    write_csv(out,'decision_cases.csv',cases)
    write_csv(out,'safety_margin_sweep.csv',sweeps)
    # Full model coverage is required for a seven-anchor Gate, not inferred from missing values.
    primary_m4 = next(s for s in scores if s['model']=='M4' and s['scope']=='FULL-7')
    gate='GATE0_INCONCLUSIVE'
    reason='Independent C2 profiles do not support630/792; FULL-7 M4 and its minimum-frequency predictions incomplete. No target-trace gap filling.'
    if primary_m4['frequencies_with_prediction']==7 and primary_m4['known_frequency_decisions']==12 and len(demands)==12:
        mismatched=[r for r in frequency_rows if r['model']=='M4' and r['scope']=='FULL-7' and r['decision']!='EXACT']
        mostly_near=not mismatched or sum(r['absolute_physical_DVFS_steps'] is not None and r['absolute_physical_DVFS_steps']<=1 for r in mismatched)>len(mismatched)/2
        if primary_m4['exact_matches']>=11 and primary_m4['FALSE_FEASIBLE']<=1 and mostly_near:
            gate='GATE0_KILL_MODEL_GAP';reason='Frozen complete-model KILL counts satisfied'
        elif primary_m4['FALSE_FEASIBLE']>=2 or primary_m4['mismatches']>=3:
            gate='GATE0_MODEL_GAP_SURVIVES';reason='Frozen complete-model SURVIVES counts satisfied'
    # Secondary sanity does not alter the frozen primary score or verdict.
    sanity=[]
    for row in simulations:
        if row['model']!='M4':continue
        s,u=bounds[row['frequency_MHz']];d=row['demand_FPS']
        expected=True if d<=s-16 else False if d>=u+16 else None
        if expected is not None:
            sanity.append(dict(**row,expected_feasible=expected,passed=row['predicted_feasible']==expected))
    structural=[]
    for f in sorted({x['frequency_MHz'] for x in sanity}):
        for side in [True,False]:
            rr=[x for x in sanity if x['frequency_MHz']==f and x['expected_feasible']==side]
            if rr and not any(x['passed'] for x in rr):structural.append(dict(frequency=f,side=side))
    m4valid='M4_INVALID' if structural or any(not x['downward_closed'] for x in simulations if x['model']=='M4') else 'PARTIAL_MODEL_NO_STRUCTURAL_SANITY_FAILURE'
    write_csv(out,'m4_sanity.csv',sanity)
    errors, ratios = [], []
    for row in capacities:
        f,mu=row['frequency_MHz'],row['mu_hat_FPS'];s,u=bounds[f]
        err=None if mu is None else 100*((mu-s)/s if mu<s else (mu-u)/u if mu>=u else 0)
        errors.append(dict(model=row['model'],frequency_MHz=f,mu_hat_FPS=mu,stable_FPS=s,next_unstable_FPS=u,
            inside_half_open_bracket=None if mu is None else s<=mu<u,signed_error_percent=err,
            absolute_error_percent=abs(err) if err is not None else None,scope='SECONDARY_POST_HOC'))
        ratios.append(dict(model=row['model'],frequency_MHz=f,stable_FPS_per_MHz=s/f,next_unstable_FPS_per_MHz=u/f,
                           stable_over_mu=None if mu in (None,0) else s/mu,provenance=row['provenance']))
    write_csv(out,'bracket_errors.csv',errors);write_csv(out,'ratio_curves.csv',ratios)
    error_summary=[]
    for model in model_names:
        vals=[x['absolute_error_percent'] for x in errors if x['model']==model and x['absolute_error_percent'] is not None]
        error_summary.append(dict(model=model,frequencies=len(vals),mean_absolute_bracket_error=st.mean(vals),
                                 median_absolute_bracket_error=st.median(vals),max_absolute_bracket_error=max(vals)))
    write_csv(out,'bracket_error_summary.csv',error_summary)
    margin_summary=[]
    for model in model_names:
        rows=[s for s in sweeps if s['model']==model and s['scope']=='FULL-7']
        zero=next((s for s in rows if s['FALSE_FEASIBLE']==0),None)
        margin_summary.append(dict(model=model,minimum_tested_zero_FF_margin=None if zero is None else zero['margin_percent'],
            complete_coverage=all(s['frequencies_with_prediction']==7 for s in rows),
            additional_DVFS_steps_mean=None if zero is None else zero['additional_DVFS_steps_mean'],
            additional_DVFS_steps_max=None if zero is None else zero['additional_DVFS_steps_max'],
            unknown=None if zero is None else zero['unknown'],
            extra_VDD_GPU_W=None,extra_VIN_W=None,
            power_reason='No independent equal-workload/same-placement power pair for the selected demand/frequency pairs'))
    write_csv(out,'minimum_safe_margins.csv',margin_summary)
    small=any(s['model']=='M4' and s['scope']=='FULL-7' and s['margin_percent']<=10 and
        s['frequencies_with_prediction']==7 and s['unknown']==0 and s['no_feasible_prediction']==0 and
        s['FALSE_FEASIBLE']==0 and s['over_provision_steps_mean']<=1 for s in sweeps)
    practical='PRACTICAL_GAP_SMALL' if small else 'PRACTICAL_GAP_REMAINS'
    write_json(out,'gate_verdict.json',dict(PRIMARY=dict(verdict=gate,reason=reason,candidate_points=len(candidates),
        usable_points=len(demands),excluded_points=len(candidates)-len(demands),M4_score=primary_m4),
        SECONDARY=dict(label='POST-HOC SECONDARY ANALYSIS',M4_validity=m4valid,
            sanity_pass=sum(x['passed'] for x in sanity),sanity_total=len(sanity),structural_failures=structural,
            practical_flag=practical,practical_flag_status='UNEVALUABLE_FULL7' if primary_m4['frequencies_with_prediction']<7 else 'EVALUATED',
            note='Missing coverage is not positive model-gap evidence; secondary does not change primary verdict')))
    reports(out,scores,frequency_rows,cases,demand_rows,capacities,error_summary,margin_summary,
            gate,reason,m4valid,sanity,practical,ratios)
    write_csv(out,'raw_replay_verification.csv',REPLAYS)
    write_json(out,'input_provenance.json',INPUTS);write_json(out,'input_schemas.json',SCHEMAS)
    before=json.loads((out/'preservation_before.json').read_text())
    changed=[p for p,h in before.items() if not Path(p).is_file() or sha(p)!=h]
    changed += [p for p,item in INPUTS.items() if sha(p)!=item['sha256']]
    assert sha(out/'M4_SPEC.md')==spec_record['M4_SPEC_SHA256']
    write_json(out,'verification.json',dict(status='FAIL' if changed else 'PASS',protected_files=len(before),
        changed=changed,raw_replays=len(REPLAYS),GPU_executed=False,network_executed=False,
        spec_unchanged=True,analysis_source_sha256=sha(Path(__file__))))
    if changed:raise RuntimeError('Preservation failure')
    print(json.dumps(dict(gate=gate,reason=reason,M4_validity=m4valid,sanity=f"{sum(x['passed'] for x in sanity)}/{len(sanity)}",preservation='PASS'),indent=2))


def reports(out,scores,freqrows,cases,demands,capacities,errors,margins,gate,reason,m4valid,sanity,practical,ratios):
    primary=[s for s in scores if s['model'] in ['M1','M2','M3','M4']]
    selection=[]
    for row in demands:
        if not row['usable_primary']:continue
        d=row['demand_FPS'];entry=dict(demand_FPS=d,actual_MHz=row['actual_minimum_feasible_frequency_MHz'])
        for model in ['M1','M2','M3','M4']:
            r=next(x for x in freqrows if x['model']==model and x['scope']=='FULL-7' and x['demand_FPS']==d)
            entry[model]=r['predicted_MHz'] if r['predicted_MHz'] is not None else r['status']
        selection.append(entry)
    write_csv(out,'frequency_selection_table.csv',selection)
    leakage=[dict(model=m,parameter_sources=src,independent_target=True,target_condition_fitting=False,
        status=status,limitations=limit) for m,src,status,limit in [
        ('M1','ISO_* raw latency C1','INDEPENDENT','Single fixed real tensor; host infer service'),
        ('M2','same ISO_*; fixed C=2','INDEPENDENT','Assumed linear scaling'),
        ('M3','RDVG_B_S01..S09 K6 C2 + ISO_*','INDEPENDENT_PARTIAL','945/1260/1575 direct; 1107/1413 estimated; no630/792'),
        ('M4','M3 + legacy8-stream decode/preprocess profiles + canonical source admission code','INDEPENDENT_PARTIAL_TRANSFER_ASSUMPTIONS',
         'K6 service->K8; unlocked replicated-video frontend->distinct-video co-running pipeline'),
        ('M3/M4 target-trace gap-fill (NOT IMPLEMENTED)','Target capacity service/frontend/queue','LEAKAGE_RISK_EXCLUDED','Would use target outcome as predictor')]]
    leakage[-1].update(independent_target=False,target_condition_fitting=True)
    write_csv(out,'leakage_audit.csv',leakage)
    ff=[x for x in cases if x['scope']=='FULL-7' and x['model'] in ['M1','M2','M3','M4'] and x['decision']=='FALSE_FEASIBLE']
    attribution=[]
    for x in cases:
        if x['decision'] not in ['FALSE_FEASIBLE','FALSE_INFEASIBLE'] or x['scope']!='FULL-7':continue
        attribution.append(dict(model=x['model'],frequency_MHz=x['frequency_MHz'],demand_FPS=x['demand_FPS'],decision=x['decision'],
            synchronized_burst='8 equal due times; source-code mechanism, not isolated causal attribution',
            frontend='NORMAL for all endpoint repeats; cannot attribute to observed frontend saturation',
            concurrent_slowdown='Independent C2 vs C1 differences; K6-to-K8 transfer unresolved',
            queue_accumulation='Positive g_B in observed unstable endpoints' if not x['observed_stable'] else 'No sustained divergence at stable endpoint',
            protection='PROTECTION_LIMITED observed' if any(x['OC3']) else 'No OC3 in endpoint repeats',
            causal_classification='UNRESOLVED; multiple mechanisms possible',g_B=x['g_B'],OC3=x['OC3']))
    write_csv(out,'mismatch_attribution.csv',attribution)
    lines=['# Gate 0 — Profile-Derived Feasibility Model Ladder','',gate,'',reason,'',
      'Primary counts use14 confirmed endpoint conditions; each contains3VALID repeats. Frequency scores use12 retained historical demands;13th candidate208 is excluded (no confirmed feasible anchor). '
      'Minimum refers to the seven tested anchors under downward-closed load-bracket assumptions, not the141-state physical grid. One physical step=9MHz. '
      '315/477 are excluded FRONTEND_CONTAMINATED diagnostics;1575 remains PROTECTION_LIMITED.', '',
      table(primary,['model','scope','frequencies_with_prediction','exact_matches','N','mismatches','unknown','over_provision','under_provision','FALSE_FEASIBLE','FALSE_INFEASIBLE','confusion_conditions','absolute_DVFS_step_error_mean']), '',
      'DIRECT-ONLY uses a restricted945/1260/1575 domain; its matches are not seven-anchor matches. FULL-7 missing predictions stay UNKNOWN, not failures or successes.', '',
      table(selection,['demand_FPS','actual_MHz','M1','M2','M3','M4']), '', '## False-feasible cases', '',
      table(ff,['model','frequency_MHz','demand_FPS','g_B','active_end_backlog','completed_FPS','queue_wait_p95_ms','frontend','OC3']), '',
      '## Leakage audit', '',table(leakage,['model','parameter_sources','independent_target','target_condition_fitting','status','limitations']), '',
      '## Mismatch interpretation and next step','',
      'M2 assumes independence despite measured C2 service slowdown. Synchronized source bursts and actual queue accumulation are visible, '
      'but no mismatch is assigned uniquely to CPU/GPU/memory/protection. Clean endpoint frontend status rules out claiming observed frontend contamination there. '
      'OC3 accompanies1575 evidence; it is neither invalidity nor proof of causation.', '',
      'GATE0_INCONCLUSIVE does not authorize KILL or advancement to D100 Gate2. First resolve independent630/792 C2 profile coverage and '
      'the frontend transfer assumption in a separately authorized step; no new experiment is run here.', '',
      '## SECONDARY','', 'See SECONDARY.md — POST-HOC SECONDARY ANALYSIS. No secondary metric changes the frozen primary gate.']
    with (out/'gate_verdict.md').open('x') as f:f.write('\n'.join(lines)+'\n')
    secondary=['# SECONDARY','', '**POST-HOC SECONDARY ANALYSIS**. Earlier M1/M2 outcomes and supplied ground truth were known. '
      'M4_SPEC was frozen before this task\'s first M4 comparison; no post-comparison model changes.', '',
      '## 8.1 Frozen M4 / sanity','',f'{m4valid}; sanity {sum(x["passed"] for x in sanity)}/{len(sanity)}. '
      'All integer8-FPS loads sufficiently outside brackets are synthetic model checks, not measured new conditions. '
      'No valid full-seven-frequency M4 claim; missing coverage and transfer assumptions remain.', '',
      '## 8.2 Independent T_conc','', 'Direct945/1260/1575 only. Interpolated1107/1413;630/792 N/A. '
      'Primary slowdown interpolation and power-law sensitivity are kept separate in model_capacity_predictions.csv/model_scores.csv. '
      'Three-point power-law fit has no held-out validation. C-robustness strata are diagnostic only.', '',
      table(capacities,['model','frequency_MHz','mu_hat_FPS','provenance']), '',
      '## 8.3 Bracket error','', 'Positive=overestimate; negative=underestimate. Half-open upper-end equality has zero distance but is outside bracket.', '',
      table(errors,['model','frequencies','mean_absolute_bracket_error','median_absolute_bracket_error','max_absolute_bracket_error']), '',
      '## 8.4 Ratios','', 'Observed stable/frequency and unstable/frequency values are in ratio_curves.csv; figures have default colors. '
      'No causal interpretation or fitted empirical capacity curve.', '',
      '## 8.5 Safety margins','',table(margins,['model','minimum_tested_zero_FF_margin','complete_coverage','additional_DVFS_steps_mean','additional_DVFS_steps_max','unknown']), '',
      practical+' — FULL7 UNEVALUABLE for M4; failure to establish SMALL from missing coverage is not positive evidence of a practical model gap. '
      'Full margin counts are in safety_margin_sweep.csv. Missing power consequences remain N/A; no mismatched rail or unequal-service power subtraction.', '',
      '## 8.6 Demand evidence','',table(demands,['demand_FPS','actual_tested_frequencies','actual_minimum_feasible_frequency_MHz','usable_primary','status']), '',
      '13 historical candidates /12 usable /1 excluded(208). No interior-bracket decisions in the retained integer8-FPS demand set. '
      'Some minima are bracket-implied, not directly measured at the exact demand; source run IDs and direct flags are in demand_points.csv.']
    ratio_shapes=[]
    def shape(vals):
        delta=np.diff(vals)
        if np.all(delta==0):return 'constant'
        if np.all(delta>=0) or np.all(delta<=0):return 'monotonic'
        return 'non-monotonic'
    for key in ['stable_FPS_per_MHz','next_unstable_FPS_per_MHz']:
        rr=[x for x in ratios if x['model']=='M1'];ratio_shapes.append(f'{key}: {shape([x[key] for x in rr])}')
    for model in ['M1','M2','M3','M4']:
        rr=[x['stable_over_mu'] for x in ratios if x['model']==model and x['stable_over_mu'] is not None]
        ratio_shapes.append(f'{model} stable/mu: {shape(rr)} on available frequencies; no extrapolation')
    secondary += ['', 'Ratio shapes: '+'; '.join(ratio_shapes)+'.']
    with (out/'SECONDARY.md').open('x') as f:f.write('\n'.join(secondary)+'\n')
    with (out/'INPUT_INVENTORY.md').open('x') as f:
        f.write('# Independent input inventory\n\n'+table(leakage,['model','parameter_sources','status','limitations'])+'\n\n'
        'Repository inventory: c_robustness C2 frequencies1260/1575 (K6r30,K7r27/r30); rate-DVFS K6C2 sanity945/1260/1575. '
        'Other concurrency/trtexec/in-flight data are unlocked-clock; no anchor relabeling. Prior inventory is '
        'results/capacity_model_validity/INPUT_INVENTORY.md. Isolated raw21 and independent concurrent raw18 are replayed. '
        'Frontend component costs cannot be split into pure decode and resize from available wall profiles. '
        'input_provenance.json contains every actual input hash and role; preservation_before.json covers existing artifacts.\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rr=[x for x in ratios if x['model']=='M1']
    fig,ax=plt.subplots()
    for key,label in [('stable_FPS_per_MHz','Confirmed stable'),('next_unstable_FPS_per_MHz','Confirmed unstable')]:
        ax.plot([x['frequency_MHz'] for x in rr],[x[key] for x in rr],marker='o',label=label)
    ax.set(xlabel='GPU frequency (MHz)',ylabel='Inference load / frequency (frames/s/MHz)',title='SECONDARY: observed endpoint ratios')
    ax.legend();fig.tight_layout();fig.savefig(out/'ratio_load_per_frequency.png',dpi=180);fig.savefig(out/'ratio_load_per_frequency.pdf');plt.close(fig)
    fig,ax=plt.subplots()
    for model in ['M1','M2','M3','M4']:
        rr=[x for x in ratios if x['model']==model]
        ax.plot([x['frequency_MHz'] for x in rr],[np.nan if x['stable_over_mu'] is None else x['stable_over_mu'] for x in rr],marker='o',label=model)
    ax.set(xlabel='GPU frequency (MHz)',ylabel='Confirmed stable load / predicted capacity',title='SECONDARY: profile-model ratios')
    ax.legend();fig.tight_layout();fig.savefig(out/'ratio_stable_over_model.png',dpi=180);fig.savefig(out/'ratio_stable_over_model.pdf');plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'results/gate0_model_ladder')
    main(parser.parse_args().output)
