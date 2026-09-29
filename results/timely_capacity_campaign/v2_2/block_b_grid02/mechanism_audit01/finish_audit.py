"""Finish the Grid02 trace audit offline. No runtime or network imports."""
import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from run_audit import OUT, GRID, read_json, median, mean, percentile


def rows(path):
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def write(name, records):
    with (OUT/name).open('w', newline='') as stream:
        if records:
            columns = list(dict.fromkeys(k for record in records for k in record))
            writer = csv.DictWriter(stream, columns)
            writer.writeheader()
            writer.writerows(records)


def write_json(name, value):
    with (OUT/name).open('w') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def numeric(record, name):
    value = record.get(name)
    return None if value in ('', None) else float(value)


def code(record):
    return record['condition']+record['round']


def hash_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_full_masks(plan, masks):
    checks=[]
    for condition in plan['order']:
        if condition['seconds']!=60:
            continue
        run_id=condition['run_id']
        label='L'+str(condition['target_service_FPS'])+('A' if condition['admission_pattern']=='ALIGNED' else 'S')
        path=GRID/run_id/'per_frame.csv.gz'
        manifest=read_json(GRID/run_id/'manifest.json')
        start=manifest['active_start_ns']
        boundaries={start+n*10**9//30 for n in range(1801)}
        actual=0
        departure_boundary_ties=0
        edge_response_completion_stamp_mismatch=0
        with gzip.open(path,'rt',newline='') as stream:
            for row in csv.DictReader(stream):
                if row['phase']!='active':
                    continue
                stream_id=int(row['stream_id']); slot=int(row['frame_id'])
                expected='LOCAL' if masks[label]['local_masks'][stream_id][slot%30] else 'EDGE'
                if row['placement']!=expected:
                    raise RuntimeError(f'Mask mismatch {run_id} stream={stream_id} slot={slot}')
                if row['placement']=='LOCAL':
                    departure=row['inference_start_timestamp_ns'] if row['terminal_state']=='COMPLETED' else row['expired_drop_ns']
                    if departure not in ('',None) and int(departure) in boundaries:
                        departure_boundary_ties+=1
                elif row['response_completion_ns'] not in ('',None) and row['completion_timestamp_ns'] not in ('',None):
                    if row['response_completion_ns']!=row['completion_timestamp_ns']:
                        edge_response_completion_stamp_mismatch+=1
                actual+=1
        if actual!=14400:
            raise RuntimeError(f'Incomplete mask validation {run_id}: {actual}')
        if edge_response_completion_stamp_mismatch:
            raise RuntimeError(f'Edge response/completion stamps differ in {run_id}')
        checks.append({'run_id':run_id,'condition':label,'active_frames_checked':actual,
            'departure_exactly_on_slot_boundary_count':departure_boundary_ties,
            'edge_response_completion_stamp_mismatch_count':edge_response_completion_stamp_mismatch,
            'full_60s_mask_match':'PASS'})
    if len(checks)!=30:
        raise RuntimeError('Expected exactly 30 full-mask checks')
    return checks


def relation(windows):
    groups=defaultdict(list)
    for row in windows:
        condition=row['condition']
        if condition=='L208S':
            condition+='_'+('BAD' if int(row['round']) in (2,3) else 'GOOD')
        groups[condition].append(row)
    output=[]
    ys=('Local_service_mean_ms','Local_service_p95_ms',
        'GPU_stream_span_mean_ms','GPU_stream_span_p95_ms',
        'host_residual_mean_ms','host_residual_p95_ms')
    bins=(('LT_1_5',lambda x:x<1.5),('1_5_TO_1_9',lambda x:1.5<=x<1.9),
          ('GE_1_9',lambda x:x>=1.9))
    for group, data in sorted(groups.items()):
        for field in ys:
            pairs=[(numeric(r,'active_concurrency_mean'),numeric(r,field)) for r in data]
            pairs=[(x,y) for x,y in pairs if x is not None and y is not None]
            x=[q[0] for q in pairs];y=[q[1] for q in pairs]
            pearson=float(np.corrcoef(x,y)[0,1]) if len(set(x))>1 and len(set(y))>1 else None
            spearman=float(spearmanr(x,y).statistic) if len(set(x))>1 and len(set(y))>1 else None
            for bin_name,predicate in bins:
                values=[v for c,v in pairs if predicate(c)]
                output.append({'group':group,'metric':field,'n_window_pairs':len(pairs),
                    'pearson_r':pearson,'spearman_rho':spearman,
                    'concurrency_bin':bin_name,'bin_n':len(values),
                    'bin_mean':mean(values),'bin_median':median(values)})
    return output


def main():
    plan=read_json(GRID/'plan.json')
    masks=read_json(GRID/'BLOCK_B_MASK_MANIFEST.json')
    validation=validate_full_masks(plan,masks)
    write('full_mask_fidelity.csv',validation)
    windows=rows(OUT/'per_window_local_dynamics.csv')
    recoveries=rows(OUT/'backlog_recovery_summary.csv')
    services=rows(OUT/'state_dependent_local_service.csv')
    structure=rows(OUT/'slot_arrival_structure.csv')
    original=rows(GRID/'analysis01/per_run.csv')
    old={r['run_id']:r for r in original}
    server={r['run_id']:r for r in rows(GRID/'analysis01/server_metrics.csv')}
    rec={r['run_id']:r for r in recoveries}
    systems=rows(OUT/'hardware_confound_audit.csv')
    system={r['run_id']:r for r in systems}
    by_run=defaultdict(list)
    for row in windows: by_run[row['run_id']].append(row)
    if len(original)!=30 or len(by_run)!=30:
        raise RuntimeError('Unexpected run count')

    # First HIGH transition is the first classified one-second window. A
    # transition before second zero cannot be inferred from this active trace.
    transitions=[]
    for number in (2,3):
        rid=f'BLOCKB02_L208_S{number}'
        data=by_run[rid]
        first=next((int(r['window_second']) for r in data if r['state']=='HIGH'),None)
        if first is None:
            continue
        for row in data[max(0,first-3):first+1]:
            transitions.append({**row,'first_HIGH_window_second':first,
                'relative_to_first_HIGH_second':int(row['window_second'])-first,
                'pre_transition_window_count_observable':min(3,first),
                'first_persistent_carryover_slot':rec[rid]['first_persistent_carryover_slot'],
                'first_persistent_carryover_seconds':rec[rid]['first_persistent_carryover_seconds']})
    write('l208s_transition_windows.csv',transitions)

    comparison=[]
    for i in range(1,6):
        rid=f'BLOCKB02_L208_S{i}'
        data=by_run[rid]; r=rec[rid]; oldrow=old[rid];sys=system[rid]
        comparison.append({'run_id':rid,'round':i,'observed_group':'BAD' if i in (2,3) else 'GOOD',
            'frozen_60s_mask_match':'PASS','same_frozen_mask_as_other_L208S_runs':'PASS',
            'total_timely_FPS':oldrow['total_timely_FPS'],
            'Local_timely_FPS':oldrow['Local_timely_FPS'],
            'Edge_timely_FPS':oldrow['Edge_timely_FPS'],
            'Edge_assigned_TIR':oldrow['Edge_assigned_TIR'],
            'Local_active_raw_completed_FPS':sum(int(q['Local_raw_completions']) for q in data)/60,
            'Local_expired_cohort':r['Local_expired_or_pruned_cohort'],
            'HIGH_windows':r['HIGH_window_count'],
            'first_HIGH_window_second':next((int(q['window_second']) for q in data if q['state']=='HIGH'),None),
            'first_persistent_slot':r['first_persistent_carryover_slot'],
            'longest_continuous_B_Q_positive_slots':r['longest_continuous_B_Q_positive_slots'],
            'queue_recoveries':r['queue_recoveries'],
            'fraction_slots_B_Q_positive':r['fraction_slots_B_Q_positive'],
            'B_Q_mean_all_slots':mean([float(q['B_Q_mean']) for q in data]),
            'first_second_B_Q_mean':data[0]['B_Q_mean'],
            'first_second_queue_p95_ms':data[0]['Local_queue_wait_p95_ms'],
            'first_second_service_mean_ms':data[0]['Local_service_mean_ms'],
            'first_second_GPU_span_mean_ms':data[0]['GPU_stream_span_mean_ms'],
            'first_second_host_residual_mean_ms':data[0]['host_residual_mean_ms'],
            'first_second_active_concurrency_mean':data[0]['active_concurrency_mean'],
            'run_service_mean_ms':sys['service_mean_ms'],
            'run_GPU_span_mean_ms':sys['GPU_span_mean_ms'],
            'run_host_residual_mean_ms':sys['host_residual_mean_ms'],
            'run_active_concurrency_mean':oldrow['active_concurrency_mean'],
            'run_temperature_mean_C':sys['temperature_mean_C'],
            'run_OC3_delta':sys['OC3_delta'],
            'run_GPU_non_target_fraction':sys['actual_GPU_frequency_non_target_fraction'],
            'run_network_transmitted_rate_Mbps':oldrow['observed_transmitted_data_rate_Mbps'],
            'run_Edge_offload_wait_p95_ms':oldrow['Edge_offload_wait_p95_ms'],
            'run_Edge_request_response_p95_ms':oldrow['Edge_request_response_p95_ms']})
    write('l208s_good_bad_comparison.csv',comparison)
    write('concurrency_service_relation.csv',relation(windows))

    hw=[];edge=[]
    for rid,r in system.items():
        prior=old[rid]; condition=r['condition']
        group='BAD' if condition=='L208S' and int(r['round']) in (2,3) else 'GOOD' if condition=='L208S' else ''
        hw.append({**r,'L208S_group':group,
            'CPU_2601000_residency_fraction_min':prior['CPU_2601000_residency_fraction_min'],
            'CPU_2601000_residency_fraction_mean':prior['CPU_2601000_residency_fraction_mean'],
            'GPU_frequency_restore_ok':prior['frequency_restore_ok'],
            'window_temperature_trajectory_C':json.dumps([numeric(q,'temperature_mean_C') for q in by_run[rid]]),
            'window_OC3_delta':json.dumps([numeric(q,'OC3_sample_delta') for q in by_run[rid]]),
            'window_GPU_non_target_fraction':json.dumps([numeric(q,'actual_GPU_frequency_non_target_fraction') for q in by_run[rid]])})
        edge.append({'run_id':rid,'condition':condition,'round':r['round'],'L208S_group':group,
            'Edge_integrity_status':r['Edge_integrity_status'],'Edge_errors':r['Edge_errors'],
            'Edge_expired':r['Edge_expired'],'Edge_drops':r['Edge_drops'],
            'Edge_duplicates':r['Edge_duplicates'],
            'Edge_TIR':prior['Edge_assigned_TIR'],'Edge_timely_FPS':prior['Edge_timely_FPS'],
            'Edge_offload_wait_p95_ms':prior['Edge_offload_wait_p95_ms'],
            'Edge_request_response_p95_ms':prior['Edge_request_response_p95_ms'],
            'Edge_pending_active_mean':prior['Edge_pending_active_mean'],
            'Edge_pending_peak':prior['Edge_pending_peak'],
            'network_TX_bytes_delta':prior['network_TX_bytes_delta'],
            'observed_transmitted_data_rate_Mbps':prior['observed_transmitted_data_rate_Mbps'],
            'WiFi_BSSID_start':prior['wifi_BSSID_start'],'WiFi_BSSID_end':prior['wifi_BSSID_end'],
            'WiFi_signal_start_dBm':prior['wifi_signal_start_dBm'],
            'WiFi_signal_end_dBm':prior['wifi_signal_end_dBm'],
            'edge_path_error_count':prior['edge_path_error_count'],
            'server_queue_wait_p95_ms':server[rid]['queue_wait_p95_ms'],
            'server_inference_p95_ms':server[rid]['inference_p95_ms'],
            'server_max_queue':server[rid]['max_queue']})
    write('hardware_confound_audit.csv',hw)
    write('edge_network_confound_audit.csv',edge)

    high=[r for r in services if r['state']=='HIGH']
    eligible=[r for r in high if int(r['n_windows'])>=5]
    excluded=[{'run_id':r['run_id'],'condition':r['condition'],
        'HIGH_window_count':int(r['n_windows']),'excluded_reason':'HIGH_WINDOWS_LT_5'}
        for r in high if int(r['n_windows'])<5]
    lower=min(float(r['mu_high_run']) for r in eligible) if eligible else None
    sources=[r['run_id'] for r in eligible if float(r['mu_high_run'])==lower] if lower is not None else []
    for r in services:
        r['mu_backlog_lower_FPS']=lower
        r['mu_backlog_lower_per_slot']=lower/30 if lower is not None else None
        r['lambda_less_than_mu_backlog_lower']=(float(r['lambda_L_FPS'])<lower) if lower is not None else None
    write('state_dependent_local_service.csv',services)
    timely_evidence={}
    for label in ('L200A','L200S','L208A','L208S','L216A','L216S'):
        vals=[float(r['TIR_total']) for r in original if 'L'+r['rate_local']+('A' if r['pattern']=='ALIGNED' else 'S')==label]
        timely_evidence[label]={'TIR_total_5_runs':vals,
            'five_of_five_at_least_0_99':len(vals)==5 and all(v>=.99 for v in vals)}
    eligible_rates=[]
    if lower is not None:
        for rate in (200,208,216):
            labels=[f'L{rate}A',f'L{rate}S']
            if rate<lower and any(timely_evidence[label]['five_of_five_at_least_0_99'] for label in labels):
                eligible_rates.append(rate)
    selection={'method':'frozen: min across eligible run medians of HIGH-window Local raw completion FPS',
        'HIGH_window_eligibility_minimum':5,'eligible_run_count':len(eligible),
        'eligible_mu_high_by_run':{r['run_id']:float(r['mu_high_run']) for r in eligible},
        'excluded_runs':excluded,
        'mu_backlog_lower_FPS':lower,'lower_envelope_source_run_ids':sources,
        'bound_name':'conservative empirical backlog-service lower envelope; not a confidence bound',
        'mu_backlog_lower_per_slot':lower/30 if lower is not None else None,
        'tested_lambda_FPS':[200,208,216],
        'tested_lambda_per_slot':{'200':200/30,'208':208/30,'216':216/30},
        'strict_lambda_less_than_bound':{str(rate):rate<lower if lower is not None else None for rate in (200,208,216)},
        'deadline_evidence_rule_for_exploratory_selection':'Grid02 condition has all five TIR_total >= 0.99; a transparent audit convention, not a changed Grid02 verdict',
        'deadline_evidence_by_condition':timely_evidence,
        'eligible_rates_after_both_filters':eligible_rates,
        'confirmation_selection_candidate_FPS':max(eligible_rates) if eligible_rates else None,
        'candidate_status':'CANDIDATE_IDENTIFIED' if eligible_rates else 'INCONCLUSIVE_NO_TESTED_RATE_PASSES_BOTH_FILTERS',
        'selection_evidence_strength':'WEAK' if len(eligible)==1 else 'NONE' if len(eligible)==0 else 'MULTIPLE_ELIGIBLE_RUNS_BUT_CONSERVATIVE_ENVELOPE_LIMITS_SELECTION' if not eligible_rates else 'MULTIPLE_ELIGIBLE_RUNS',
        'L192_selection_excluded':True}
    write_json('confirmation_selection_candidate.json',selection)

    # Retain a machine-readable pointer to every source and fixed analysis rule.
    write_json('audit_provenance.json',{
        'source_grid02_plan_sha256':hash_file(GRID/'plan.json'),
        'source_grid02_analysis01_H1_sha256':hash_file(GRID/'analysis01/H1_summary.json'),
        'source_mask_manifest_sha256':hash_file(GRID/'BLOCK_B_MASK_MANIFEST.json'),
        'measured_runs':30,'full_mask_checks':'PASS','full_mask_frames_checked':sum(r['active_frames_checked'] for r in validation),
        'Local_departure_exactly_on_slot_boundary_count':sum(r['departure_exactly_on_slot_boundary_count'] for r in validation),
        'H1_verdict_unchanged':'H1_NOT_SUPPORTED','new_workload_executed':False})
    print('finish outputs written', flush=True)


if __name__=='__main__':
    main()
