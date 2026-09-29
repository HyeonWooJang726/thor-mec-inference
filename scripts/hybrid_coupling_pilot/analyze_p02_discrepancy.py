#!/usr/bin/env python3
"""Read-only P02/raw replay and historical Hybrid-smoke comparison.

Only writes to a new --output directory. Imports CPU-only frozen helpers;
never calls a runner, hardware preflight, CUDA, network or frequency control.
"""
import argparse
import ast
from collections import Counter
import csv
import difflib
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys

sys.dont_write_bytecode = True
import analyze_coupling as pilot
import pilot_common as common
import run_coupling_pilot as runner

ROOT = common.ROOT
PLAN = ROOT / 'results/hybrid_coupling_pilot/plan_ab02.json'
HIST = ROOT / 'results/hybrid_capacity_extension/HYBRID_SMOKE01'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, indent=2, allow_nan=False)
        f.write('\n')


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('x', newline='') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)


def flatten(obj, prefix=''):
    out = {}
    for k, v in obj.items():
        key = prefix + k
        if isinstance(v, dict):
            out.update(flatten(v, key + '_'))
        elif not isinstance(v, list):
            out[key] = v
    return out


def compare(replay, stored, field, mismatches, counts):
    if isinstance(replay, dict):
        for k, v in replay.items():
            if k not in stored:
                mismatches.append(dict(field=field+'.'+k, stored='MISSING', replay=v))
            else:
                compare(v, stored[k], field+'.'+k, mismatches, counts)
    elif isinstance(replay, list):
        if not isinstance(stored, list) or len(replay) != len(stored):
            mismatches.append(dict(field=field, stored=stored, replay=replay))
        else:
            for i, (x, y) in enumerate(zip(replay, stored)):
                compare(x, y, field+f'[{i}]', mismatches, counts)
    else:
        counts[0] += 1
        equal = replay == stored
        if isinstance(replay, float) and isinstance(stored, (int, float)):
            equal = math.isclose(replay, stored, rel_tol=1e-12, abs_tol=1e-10)
        if not equal:
            mismatches.append(dict(field=field, stored=stored, replay=replay))


def identity(rows, t0, path=None, schedule=False):
    result = []
    for r in rows:
        if r['phase'] != 'active' or (path and r['placement'] != path):
            continue
        x = [int(r['stream_id']), int(r['frame_id'])]
        if schedule:
            x += [int(r['source_timestamp_ns']), int(r['logical_arrival_ns'])-t0,
                  int(r['admission_timestamp_ns'])-t0, int(r['admitted']), r['placement'],
                  int(r['edge_request_id']) if r['edge_request_id'] else None,
                  int(r['edge_release_target_ns'])-t0 if r['edge_release_target_ns'] else None]
        result.append(x)
    return sorted(result)


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def forensic_run(m, frames, power):
    t0, t1 = m['active_start_ns'], m['active_end_ns']
    active = [r for r in frames if r['phase'] == 'active']
    local = [r for r in active if r['placement'] == 'LOCAL']
    edge = [r for r in active if r['placement'] == 'EDGE']
    warm = [r for r in frames if r['phase'] == 'warmup']
    v = pilot.h.val
    phases = {x['phase']: x['monotonic_ns'] for x in m['lifecycle_events']}
    resources = m['resources']
    backend = {k: v for k, v in m['edge_ready'].get('backend', {}).items()
               if k not in ('resources', 'gpu_before')}
    env = m['environment_before']
    policies = {k: v for k, v in env['clock_sysfs'].items() if not k.endswith('cur_freq')}
    cpus, cpu_clocks, memory = [], [], []
    samples = [r for r in power if t0 <= int(r['timestamp_ns']) < t1]
    for r in samples:
        raw = r.get('raw_tegrastats', '')
        match = re.search(r'CPU \[([^]]+)\]', raw)
        if match:
            pairs = re.findall(r'(\d+)%@(\d+)', match[1])
            if pairs:
                cpus.append(sum(int(x) for x, _ in pairs)/100)
                cpu_clocks.extend(int(y) for _, y in pairs)
        match = re.search(r'RAM (\d+)/', raw)
        if match:
            memory.append(int(match[1]))
    trace = []
    for sec in range(11):
        time_ns = t0 + sec * 10**9
        cell = dict(t_seconds=sec)
        for name, rr in [('L', local), ('E', edge), ('H', local+edge)]:
            cell[name] = sum(v(r, 'logical_arrival_ns') < time_ns for r in rr) - sum(
                v(r, 'completion_timestamp_ns') < time_ns for r in rr)
        trace.append(cell)
    fully_active = [r for r in local if t0 <= v(r, 'inference_start_timestamp_ns') and
                    v(r, 'completion_timestamp_ns') < t1]
    return dict(
        source_identity_sha256=fingerprint(identity(frames, t0)),
        local_identity_sha256=fingerprint(identity(frames, t0, 'LOCAL')),
        schedule_sha256=fingerprint(identity(frames, t0, schedule=True)),
        edge_pixels_sha256=fingerprint(sorted((int(r['stream_id']), int(r['frame_id']),
                                              r['payload_sha256']) for r in edge)),
        active_seconds=(t1-t0)/1e9, slope_window_seconds=[5, 10],
        child_start_time=m['child_start_time'], active_start_monotonic_ns=t0,
        local_warmup_per_worker=dict(Counter(r['worker_id'] for r in warm)),
        warmup_input=m['warmup_input'], edge_warmup=m['edge_ready'].get('warmup_inferences'),
        warmup_last_completion_to_t0_ms=(t0-max(v(r, 'completion_timestamp_ns') for r in warm))/1e6,
        active_checkpoint_to_t0_ms=(t0-phases['active_started'])/1e6,
        drain_completion_after_t1_ms=(phases['drain_completed']-t1)/1e6,
        premeasurement_queue_empty=m['premeasurement_queue_empty'],
        ready_queue_accounting=m['ready_queue_accounting'],
        distinct_contexts=len({r['context_object_id'] for r in resources}),
        distinct_cuda_streams=len({r['cuda_stream_pointer'] for r in resources}),
        worker_buffer_bytes=[r['buffer_bytes'] for r in resources],
        local_engine=m['engine_provenance'], local_TensorRT=m['TensorRT_version'],
        edge_backend=backend, edge_final=m['edge_final'],
        frequency_restore_ok=m['frequency_restore_ok'], restored_range_Hz=m['restored_range_Hz'],
        active_frequency_readbacks=sorted({float(r['actual_gpu_freq_MHz']) for r in samples}),
        active_pinned_ranges=sorted({(r['min_freq_Hz'], r['max_freq_Hz']) for r in samples}),
        recorded_system_configuration=dict(nvpmodel=env['nvpmodel'], uname=env['uname'],
                                           clock_policies=policies, git_commit=env['git_commit']),
        preactive_dynamic_clock_snapshot={k: v for k, v in env['clock_sysfs'].items() if k.endswith('cur_freq')},
        cpu_utilized_core_equivalents_sample_mean=statistics.mean(cpus) if cpus else None,
        cpu_clock_MHz_all_core_sample_mean=statistics.mean(cpu_clocks) if cpu_clocks else None,
        ram_used_MB_sample_mean=statistics.mean(memory) if memory else None,
        fully_active_local_service_ms=pilot.h.quantiles([
            (v(r, 'completion_timestamp_ns')-v(r, 'inference_start_timestamp_ns'))/1e6 for r in fully_active]),
        backlog_at_second_boundaries_left_limit=trace,
        lifecycle_phases=[x['phase'] for x in m['lifecycle_events']])


def fmt(v):
    if v is None:
        return 'N/A'
    return f'{v:.4f}' if isinstance(v, float) else str(v)


def table(rows, columns):
    return '\n'.join(['| '+' | '.join(columns)+' |', '| '+' | '.join('---' for _ in columns)+' |'] +
                     ['| '+' | '.join(fmt(r.get(k)) for k in columns)+' |' for r in rows])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=common.OUT/'analysis_ab02')
    args = ap.parse_args()
    if args.output.exists():
        raise RuntimeError('Refusing to overwrite output: '+str(args.output))
    if subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() != 'rate-dvfs-gate':
        raise RuntimeError('Unexpected branch')
    plan = json.loads(PLAN.read_text())
    assert len(plan['order']) == 10 and plan['attempt'] == 'P02'
    directories = [common.OUT/c['run_id'] for c in plan['order']] + [HIST]
    # Every pre-existing artifact in both Hybrid result trees is covered, including P01.
    protected = set()
    for root in (common.OUT, HIST.parent, ROOT/'scripts/hybrid_coupling_pilot', ROOT/'scripts/hybrid_capacity_extension'):
        protected.update(p for p in root.rglob('*') if p.is_file())
    for d in directories:
        m = json.loads((d/'manifest.json').read_text())
        protected.update(ROOT/p for p in m['source_sha256'])
    before = {str(p.relative_to(ROOT)): sha(p) for p in sorted(protected)}
    records, flats, data, mismatches, counts, schemas = [], [], {}, [], [0], {}
    provenance = []
    for i, d in enumerate(directories):
        m = json.loads((d/'manifest.json').read_text())
        stored = json.loads((d/'summary.json').read_text())
        for path, digest in m['source_sha256'].items():
            if sha(ROOT/path) != digest:
                raise RuntimeError('Historical source hash mismatch: '+path)
        expected_plan = PLAN if i < 10 else HIST.parent/'plan.json'
        if m['execution_manifest_sha256'] != sha(expected_plan):
            raise RuntimeError('Execution plan hash mismatch: '+d.name)
        frames = pilot.read_csv(d/'per_frame.csv.gz')
        power = pilot.read_csv(d/'power_trace.csv.gz')
        s = (pilot.summarize if i < 10 else pilot.h.summarize)(m, frames, power)
        compare(s, stored, d.name, mismatches, counts)
        for k, expected in [('child_returncode', 0), ('PROCESS_LIFECYCLE', 'PASS'),
                            ('frequency_restore_ok', True), ('status_finalized', True)]:
            if m.get(k) != expected or stored.get(k) != expected:
                raise RuntimeError('Final lifecycle failure: '+d.name+' '+k)
            s[k] = m[k]
        if s['integrity_status'] != 'VALID':
            raise RuntimeError('Raw integrity failure: '+d.name+' '+repr(s['errors']))
        if i < 10:
            c = plan['order'][i]
            assert (m['edge_r'], m['pass_name'], m['order_index'], m['repeat']) == (
                c['edge_r'], c['pass'], c['order_index'], c['repeat'])
            s.update(pass_name=c['pass'], order_index=c['order_index'], edge_r=c['edge_r'])
        schemas[d.name] = dict(per_frame=list(frames[0]), power=list(power[0]))
        records.append(s)
        flats.append(flatten(s))
        data[d.name] = (m, frames, power)
        provenance.append(dict(run_id=d.name, source_files_verified=len(m['source_sha256']),
                               execution_plan=str(expected_plan.relative_to(ROOT)), plan_sha256=sha(expected_plan)))
    if mismatches:
        print(json.dumps(mismatches, indent=2))
        raise RuntimeError('Raw replay mismatch; stopping before interpretation')
    pairs = []
    numeric = [k for k in flats[0] if any(pilot.finite(r.get(k)) for r in flats[:10])]
    for rate in (0, 8, 16, 24, 40):
        a, b = [next(r for r in flats[:10] if r['edge_assigned_FPS'] == rate and r['pass_name'] == p)
                for p in ('A', 'B')]
        for metric in numeric:
            x, y = a.get(metric), b.get(metric)
            values = [v for v in (x, y) if pilot.finite(v)]
            pairs.append(dict(edge_FPS=rate, metric=metric, A_run=a['run_id'], B_run=b['run_id'],
                              A_integrity='VALID', B_integrity='VALID', A_value=x, B_value=y,
                              A_stability=a['queue_classification'], B_stability=b['queue_classification'],
                              A_supply=a['supply_status'], B_supply=b['supply_status'],
                              B_minus_A=y-x if len(values)==2 else None, valid_n=len(values),
                              mean=statistics.mean(values) if values else None,
                              sample_SD=statistics.stdev(values) if len(values)==2 else None))
    # Empty Edge latency groups at E=0 must still appear as N/A, not disappear.
    for metric in pilot.METRICS + ['edge_server_queue_ms_'+q for q in ('mean', 'p50', 'p95', 'p99')]:
        if metric not in numeric:
            raise RuntimeError('Required metric missing from export: '+metric)
    ids = ['HYBRID_SMOKE01', 'COUPLING_AB_A_E40_P02', 'COUPLING_AB_B_E40_P02']
    forensic = {rid: forensic_run(*data[rid]) for rid in ids}
    local_ids = {rid: fingerprint(identity(frames, m['active_start_ns'], 'LOCAL'))
                 for rid, (m, frames, _) in data.items()}
    old = forensic[ids[0]]
    same = {key: all(forensic[rid][key] == old[key] for rid in ids[1:]) for key in (
        'source_identity_sha256', 'local_identity_sha256', 'schedule_sha256', 'edge_pixels_sha256',
        'active_seconds', 'slope_window_seconds', 'local_warmup_per_worker', 'warmup_input',
        'edge_warmup', 'premeasurement_queue_empty', 'worker_buffer_bytes', 'local_engine',
        'local_TensorRT', 'edge_backend', 'recorded_system_configuration', 'lifecycle_phases')}
    same['all_P02_Local_frame_IDs_equal_to_smoke'] = len(set(local_ids.values())) == 1
    same['all_P02_source_provenance_equal_to_smoke'] = all(
        m['inputs'] == data['HYBRID_SMOKE01'][0]['inputs'] for m, _, _ in data.values())
    old_src, new_src = common.hybrid.adapted_source(), runner.adapted_source()
    def functions(src):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef)}
    old_funcs, new_funcs = functions(old_src), functions(new_src)
    unchanged = [k for k in old_funcs.keys() & new_funcs.keys() if old_funcs[k] == new_funcs[k]]
    source_diff = ''.join(difflib.unified_diff(old_src.splitlines(True), new_src.splitlines(True),
                                             fromfile='Hybrid adapter', tofile='P02 pilot adapter'))
    forensic_output = dict(runs=forensic, equality_checks=same, local_frame_identity_by_run=local_ids,
        unchanged_nested_functions=sorted(unchanged), adapted_run_one_source_diff=source_diff,
        limitations=['Local tensors are not hashed per frame; matching Edge pixel hashes do not prove Local tensor identity independently of source reuse.',
                     'Local service timestamps measure host inference-service intervals, not GPU kernel-only durations.',
                     'Edge returned metadata and durations are available; independent Edge process history is not inferred.',
                     'Background processes, thread scheduling, protection duration and full active CPU/EMC policy history were not recorded.',
                     'No cross-host timestamp subtraction is used.'])
    comparison = [next(r for r in flats if r['run_id'] == rid) for rid in ids]
    # Report is specific to this immutable input cohort; no fitted causal decision rule.
    nonmonotonic = {}
    for p in ('A', 'B'):
        ordered = sorted([r for r in flats[:10] if r['pass_name']==p], key=lambda r:r['edge_r'])
        nonmonotonic[p] = dict(
            completion_increases_at_some_rate_steps=any(y['local_completed_FPS'] > x['local_completed_FPS'] for x,y in zip(ordered,ordered[1:])),
            service_decreases_at_some_rate_steps=any(y['local_service_ms_mean'] < x['local_service_ms_mean'] for x,y in zip(ordered,ordered[1:])))
    assert all(all(x.values()) for x in nonmonotonic.values())
    assert all(same.values()), 'Workload/runtime equality differs; reassess interpretation'
    verdict = 'COUPLING_NOT_SUPPORTED_BY_PILOT'
    stable_n = sum(r['queue_stable'] for r in flats[:10])
    report = [
        '# P02 coupling pilot and historical Hybrid smoke', '',
        '**'+verdict+'**', '',
        f'Raw replay: 10/10 P02 VALID and HYBRID_SMOKE01 VALID; {counts[0]} stored scalar values checked, no mismatch. '
        f'P02 global stability: {stable_n}/10 under the frozen criterion. P01 permission failures remain excluded and preserved.', '',
        'Local completion/service do not worsen systematically with Edge rate in both passes. '
        'This pilot does not establish absence of coupling. A/B differences and the historical smoke discrepancy remain unresolved; '
        'no CPU/memory/network/GPU mechanism is assigned. No new significance or similarity threshold is used.', '',
        '## Definitions and populations', '',
        'All active intervals are 10 s; continuous-time OLS uses [5,10] s. B_L/B_E count logically assigned minus completed '
        '(returned on Edge), and B_H=B_L+B_E. Drain is excluded from slope. '
        'Frozen STABLE requires VALID, g_B_H<=0.5 frame/s, no drop/cap saturation and full drain. '
        'Latency quantiles use all active-logical assigned requests, including those completed during drain. '
        'Concurrency is active-clipped host service overlap, not demonstrated kernel overlap. '
        'VDD_GPU uses frozen time-integrated mean; VDD_CPU_SOC_MSS is an arithmetic active telemetry sample mean. '
        'Temperature is the recorded GPU temperature sample mean. E=0 Edge latencies are N/A, not zero.', '',
        'Full precision is in per_run_metrics.csv and rate_repeat_summary.csv. Sample SD is across two run-level metrics '
        '(ddof=1); mean p95 is the mean of the two run p95 values, not a pooled-frame percentile. '
        'Decode/resize remains 240 FPS at every rate; payload_ready counts admitted branches, so it is 200+E FPS.', '',
        '## A/B raw replay', '',
        table(flats[:10], ['run_id','local_assigned_FPS','edge_assigned_FPS','local_completed_FPS','edge_completed_FPS',
                           'aggregate_completed_fps','g_B_L','g_B_E','g_B_H','queue_classification']), '',
        '## Direct E40 versus historical smoke', '',
        table(comparison, ['run_id','local_completed_FPS','edge_completed_FPS','aggregate_completed_fps','g_B_L','g_B_E',
                           'local_service_ms_mean','local_queue_ms_mean','active_concurrency_mean',
                           'backlogs_L_active_end_backlog','backlogs_E_active_end_backlog','backlog_after_drain',
                           'avg_power_W','available_rail_power_W_diagnostic_VDD_CPU_SOC_MSS','temperature','OC3_delta']), '',
        'The severe Local slowdown is present in historical raw, not a stored-summary error. '
        'Both P02 E40 runs have shorter Local host service intervals and much smaller queues with similar near-two '
        'active concurrency; frontend delivery is NORMAL. E40 late-window negative slope does not remove its startup backlog '
        'or establish 60-s sustainability. Historical smoke is colder and has lower VDD_GPU, while its OC3 count overlaps P02; '
        'these measurements do not isolate a cause.', '',
        '## Workload and implementation audit', '',
        table([dict(check=k, equal=v) for k,v in same.items()], ['check','equal']), '',
        'All 2,000 Local frame IDs are identical across ten P02 runs and smoke. At E40, all 2,400 source/placement records '
        'match after subtracting Thor t0, including 400 Edge request IDs and 25-ms release offsets. All 400 Edge payload hashes '
        'also match across the three runs. Local payload tensors were not separately hashed. '
        'At lower Edge rates the pilot deliberately thins only complementary Edge slots, retaining decode+resize for SKIP frames.', '',
        'Hybrid and pilot are different launchers, but use the same frozen Local infer worker, TensorRT runtime, '
        'decode/resize and frequency helper. P02 adds an entry-point permission check and plan binding, pilot metadata/analyzer, '
        'an unconditional resize guard, Edge slot selection and HELLO/count adaptation. At E40 all frames are admitted and all '
        '40 Edge slots/s selected, so these guards/placement produce the same work. The full adapted-source diff and unchanged '
        'nested function list are preserved in forensic_comparison.json. No identified harness difference explains the severe slowdown; '
        'the extra decorator bookkeeping is not a measured causal explanation.', '',
        'Both use fresh child Local workers, 30 actual warmup inferences per worker, empty premeasurement queues, '
        'private two-context/two-stream resources, identical engine hash and Local TensorRT version. Edge creates a fresh Backend '
        'per TCP session with 50 warmup inferences; pilot keeps a campaign listener across sessions, whereas historical smoke has '
        'one session. Both use the same formal Backend/serve_session and inherited sender/receiver. The Edge connection/READY '
        'precedes Local initialization and warmup; all 400 requests return with clean drain. No cache replaces live workload.', '',
        'Actual active clock samples are 1575 MHz with target min=max, zero non-target fraction and successful restore in all '
        'three comparisons. Recorded MAXN, governor, CPU policy ranges, NVD/VIC/EMC allowed settings and kernel match. '
        'Dynamic pre-run clock snapshots differ and are recorded, not treated as changed policy. Sessions occurred at different UTC '
        'times and have different monotonic/cumulative OC3 baselines. No preserved boot/background-process history establishes why.', '',
        '## Order, protection and temperature', '',
        'B/E0 is unstable without an Edge connection. B/E16 is unstable with OC3_delta=0. B/E8 returns to high Local completion '
        'despite later order, higher temperature and OC3_delta=5. A/B E40 are similar, but several lower-rate paired observations '
        'differ substantially. Therefore neither an Edge-rate dose response nor an order/temperature/OC3 causal explanation is '
        'established. Descriptive rank associations below must not be read as a fitted explanation or statistical significance.', '',
        pilot.diagnostic_report(flats[:10], pairs), '',
        '## Minimal next formal experiment — proposal only, not executed', '',
        'Use the same P02 harness for E=0 and E=40 only, 60 s each, three paired repeats (six runs), with fixed order '
        '0,40 / 40,0 / 0,40. Freeze this order before execution. Keep identical Local frame IDs, Local 200 FPS, '
        '240-FPS decode+resize, 1575 MHz, C_L=2/C_E=1, RAW640, existing warmup and final-30-s criterion; '
        'E=0 has no connection. Keep every failure and perform no automatic retry. Record actual startup temperature, '
        'OC3 before/after, sampled clocks and host/background-process context without changing policies. '
        'This tests sustained E40 feasibility against an interleaved no-network control; it cannot retroactively identify '
        'the cause of the single historical smoke. If that discrepancy persists, a separately approved matched-harness comparison '
        'would be needed. No experiment, frequency change, deployment or network action was performed in this analysis.', '',
        '## Complete requested metrics: A / B / mean / sample SD', '',
    ]
    requested = ['local_assigned_FPS','edge_assigned_FPS','local_completed_FPS','edge_completed_FPS',
        'aggregate_completed_fps','g_B_L','g_B_E','g_B_H'] + [
        f'backlogs_{p}_{k}' for p in ('L','E','H') for k in ('peak_backlog','active_end_backlog','after_drain_backlog')] + [
        f'{group}_{q}' for group in ('local_service_ms','local_queue_ms','edge_client_pending_ms','edge_send_ms','edge_server_queue_ms')
        for q in ('mean','p50','p95','p99')] + ['active_concurrency_mean','active_concurrency_peak','decode_ready_FPS',
        'resize_ready_FPS','payload_ready_FPS','local_ready_FPS','source_pending_slope','frontend_pending_slope',
        'frontend_ready_deficit_fraction','avg_power_W','available_rail_power_W_diagnostic_VDD_CPU_SOC_MSS',
        'temperature','OC3_before','OC3_after','OC3_delta','actual_freq_mean_MHz','actual_clock_non_target_fraction']
    for rate in (0,8,16,24,40):
        report += [f'### Edge {rate} FPS', '',
                   table([r for r in pairs if r['edge_FPS']==rate and r['metric'] in requested],
                         ['metric','A_value','B_value','mean','sample_SD']), '']
    report += ['All P02 and historical smoke replay have supply_status=NORMAL; all drain-end backlogs are zero. '
               'Status is categorical and not averaged. OC3 counter means/SD are bookkeeping only; interpret within-run deltas.', '']
    after = {p: sha(ROOT/p) for p in before}
    changes = [p for p in before if before[p] != after[p]]
    if changes:
        raise RuntimeError('Existing artifact changed: '+repr(changes))
    args.output.mkdir(parents=True, exist_ok=False)
    write_csv(args.output/'per_run_metrics.csv', flats[:10])
    write_csv(args.output/'rate_repeat_summary.csv', pairs)
    write_csv(args.output/'hybrid_smoke_comparison.csv', comparison)
    save(args.output/'forensic_comparison.json', forensic_output)
    with (args.output/'coupling_verdict.md').open('x') as f:
        f.write('\n'.join(report))
    save(args.output/'verification.json', dict(
        primary_runs=10, historical_comparison_runs=1, excluded_P01=plan['excluded_previous_attempt'],
        replay_scalar_checks=counts[0], replay_mismatches=mismatches, raw_replay='PASS',
        provenance=provenance, schemas=schemas, nonmonotonic_rate_steps=nonmonotonic,
        input_sha256_before=before, input_sha256_after=after, preservation='PASS',
        verdict=verdict, command=f'python3 -B scripts/hybrid_coupling_pilot/analyze_p02_discrepancy.py --output {args.output}',
        no_hardware_or_network_run=True, numeric_comparison_tolerance=dict(relative=1e-12, absolute=1e-10)))
    # Recheck after output creation too; new output files are intentionally outside the protected set.
    assert all(sha(ROOT/p)==digest for p,digest in before.items())
    print(verdict)
    print(f'Raw replay PASS: {counts[0]} scalar checks; 10/10 P02 VALID; {stable_n}/10 STABLE; preservation PASS')
    print(args.output)


if __name__ == '__main__':
    main()
