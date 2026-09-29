"""Offline, read-only Block B Grid02 mechanism audit. Never imports runtime launchers."""
import csv
import gzip
import json
import math
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
GRID = OUT.parent
T = 60
NS = 10**9


def read_csv(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', newline='') as stream:
        return list(csv.DictReader(stream))


def read_json(path):
    return json.loads(Path(path).read_text())


def write_csv(name, rows):
    path = OUT/name
    with path.open('x', newline='') as stream:
        if rows:
            keys = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(stream, keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)


def write_json(name, obj):
    with (OUT/name).open('x') as stream:
        json.dump(obj, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def integer(row, key):
    value = row.get(key)
    return None if value in ('', None) else int(value)


def number(row, key):
    value = row.get(key)
    return None if value in ('', None) else float(value)


def percentile(values, p):
    return float(np.percentile(values, p)) if values else None


def mean(values):
    return float(st.mean(values)) if values else None


def median(values):
    return float(st.median(values)) if values else None


def slope(xs, ys):
    if len(xs) < 2:
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    den = float(np.sum((x-x.mean())**2))
    return float(np.sum((x-x.mean())*(y-y.mean()))/den) if den else None


def index(stamp, start):
    if stamp is None or not start <= stamp < start+T*NS:
        return None
    return (stamp-start)//NS


def interval_bins(intervals, start):
    bins = [[] for _ in range(T)]
    for left, right in intervals:
        if left is None or right is None or left >= right or right <= start or left >= start+T*NS:
            continue
        first = max(0, (left-start)//NS)
        last = min(T-1, (right-1-start)//NS)
        for sec in range(first, last+1):
            a, b = start+sec*NS, start+(sec+1)*NS
            bins[sec].append((max(left,a), min(right,b)))
    return bins


def occupancy(intervals, left, right):
    """Exact time-weighted occupancy mean/p95 and positive-time fraction."""
    events = defaultdict(int)
    for a,b in intervals:
        if a < b:
            events[a] += 1
            events[b] -= 1
    events[left] += 0
    events[right] += 0
    level = 0
    last = left
    durations = defaultdict(int)
    peak = 0
    for stamp in sorted(events):
        if stamp > last:
            durations[level] += stamp-last
        level += events[stamp]
        peak = max(peak,level)
        last = stamp
    if level != 0:
        raise RuntimeError('Clipped interval occupancy is not conserved')
    total = right-left
    ave = sum(level*duration for level,duration in durations.items())/total
    cumul = 0
    p95 = None
    for value,duration in sorted(durations.items()):
        cumul += duration
        if cumul >= .95*total:
            p95 = value
            break
    return ave,p95,peak,1-durations.get(0,0)/total


def circular_runs(bits):
    if not any(bits):
        return []
    if all(bits):
        return [len(bits)]
    zero = bits.index(False)
    shifted = bits[zero+1:]+bits[:zero+1]
    lengths = []
    current = 0
    for bit in shifted:
        if bit:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    return lengths


def positive_runs(values):
    runs = []
    begin = None
    for n, value in enumerate(list(values)+[0]):
        if value > 0 and begin is None:
            begin = n
        elif value == 0 and begin is not None:
            runs.append((begin,n))
            begin = None
    return runs


def slot_structure(label, mask):
    local = mask['m_L']
    edge = mask['m_E']
    busy_l = circular_runs([n > 0 for n in local])
    gap_l = circular_runs([n == 0 for n in local])
    busy_e = circular_runs([n > 0 for n in edge])
    return dict(condition=label, m_L=json.dumps(local), m_E=json.dumps(edge),
        mean_m_L=mean(local),max_m_L=max(local),variance_m_L=float(np.var(local)),
        mean_m_E=mean(edge),max_m_E=max(edge),variance_m_E=float(np.var(edge)),
        zero_Local_arrival_slot_fraction=sum(n==0 for n in local)/30,
        zero_Edge_arrival_slot_fraction=sum(n==0 for n in edge)/30,
        consecutive_Local_busy_slots=json.dumps(busy_l),
        Local_busy_run_max=max(busy_l) if busy_l else 0,
        Local_recovery_gap_slots=json.dumps(gap_l),
        consecutive_Edge_busy_slots=json.dumps(busy_e),
        Edge_busy_run_max=max(busy_e) if busy_e else 0,
        cyclic_period_slots=30)


def compute_run(condition, frozen_mask):
    rid = condition['run_id']
    path = GRID/rid
    manifest = read_json(path/'manifest.json')
    summary = read_json(path/'summary.json')
    edge_final = read_json(path/'edge_final.json')
    before_cpu = read_json(path/'CPU_BEFORE_RUN.json')
    after_cpu = read_json(path/'CPU_AFTER_RUN.json')
    if not (summary['integrity_status']=='VALID' and summary['terminal_accounting_status']=='PASS' and
            summary['true_unfinished_after_drain']==0 and manifest.get('frequency_restore_ok') is True and
            edge_final['integrity_status']=='VALID' and before_cpu['status']==after_cpu['status']=='PASS'):
        raise RuntimeError('Frozen run integrity failed: '+rid)
    t0, t1 = manifest['active_start_ns'],manifest['active_end_ns']
    if t1-t0 != T*NS:
        raise RuntimeError('Not a 60s measured run: '+rid)
    frames = [r for r in read_csv(path/'per_frame.csv.gz') if r['phase']=='active']
    if len(frames)!=14400 or len({(int(r['stream_id']),int(r['frame_id'])) for r in frames})!=14400:
        raise RuntimeError('Source ID universe failed: '+rid)
    phase = {(int(r['stream_id']),int(r['frame_id'])):r for r in
             read_csv(path/'per_frame_phase_timestamps.csv')}
    power = read_csv(path/'power_trace.csv.gz')
    if len(phase)!=condition['target_service_FPS']*T:
        raise RuntimeError('Local phase sample count failed: '+rid)
    local = [r for r in frames if r['placement']=='LOCAL']
    edge = [r for r in frames if r['placement']=='EDGE']
    if len(local)!=condition['target_service_FPS']*T or len(edge)!=(240-condition['target_service_FPS'])*T:
        raise RuntimeError('Frozen split count failed: '+rid)
    first = [[None]*30 for _ in range(8)]
    for r in frames:
        sid,frame = int(r['stream_id']),int(r['frame_id'])
        if integer(r,'logical_arrival_ns')!=t0+frame*NS//30:
            raise RuntimeError('Source timestamp changed: '+rid)
        if frame<30:
            first[sid][frame]=int(r['placement']=='LOCAL')
    if first!=frozen_mask['local_masks']:
        raise RuntimeError('Actual/frozen first-period mask mismatch: '+rid)

    events = [defaultdict(list) for _ in range(T)]
    # Keys are named observations; all timestamps are Thor monotonic for these paths.
    def put(key, stamp, value=1):
        sec = index(stamp,t0)
        if sec is not None:
            events[sec][key].append(value)

    queue_intervals=[]
    service_intervals=[]
    terminal_intervals=[]
    pending_intervals=[]
    arrivals=[]
    departures=[]
    service_starts=[]
    completions=[]
    missing_drop=0
    missing_start=0
    service_all=[]
    gpu_all=[]
    host_all=[]
    expired_by_slot=Counter()
    missing_by_slot=Counter()
    for r in frames:
        due=integer(r,'logical_arrival_ns')
        put('source_arrivals',due)
        if r['placement']=='LOCAL':
            put('Local_assigned_arrivals',due)
            slot=int(r['frame_id'])
            started=integer(r,'inference_start_timestamp_ns')
            completed=integer(r,'completion_timestamp_ns')
            drop=integer(r,'expired_drop_ns')
            if r['terminal_state']=='EXPIRED_DROP':
                expired_by_slot[slot]+=1
                if drop is None:
                    missing_drop+=1
                    missing_by_slot[slot]+=1
                    put('missing_drop_timestamp_expired',due)
                    continue  # Excluded from B_Q, never given an inferred release.
                departure=drop
                terminal=drop
                put('Local_expired_drop_events',drop)
            elif r['terminal_state']=='COMPLETED':
                if started is None or completed is None:
                    missing_start+=1
                    continue
                departure=started
                terminal=completed
                put('Local_raw_completions',completed)
                if completed-due<=100_000_000:
                    put('Local_timely_completions',completed)
                ready=integer(r,'ready_timestamp_ns')
                if ready is not None:
                    put('Local_queue_wait_ms',started,(started-ready)/1e6)
                put('Local_service_ms',completed,(completed-started)/1e6)
                service_all.append((completed-started)/1e6)
                phase_row=phase.get((int(r['stream_id']),slot))
                if phase_row and phase_row['gpu_event_status']=='OK':
                    gpu=number(phase_row,'gpu_exec_duration_ms')
                    pre=integer(phase_row,'t_pre_infer')
                    returned=integer(phase_row,'t_infer_return')
                    if gpu is not None and pre is not None and returned is not None:
                        put('GPU_stream_span_ms',completed,gpu)
                        put('host_residual_ms',completed,(returned-pre)/1e6-gpu)
                        gpu_all.append(gpu)
                        host_all.append((returned-pre)/1e6-gpu)
                service_intervals.append((started,completed))
                service_starts.append(started)
                completions.append(completed)
            else:
                raise RuntimeError('Unrecognized Local terminal state: '+rid)
            arrivals.append(due)
            departures.append(departure)
            queue_intervals.append((due,departure))
            terminal_intervals.append((due,terminal))
        elif r['placement']=='EDGE':
            put('Edge_assigned_arrivals',due)
            completed=integer(r,'completion_timestamp_ns')
            submitted=integer(r,'socket_submission_ns')
            drop=integer(r,'expired_drop_ns')
            if completed is not None:
                put('Edge_completions',completed)
                if completed-due<=100_000_000:
                    put('Edge_timely_completions',completed)
                if submitted is not None:
                    put('Edge_request_response_ms',completed,(completed-submitted)/1e6)
            if submitted is not None:
                put('Edge_offload_wait_ms',submitted,(submitted-due)/1e6)
            pending_intervals.append((due,submitted if submitted is not None else drop))
        else:
            raise RuntimeError('Source frame has no Local/Edge destination: '+rid)
    if missing_start:
        raise RuntimeError(f'Missing Local execution timestamp count {missing_start}: {rid}')
    if len(arrivals)+missing_drop!=len(local):
        raise RuntimeError('Local queue-state input count mismatch: '+rid)
    arrivals=np.sort(np.asarray(arrivals,dtype=np.int64))
    departures=np.sort(np.asarray(departures,dtype=np.int64))
    service_starts=np.sort(np.asarray(service_starts,dtype=np.int64))
    completions=np.sort(np.asarray(completions,dtype=np.int64))
    boundaries=np.asarray([t0+n*NS//30 for n in range(T*30+1)],dtype=np.int64)
    bq=np.searchsorted(arrivals,boundaries,side='left')-np.searchsorted(departures,boundaries,side='left')
    ins=np.searchsorted(service_starts,boundaries,side='left')-np.searchsorted(completions,boundaries,side='right')
    if np.any(bq<0) or np.any(ins<0):
        raise RuntimeError('Negative queue/in-service carry-over: '+rid)
    work=bq+ins
    slot_rows=[]
    for n in range(T*30):
        slot_rows.append({'run_id':rid,'condition':f"L{condition['target_service_FPS']}"+
            ('A' if condition['admission_pattern']=='ALIGNED' else 'S'),
            'round':condition['repeat'],'slot_index':n,'slot_start_ns':int(boundaries[n]),
            'm_L':frozen_mask['m_L'][n%30],'m_E':frozen_mask['m_E'][n%30],
            'B_Q':int(bq[n]),'U':int(ins[n]),'W':int(work[n]),
            'expired_or_pruned_count':expired_by_slot[n],
            'missing_drop_timestamp_expired_count':missing_by_slot[n]})
    service_bins=interval_bins(service_intervals,t0)
    pending_bins=interval_bins(pending_intervals,t0)
    terminal_bins=interval_bins(terminal_intervals,t0)
    window_rows=[]
    for sec in range(T):
        left,right=t0+sec*NS,t0+(sec+1)*NS
        slot=slice(sec*30,(sec+1)*30)
        qb=bq[slot];uu=ins[slot];ww=work[slot]
        r_q=float(np.mean(qb>0))
        state='LOW' if r_q<=.10 else ('HIGH' if r_q>=.90 else 'TRANSITION')
        cc_mean,cc_p95,_,_=occupancy(service_bins[sec],left,right)
        pending_mean,_,pending_peak,_=occupancy(pending_bins[sec],left,right)
        _,_,_,backlog_positive=occupancy(terminal_bins[sec],left,right)
        e=events[sec]
        samples=[r for r in power if index(integer(r,'timestamp_ns'),t0)==sec]
        freq=[float(r['actual_gpu_freq_MHz']) for r in samples if
              r.get('actual_gpu_freq_MHz') not in ('',None) and float(r['actual_gpu_freq_MHz'])>0]
        oc3=[int(r['OC3_count']) for r in samples if r.get('OC3_count') not in ('',None)]
        temp=[float(r['temperature_C']) for r in samples if r.get('temperature_C') not in ('',None)]
        tx=[int(r['network_tx_bytes']) for r in samples if r.get('network_tx_bytes') not in ('',None)]
        assigned=len(e['Local_assigned_arrivals']);raw=len(e['Local_raw_completions'])
        drops=len(e['Local_expired_drop_events'])
        row={'run_id':rid,'condition':slot_rows[0]['condition'],'round':condition['repeat'],
            'window_second':sec,'window_start_ns':left,'window_end_ns':right,
            'source_arrivals':len(e['source_arrivals']),
            'Local_assigned_arrivals':assigned,'Edge_assigned_arrivals':len(e['Edge_assigned_arrivals']),
            'Local_raw_completions':raw,'Local_timely_completions':len(e['Local_timely_completions']),
            'Local_raw_completion_FPS':raw,'Local_timely_FPS':len(e['Local_timely_completions']),
            'Local_expired_or_pruned':drops,
            'missing_drop_timestamp_expired_count':len(e['missing_drop_timestamp_expired']),
            'pruning_aware_workload_balance':assigned-raw-drops,
            'Local_queue_wait_p50_ms':percentile(e['Local_queue_wait_ms'],50),
            'Local_queue_wait_p95_ms':percentile(e['Local_queue_wait_ms'],95),
            'r_Q':r_q,'state':state,'B_Q_mean':float(np.mean(qb)),'B_Q_p50':float(np.percentile(qb,50)),
            'B_Q_p95':float(np.percentile(qb,95)),'B_Q_max':int(np.max(qb)),
            'U_positive_fraction':float(np.mean(uu>0)),'U_mean':float(np.mean(uu)),
            'U_p95':float(np.percentile(uu,95)),
            'W_positive_fraction':float(np.mean(ww>0)),'W_mean':float(np.mean(ww)),
            'W_p95':float(np.percentile(ww,95)),
            'terminal_backlog_positive_time_fraction_reference_only':backlog_positive,
            'Local_service_mean_ms':mean(e['Local_service_ms']),
            'Local_service_p50_ms':percentile(e['Local_service_ms'],50),
            'Local_service_p95_ms':percentile(e['Local_service_ms'],95),
            'GPU_stream_span_mean_ms':mean(e['GPU_stream_span_ms']),
            'GPU_stream_span_p95_ms':percentile(e['GPU_stream_span_ms'],95),
            'host_residual_mean_ms':mean(e['host_residual_ms']),
            'host_residual_p95_ms':percentile(e['host_residual_ms'],95),
            'active_concurrency_mean':cc_mean,'active_concurrency_p95':cc_p95,
            'Edge_assigned':len(e['Edge_assigned_arrivals']),
            'Edge_completed':len(e['Edge_completions']),
            'Edge_timely':len(e['Edge_timely_completions']),
            'Edge_offload_wait_p50_ms':percentile(e['Edge_offload_wait_ms'],50),
            'Edge_offload_wait_p95_ms':percentile(e['Edge_offload_wait_ms'],95),
            'Edge_request_response_p50_ms':percentile(e['Edge_request_response_ms'],50),
            'Edge_request_response_p95_ms':percentile(e['Edge_request_response_ms'],95),
            'Edge_pending_mean':pending_mean,'Edge_pending_peak':pending_peak,
            'OC3_sample_delta':max(oc3)-min(oc3) if oc3 else None,
            'OC3_sample_start':oc3[0] if oc3 else None,'OC3_sample_end':oc3[-1] if oc3 else None,
            'temperature_mean_C':mean(temp),'temperature_start_C':temp[0] if temp else None,
            'temperature_end_C':temp[-1] if temp else None,
            'actual_GPU_frequency_mean_MHz':mean(freq),
            'actual_GPU_frequency_non_target_fraction':sum(abs(x-1575)>1 for x in freq)/len(freq) if freq else None,
            'GPU_frequency_readback_samples':len(freq),
            'CPU_pin_before':before_cpu['status'],'CPU_pin_after':after_cpu['status'],
            'network_TX_bytes_delta_sampled':tx[-1]-tx[0] if len(tx)>=2 else None}
        if row['source_arrivals']!=240 or assigned+row['Edge_assigned']!=240:
            raise RuntimeError('Per-second source admission mismatch: '+rid)
        window_rows.append(row)
    counts=Counter(r['state'] for r in window_rows)
    summary_rows=[]
    for state in ('LOW','HIGH','TRANSITION'):
        rates=[r['Local_raw_completion_FPS'] for r in window_rows if r['state']==state]
        summary_rows.append({'run_id':rid,'condition':slot_rows[0]['condition'],
            'round':condition['repeat'],'state':state,'n_windows':len(rates),
            'Local_raw_completion_FPS_mean':mean(rates),'median':median(rates),
            'p10':percentile(rates,10),'p50':percentile(rates,50),'p90':percentile(rates,90),
            'minimum':min(rates) if rates else None,'maximum':max(rates) if rates else None,
            'mu_low_run':median(rates) if state=='LOW' and len(rates)>=5 else None,
            'mu_high_run':median(rates) if state=='HIGH' and len(rates)>=5 else None,
            'eligible_for_lower_envelope':state=='HIGH' and len(rates)>=5,
            'excluded_reason':('HIGH_WINDOWS_LT_5' if state=='HIGH' and len(rates)<5 else
                               'LOW_WINDOWS_LT_5' if state=='LOW' and len(rates)<5 else ''),
            'lambda_L_FPS':condition['target_service_FPS'],
            'lambda_L_per_slot':condition['target_service_FPS']/30,
            'mu_high_per_slot':median(rates)/30 if state=='HIGH' and len(rates)>=5 else None})
    runs=positive_runs(bq[:-1])
    wruns=positive_runs(work[:-1])
    persistent=[(a,b) for a,b in runs if b-a>=30]
    first_persistent=persistent[0][0] if persistent else None
    longest=max(runs,key=lambda x:x[1]-x[0]) if runs else None
    wlongest=max(wruns,key=lambda x:x[1]-x[0]) if wruns else None
    recovery_gaps=[runs[i+1][0]-runs[i][1] for i in range(len(runs)-1)]
    if runs and runs[-1][1]<T*30:
        recovery_gaps.append(T*30-runs[-1][1])
    recovery={'run_id':rid,'condition':slot_rows[0]['condition'],'round':condition['repeat'],
        'fraction_slots_B_Q_positive':float(np.mean(bq[:-1]>0)),
        'fraction_slots_U_positive':float(np.mean(ins[:-1]>0)),
        'fraction_slots_W_positive':float(np.mean(work[:-1]>0)),
        'first_persistent_carryover_slot':first_persistent,
        'first_persistent_carryover_seconds':first_persistent/30 if first_persistent is not None else None,
        'longest_continuous_B_Q_positive_slots':longest[1]-longest[0] if longest else 0,
        'longest_continuous_W_positive_slots':wlongest[1]-wlongest[0] if wlongest else 0,
        'queue_recoveries':max(0,len(runs)-1)+int(bool(runs and runs[-1][1]<T*30)),
        'zero_carryover_recovery_gap_slots':json.dumps(recovery_gaps),
        'zero_carryover_recovery_gap_seconds':json.dumps([n/30 for n in recovery_gaps]),
        'end_of_active_B_Q':int(bq[-1]),'end_of_active_U':int(ins[-1]),
        'end_of_active_W':int(work[-1]),
        'B_Q_slope_longest_persistent_frames_per_second':
            slope([n/30 for n in range(*longest)],bq[longest[0]:longest[1]])
            if longest and longest[1]-longest[0]>=30 else None,
        'Local_expired_or_pruned_cohort':sum(expired_by_slot.values()),
        'missing_drop_timestamp_expired_count':missing_drop,
        'expired_excluded_from_B_Q_due_to_missing_drop':missing_drop,
        'HIGH_window_count':counts['HIGH'],'LOW_window_count':counts['LOW'],
        'TRANSITION_window_count':counts['TRANSITION'],
        'HIGH_window_mean_pruning_aware_balance':mean([r['pruning_aware_workload_balance']
            for r in window_rows if r['state']=='HIGH']),
        'HIGH_window_mean_assigned':mean([r['Local_assigned_arrivals'] for r in window_rows if r['state']=='HIGH']),
        'HIGH_window_mean_raw_completed':mean([r['Local_raw_completions'] for r in window_rows if r['state']=='HIGH']),
        'HIGH_window_mean_expired':mean([r['Local_expired_or_pruned'] for r in window_rows if r['state']=='HIGH'])}
    active_power=[r for r in power if index(integer(r,'timestamp_ns'),t0) is not None]
    active_freq=[float(r['actual_gpu_freq_MHz']) for r in active_power if
        r.get('actual_gpu_freq_MHz') not in ('',None) and float(r['actual_gpu_freq_MHz'])>0]
    edge_offload=[(integer(r,'socket_submission_ns')-integer(r,'logical_arrival_ns'))/1e6
        for r in edge if integer(r,'socket_submission_ns') is not None]
    edge_response=[(integer(r,'response_completion_ns')-integer(r,'socket_submission_ns'))/1e6
        for r in edge if integer(r,'response_completion_ns') is not None and
        integer(r,'socket_submission_ns') is not None]
    return window_rows,slot_rows,summary_rows,recovery,{
        'run_id':rid,'condition':slot_rows[0]['condition'],'round':condition['repeat'],
        'temperature_start_C':number(active_power[0],'temperature_C') if active_power else None,
        'temperature_mean_C':mean([float(r['temperature_C']) for r in active_power if r.get('temperature_C') not in ('',None)]),
        'temperature_end_C':number(active_power[-1],'temperature_C') if active_power else None,
        'OC3_before':manifest['OC3_before'],'OC3_after':manifest['OC3_after'],
        'OC3_delta':manifest['OC3_after']-manifest['OC3_before'],
        'actual_GPU_frequency_non_target_fraction':sum(abs(x-1575)>1 for x in active_freq)/len(active_freq)
            if active_freq else None,
        'actual_GPU_frequency_readback_samples':len(active_freq),
        'CPU_pin_before':before_cpu['status'],'CPU_pin_after':after_cpu['status'],
        'run_order_index':condition['order_index'],
        'service_mean_ms':mean(service_all),'GPU_span_mean_ms':mean(gpu_all),
        'host_residual_mean_ms':mean(host_all),
        'Edge_integrity_status':edge_final['integrity_status'],
        'Edge_errors':json.dumps(edge_final.get('errors',[])),
        'Edge_expired':sum(r['terminal_state']=='EXPIRED_DROP' for r in edge),
        'Edge_drops':edge_final.get('drops'),'Edge_duplicates':edge_final.get('duplicates'),
        'Edge_offload_wait_p95_ms':percentile(edge_offload,95),
        'Edge_request_response_p95_ms':percentile(edge_response,95),
        'Edge_pending_mean':mean([r['Edge_pending_mean'] for r in window_rows]),
        'Edge_pending_peak':max(r['Edge_pending_peak'] for r in window_rows),
        'network_transmitted_rate_Mbps':(manifest.get('run_end_diagnostics',{}).get('network_tx_bytes',0)-
            manifest.get('run_start_diagnostics',{}).get('network_tx_bytes',0))*8/T/1e6
            if isinstance(manifest.get('run_end_diagnostics',{}).get('network_tx_bytes'),int) and
               isinstance(manifest.get('run_start_diagnostics',{}).get('network_tx_bytes'),int) else None,
        'WiFi_BSSID_start':manifest.get('wifi_start',{}).get('BSSID'),
        'WiFi_BSSID_end':manifest.get('wifi_end',{}).get('BSSID'),
        'WiFi_signal_start_dBm':manifest.get('wifi_start',{}).get('signal_dBm'),
        'WiFi_signal_end_dBm':manifest.get('wifi_end',{}).get('signal_dBm'),
        'summary_integrity':summary['integrity_status']}


def main():
    plan=read_json(GRID/'plan.json')
    if read_json(GRID/'analysis01/H1_summary.json')['verdict']!='H1_NOT_SUPPORTED':
        raise RuntimeError('Frozen H1 verdict changed')
    masks=read_json(GRID/'BLOCK_B_MASK_MANIFEST.json')
    conditions=[c for c in plan['order'] if c['repeat'] in range(1,6) and c['seconds']==60]
    if len(conditions)!=30:
        raise RuntimeError('Not the frozen 30 measured Grid02 runs')
    windows=[];slots=[];services=[];recoveries=[];systems=[]
    for i,c in enumerate(conditions,1):
        label=f"L{c['target_service_FPS']}"+('A' if c['admission_pattern']=='ALIGNED' else 'S')
        w,s,sv,r,sys=compute_run(c,masks[label])
        windows+=w;slots+=s;services+=sv;recoveries.append(r);systems.append(sys)
        print(f'{i:02d}/30 {c["run_id"]}: LOW={r["LOW_window_count"]} '
              f'HIGH={r["HIGH_window_count"]} expired={r["Local_expired_or_pruned_cohort"]}',flush=True)
    write_csv('per_window_local_dynamics.csv',windows)
    write_csv('per_slot_carryover.csv',slots)
    write_csv('slot_arrival_structure.csv',[slot_structure(k,masks[k]) for k in
        ('L216A','L216S','L208A','L208S','L200A','L200S')])
    write_csv('state_dependent_local_service.csv',services)
    write_csv('backlog_recovery_summary.csv',recoveries)
    write_csv('hardware_confound_audit.csv',systems)
    write_csv('edge_network_confound_audit.csv',systems)
    print('core CSVs written',flush=True)


if __name__=='__main__':
    main()
