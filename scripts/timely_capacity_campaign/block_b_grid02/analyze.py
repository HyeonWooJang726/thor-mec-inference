"""After-restore, log-only Block B paired and mechanism analysis."""
import argparse
import csv
import gzip
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from grid_config import OUT, PLAN, order, sha
from validate import read_frames, validate_run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from dispatch_observation import positions


def read_csv(path):
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with Path(path).open('x', newline='') as stream:
        if rows:
            fields = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)


def write_json(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')


def quantile(values, pct):
    if not values: return None
    x = sorted(values); q = (len(x)-1)*pct/100
    lo = int(q); hi = min(lo+1, len(x)-1)
    return x[lo]+(x[hi]-x[lo])*(q-lo)


def val(row, name):
    item = row.get(name)
    return None if item in ('', None) else int(item)


def timely(row):
    end = val(row, 'completion_timestamp_ns')
    begin = val(row, 'logical_arrival_ns')
    return end is not None and begin is not None and end-begin <= 100_000_000


def client_pending(edge_rows, start, end):
    events=[]
    at_end=0
    for row in edge_rows:
        begin=val(row,'logical_arrival_ns')
        terminal=val(row,'socket_submission_ns') or val(row,'expired_drop_ns')
        if terminal is None or terminal>=end: at_end+=1
        stop=min(terminal if terminal is not None else end,end)
        if begin<stop and begin<end:
            events.extend(((begin,1),(stop,-1)))
    level=peak=area=0;previous=start
    for stamp,delta in sorted(events):
        if stamp<start:
            level+=delta;continue
        area+=level*(stamp-previous);level+=delta;peak=max(peak,level);previous=stamp
    area+=level*(end-previous)
    return {'mean':area/(end-start),'peak':peak,'active_end':at_end}


def server_metrics(run_id):
    base = OUT / 'received_edge' / run_id
    summary = json.loads((base/'summary.json').read_text())
    rows = read_csv(base/'requests.csv')
    if summary.get('integrity_status') != 'VALID' or not all(summary.get(k) for k in
            ('drain_completed','cleanup_completed','worker_thread_exited')) or \
            not (summary.get('received') == summary.get('completed') ==
                 summary.get('responses_sent') == len(rows)):
        raise RuntimeError('Edge server accounting/lifecycle failure: '+run_id)
    ids = [int(r['request_id']) for r in rows]
    if len(set(ids)) != len(ids): raise RuntimeError('Duplicate Edge server request ID')
    def elapsed(a,b):
        return [(int(r[b])-int(r[a]))/1e6 for r in rows]
    queue = elapsed('queue_enter_ns','queue_start_ns')
    infer = elapsed('inference_start_ns','inference_end_ns')
    return {'run_id': run_id, 'received': len(rows), 'completed': summary['completed'],
            'responses_sent': summary['responses_sent'], 'max_queue': summary.get('queue_peak_observed'),
            **{f'queue_wait_p{p}_ms': quantile(queue,p) for p in (50,95,99)},
            **{f'inference_p{p}_ms': quantile(infer,p) for p in (50,95,99)}}, {int(r['request_id']): r for r in rows}


def vin_active(manifest, directory):
    """Existing named first instantaneous VIN mW, monotonic 100-ms trace."""
    path = directory/'power_trace.csv.gz'
    if not path.is_file():
        return {'status':'UNAVAILABLE','reason':'power_trace.csv.gz absent'}
    with gzip.open(path, 'rt', newline='') as stream:
        trace = list(csv.DictReader(stream))
    t0, t1 = int(manifest['active_start_ns']), int(manifest['active_end_ns'])
    points = []
    for r in trace:
        match = re.search(r'\bVIN (\d+)mW/', r.get('raw_tegrastats',''))
        points.append((int(r['timestamp_ns']), int(match.group(1))/1000 if match else None))
    points.sort()
    if len(points)<2 or points[0][0]>t0 or points[-1][0]<t1 or any(
            points[i+1][0]<=points[i][0] for i in range(len(points)-1)):
        return {'status':'UNAVAILABLE','reason':'VIN trace does not bracket active window'}
    left = max(i for i,x in enumerate(points) if x[0]<=t0)
    right = min(i for i,x in enumerate(points) if x[0]>=t1)
    selected = points[left:right+1]
    if any(w is None for _,w in selected) or any((b[0]-a[0])>500_000_000 for a,b in zip(selected,selected[1:])):
        return {'status':'UNAVAILABLE','reason':'VIN missing or >0.5s sample gap'}
    def interpolate(stamp):
        for a,b in zip(selected,selected[1:]):
            if a[0]<=stamp<=b[0]:
                return a[1]+(b[1]-a[1])*(stamp-a[0])/(b[0]-a[0])
        raise RuntimeError('VIN endpoint not bracketed')
    clipped = [(t0,interpolate(t0))]+[(t,w) for t,w in selected if t0<t<t1]+[(t1,interpolate(t1))]
    joules = sum((b[0]-a[0])/1e9*(a[1]+b[1])/2 for a,b in zip(clipped,clipped[1:]))
    return {'status':'VALID','field':'VIN first instantaneous mW','active_energy_J':joules,
            'active_mean_W':joules/((t1-t0)/1e9), 'samples':len(selected),
            'run_energy_J':None,
            'run_energy_reason':'Frozen power trace stops around active end, before full drain/cleanup; no extrapolation'}


def per_run(condition):
    rid = condition['run_id']; directory = OUT/rid
    m = json.loads((directory/'manifest.json').read_text())
    s = json.loads((directory/'summary.json').read_text())
    v = validate_run(directory, condition)
    if v['status'] != 'PASS': raise RuntimeError(f'Invalid Block B session {rid}: {v["errors"]}')
    frames = [r for r in read_frames(directory/'per_frame.csv.gz') if r.get('phase')=='active']
    if len(frames) != 240*condition['seconds']:
        raise RuntimeError('Incomplete source frames')
    observed = positions(frames)
    server, request_rows = server_metrics(rid)
    edge_ids = [int(r['edge_request_id']) for r in frames if r['placement']=='EDGE'
                and r['socket_submission_ns'] not in ('',None)]
    if sorted(request_rows) != sorted(edge_ids):
        raise RuntimeError('Thor/Edge request IDs differ')
    by_stream = []
    by_path = []
    by_position = []
    for group_name, values in [('STREAM', range(8)), ('PATH', ('LOCAL','EDGE')),
                               ('POSITION', [(path,pos) for path in ('LOCAL','EDGE') for pos in range(8)])]:
        for value in values:
            if group_name=='STREAM':
                subset = [r for r in frames if int(r['stream_id'])==value]
            elif group_name=='PATH':
                subset = [r for r in frames if r['placement']==value]
            else:
                path,position = value
                subset = [r for r in frames if r['placement']==path and
                          observed[int(r['stream_id']),int(r['frame_id'])]['dispatch_position']==position]
            if not subset: continue
            timely_count = sum(timely(r) for r in subset)
            expired = sum(r['terminal_state']=='EXPIRED_DROP' for r in subset)
            complete = sum(r['terminal_state']=='COMPLETED' for r in subset)
            if timely_count+(complete-timely_count)+expired != len(subset):
                raise RuntimeError('Terminal partition mismatch in '+group_name)
            record = {'run_id':rid, 'group':group_name, 'value':value, 'admitted':len(subset),
                      'timely':timely_count, 'late':complete-timely_count, 'expired':expired,
                      'TIR':timely_count/len(subset), 'timely_FPS':timely_count/condition['seconds']}
            if group_name=='POSITION':
                record['destination'],record['dispatch_position']=value
            waits = [(val(r,'socket_submission_ns')-val(r,'logical_arrival_ns'))/1e6
                     for r in subset if val(r,'socket_submission_ns') is not None]
            responses = [(val(r,'response_completion_ns')-val(r,'socket_submission_ns'))/1e6
                         for r in subset if val(r,'response_completion_ns') is not None and
                         val(r,'socket_submission_ns') is not None]
            record.update({f'offload_wait_p{p}':quantile(waits,p) for p in (50,95,99)})
            record.update({f'request_response_p{p}':quantile(responses,p) for p in (50,95,99)})
            if group_name=='STREAM': by_stream.append(record)
            elif group_name=='PATH': by_path.append(record)
            else: by_position.append(record)
    total_timely = sum(timely(r) for r in frames)
    if total_timely != s.get('timely_completed_frames'):
        raise RuntimeError('Frame/summary timely mismatch')
    stream_tirs = [r['TIR'] for r in by_stream]
    phase = read_csv(directory/'per_frame_phase_timestamps.csv')
    executed = [r for r in phase if r.get('terminal_state')=='COMPLETED' and
                r.get('gpu_event_status')=='OK' and r.get('gpu_exec_duration_ms') not in ('',None)]
    gpu = [float(r['gpu_exec_duration_ms']) for r in executed]
    host = [(int(r['t_infer_return'])-int(r['t_pre_infer']))/1e6-float(r['gpu_exec_duration_ms'])
            for r in executed if r.get('t_infer_return') not in ('',None) and
            r.get('t_pre_infer') not in ('',None)]
    net_before=m.get('run_start_diagnostics',{}).get('network_tx_bytes')
    net_after=m.get('run_end_diagnostics',{}).get('network_tx_bytes')
    tx_delta=net_after-net_before if isinstance(net_before,int) and isinstance(net_after,int) else None
    edge_frames=[r for r in frames if r['placement']=='EDGE']
    pending=client_pending(edge_frames,int(m['active_start_ns']),int(m['active_end_ns']))
    offload=[(val(r,'socket_submission_ns')-val(r,'logical_arrival_ns'))/1e6
             for r in edge_frames if val(r,'socket_submission_ns') is not None]
    response=[(val(r,'response_completion_ns')-val(r,'socket_submission_ns'))/1e6
              for r in edge_frames if val(r,'response_completion_ns') is not None and
              val(r,'socket_submission_ns') is not None]
    energy = vin_active(m,directory)
    cpu_before=json.loads((directory/'CPU_BEFORE_RUN.json').read_text())
    cpu_after=json.loads((directory/'CPU_AFTER_RUN.json').read_text())
    cpu_residency=json.loads((directory/'CPU_TIME_IN_STATE_DELTA.json').read_text())
    target_residency=[r['residency_fraction'] for r in cpu_residency
                      if r['frequency_kHz']==2601000]
    if cpu_before.get('status')!='PASS' or cpu_after.get('status')!='PASS' or len(target_residency)!=7:
        raise RuntimeError('CPU policy/residency evidence incomplete')
    energy_row = {'run_id':rid, 'energy_scope':'Thor VIN only, excludes Edge/server',
                  'P_active_mean_W':energy.get('active_mean_W'),
                  'E_active_J':energy.get('active_energy_J'), 'P_run_mean_W':None,
                  'E_run_J':None, 'Thor_J_per_timely_frame':None,
                  'status':energy['status'], 'reason':energy.get('reason',energy.get('run_energy_reason'))}
    run = {'run_id':rid, 'round':condition['repeat'], 'rate_local':condition['target_service_FPS'],
           'rate_edge':240-condition['target_service_FPS'], 'pattern':condition['admission_pattern'],
           'total_timely_FPS':total_timely/condition['seconds'], 'TIR_total':total_timely/len(frames),
           'worst_stream_TIR':min(stream_tirs), 'best_stream_TIR':max(stream_tirs),
           'stream_gap':max(stream_tirs)-min(stream_tirs),
           'Local_timely_FPS':next(r['timely_FPS'] for r in by_path if r['value']=='LOCAL'),
           'Edge_timely_FPS':next(r['timely_FPS'] for r in by_path if r['value']=='EDGE'),
           'Local_assigned_TIR':next(r['TIR'] for r in by_path if r['value']=='LOCAL'),
           'Edge_assigned_TIR':next(r['TIR'] for r in by_path if r['value']=='EDGE'),
           'local_queue_p95_ms':s.get('local_queue_ms',{}).get('p95'),
           'local_queue_p50_ms':s.get('local_queue_ms',{}).get('p50'),
           'local_queue_p99_ms':s.get('local_queue_ms',{}).get('p99'),
           'local_service_mean_ms':s.get('local_service_ms',{}).get('mean'),
           'local_service_p50_ms':s.get('local_service_ms',{}).get('p50'),
           'local_service_p95_ms':s.get('local_service_ms',{}).get('p95'),
           'local_service_p99_ms':s.get('local_service_ms',{}).get('p99'),
           'GPU_stream_span_mean_ms':statistics.mean(gpu) if gpu else None,
           'GPU_stream_span_p95_ms':quantile(gpu,95),
           'host_residual_mean_ms':statistics.mean(host) if host else None,
           'host_residual_p95_ms':quantile(host,95),
           'Local_completion_latency_mean_ms':s.get('local_E2E_ms',{}).get('mean'),
           'active_concurrency_mean':s.get('active_concurrency_mean'),
           'Edge_offload_wait_p50_ms':quantile(offload,50),
           'Edge_offload_wait_p95_ms':quantile(offload,95),
           'Edge_offload_wait_p99_ms':quantile(offload,99),
           'Edge_request_response_p50_ms':quantile(response,50),
           'Edge_request_response_p95_ms':quantile(response,95),
           'Edge_request_response_p99_ms':quantile(response,99),
           'Edge_pending_active_mean':pending['mean'],
           'Edge_pending_peak':pending['peak'],
           'Edge_pending_active_end':pending['active_end'],
           'OC3_delta':s.get('OC3_delta'), 'frequency_restore_ok':s.get('frequency_restore_ok'),
           'CPU_pin_before':cpu_before['status'],'CPU_pin_after':cpu_after['status'],
           'CPU_2601000_residency_fraction_min':min(target_residency),
           'CPU_2601000_residency_fraction_mean':statistics.mean(target_residency),
           'temperature':json.dumps(s.get('temperature'),sort_keys=True),
           'network_TX_bytes_delta':tx_delta,
           'observed_transmitted_data_rate_Mbps':tx_delta*8/condition['seconds']/1e6 if tx_delta is not None else None,
           'wifi_BSSID_start':m.get('wifi_start',{}).get('BSSID'),
           'wifi_BSSID_end':m.get('wifi_end',{}).get('BSSID'),
           'wifi_signal_start_dBm':m.get('wifi_start',{}).get('signal_dBm'),
           'wifi_signal_end_dBm':m.get('wifi_end',{}).get('signal_dBm'),
           'edge_path_error_count':len(m.get('edge_path_errors',[])),
           'integrity_status':'VALID'}
    return run, by_stream, by_path, by_position, server, energy_row


def prediction(condition, observed):
    if condition=='L216S':
        low, high = 225, 234
        matched = low <= observed <= high
        predicted = '225..234 inclusive'
        signed = None if matched else (observed-low if observed<low else observed-high)
    else:
        point = {'L216A':212,'L208A':229,'L208S':240,'L200A':233,'L200S':240}[condition]
        matched = abs(observed-point)<=5
        predicted = point
        signed = observed-point
    return {'condition':condition,'prediction':predicted,'observed_mean':observed,
            'MATCH_status':'MATCH' if matched else 'MISMATCH',
            'signed_difference':signed, 'absolute_difference':abs(signed) if signed is not None else None,
            'direction':'HIGH' if signed is not None and signed>0 else 'LOW' if signed is not None and signed<0 else 'IN_RANGE',
            'verdict_effect':'NONE'}


def local_prior_comparison(results):
    """Descriptive only; historical rows never enter H1 or new repeat count."""
    root = OUT.parent
    sources = {
        'L216A': (root/'timely_capacity_scan02/analysis_revision01_result/per_run_timely.csv',
                  ['V22_TIMELY_D100_R1_L216_P01','V22_TIMELY_D100_R2_L216_P01']),
        'L200A': (root/'timely_capacity_scan02/analysis_revision01_result/per_run_timely.csv',
                  ['V22_TIMELY_D100_R1_L200_P01','V22_TIMELY_D100_R2_L200_P01']),
        'L208A': (root/'block_a_phase_pilot02/analysis01/per_run.csv',
                  ['V22_BLOCKA_D100_A1_P02','V22_BLOCKA_D100_A2_P02']),
        'L208S': (root/'block_a_phase_pilot02/analysis01/per_run.csv',
                  ['V22_BLOCKA_D100_S1_P02','V22_BLOCKA_D100_S2_P02']),
    }
    output=[]
    for label,(source,ids) in sources.items():
        historic={r['run_id']:r for r in read_csv(source)}
        if any(rid not in historic for rid in ids):
            raise RuntimeError('Missing frozen Local-only prior')
        rate=int(label[1:4]);pattern='ALIGNED' if label.endswith('A') else 'STAGGERED'
        current=[r for r in results if r['rate_local']==rate and r['pattern']==pattern]
        for key, new_key in [('service_mean','local_service_mean_ms'),
                             ('GPU_span_mean','GPU_stream_span_mean_ms'),
                             ('host_residual_mean','host_residual_mean_ms'),
                             ('queue_p95','local_queue_p95_ms'),
                             ('TIR_admission','Local_assigned_TIR'),
                             ('timely_FPS','Local_timely_FPS')]:
            values=[float(historic[rid][key]) for rid in ids if historic[rid].get(key) not in ('',None)]
            current_values=[r[new_key] for r in current if r.get(new_key) is not None]
            output.append({'condition':label,'metric':key,'prior_source':str(source),
                           'prior_run_ids':ids,'prior_values':values,
                           'prior_mean':statistics.mean(values) if values else None,
                           'hybrid_run_ids':[r['run_id'] for r in current],
                           'hybrid_values':current_values,
                           'hybrid_mean':statistics.mean(current_values) if current_values else None,
                           'interpretation':'coupling diagnostic only; not H1'})
    for label in ('L216S','L200S'):
        output.append({'condition':label,'metric':'ALL','prior_source':'NO_DIRECT_MATCHED_PRIOR'})
    return output


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Analyzer output outside fresh Block B root')
    restore=json.loads((OUT/'CPU_RESTORE_READBACK.json').read_text())
    if restore.get('status')!='PASS' or restore.get('plan_sha256')!=sha(PLAN):
        raise RuntimeError('CPU restore PASS required before analysis')
    conditions=order()
    results=[]; streams=[]; paths=[]; positions_out=[]; servers=[]; energies=[]
    for c in conditions:
        run, per_stream, per_path, per_position, server, energy=per_run(c)
        if c['repeat']==0:
            warmup=run
            if run['integrity_status']!='VALID':raise RuntimeError('Warmup INVALID')
            continue
        results.append(run);streams+=per_stream;paths+=per_path
        positions_out+=per_position;servers.append(server);energies.append(energy)
    if len(results)!=30: raise RuntimeError('Incomplete measured grid')
    by={(r['round'],r['rate_local'],r['pattern'][0]):r for r in results}
    h1=[];paired=[];four=[]
    for i in range(1,6):
        l216a=by[i,216,'A'];l208s=by[i,208,'S']
        both=(l208s['total_timely_FPS']>l216a['total_timely_FPS'] and
              l208s['worst_stream_TIR']>=l216a['worst_stream_TIR'])
        h1.append({'round':i,'L208S_minus_L216A_timely_FPS':l208s['total_timely_FPS']-l216a['total_timely_FPS'],
                   'L208S_minus_L216A_worst_TIR':l208s['worst_stream_TIR']-l216a['worst_stream_TIR'],
                   'both_conditions':both})
        for rate in (216,208,200):
            a,s=by[i,rate,'A'],by[i,rate,'S']
            paired.append({'round':i,'split':f'L{rate}E{240-rate}',
                           **{name+'_S_minus_A':s[name]-a[name] for name in
                              ('total_timely_FPS','TIR_total','worst_stream_TIR')}})
        alternate=max(by[i,216,'A']['total_timely_FPS'],by[i,216,'S']['total_timely_FPS'],
                      by[i,200,'A']['total_timely_FPS'])
        four.append({'round':i,'L208S_timely_FPS':l208s['total_timely_FPS'],
                     'BestAlternative4_timely_FPS':alternate,
                     'L208S_minus_BestAlternative4':l208s['total_timely_FPS']-alternate,
                     'formal_verdict':'NONE'})
    summary=[]; predictions=[]
    for rate in (216,208,200):
        for token in ('A','S'):
            rr=[by[i,rate,token] for i in range(1,6)]
            label=f'L{rate}{token}'
            row={'condition':label,'five_timely_FPS':[r['total_timely_FPS'] for r in rr],
                 'mean_total_timely_FPS':statistics.mean(r['total_timely_FPS'] for r in rr),
                 'mean_worst_stream_TIR':statistics.mean(r['worst_stream_TIR'] for r in rr)}
            summary.append(row);predictions.append(prediction(label,row['mean_total_timely_FPS']))
    descriptive=[]
    for rate in (216,208,200):
        for metric in ('total_timely_FPS','TIR_total','worst_stream_TIR'):
            values=[by[i,rate,'S'][metric]-by[i,rate,'A'][metric] for i in range(1,6)]
            descriptive.append({'comparison':f'L{rate} S-A','metric':metric,'five_values':values,
                'positive_count':sum(v>0 for v in values),'mean':statistics.mean(values),
                'median':statistics.median(values),'min':min(values),'max':max(values),
                'formal_verdict':'NONE'})
    for label,left,right in (('ALIGNED L200A-L216A',(200,'A'),(216,'A')),
                             ('STAGGERED L208S-L216S',(208,'S'),(216,'S'))):
        for metric in ('total_timely_FPS','TIR_total','worst_stream_TIR'):
            values=[by[(i,)+left][metric]-by[(i,)+right][metric] for i in range(1,6)]
            descriptive.append({'comparison':label,'metric':metric,'five_values':values,
                'positive_count':sum(v>0 for v in values),'mean':statistics.mean(values),
                'median':statistics.median(values),'min':min(values),'max':max(values),
                'formal_verdict':'NONE'})
    args.output.mkdir(parents=True,exist_ok=False)
    for name,rows in [('per_run.csv',results),('per_stream.csv',streams),('per_path.csv',paths),
                      ('per_dispatch_position.csv',positions_out),('server_metrics.csv',servers),
                      ('energy_per_run.csv',energies),('H1_rounds.csv',h1),
                      ('paired_by_split.csv',paired),('policy_four_cell_summary.csv',four),
                      ('split_pattern_summary.csv',summary),
                      ('descriptive_comparison_summary.csv',descriptive),
                      ('prediction_vs_observed.csv',predictions),
                      ('local_prior_comparison.csv',local_prior_comparison(results))]:
        write_csv(args.output/name,rows)
    write_json(args.output/'H1_summary.json',{'verdict':'H1_SUPPORTED' if all(r['both_conditions'] for r in h1)
               else 'H1_NOT_SUPPORTED','rule':'same-round 5/5 strict timely FPS and non-strict worst TIR',
               'statistical_significance_test':False})
    write_json(args.output/'prediction_summary.json',{'MATCH_count':sum(r['MATCH_status']=='MATCH' for r in predictions),
               'prediction_has_no_validity_or_H1_effect':True})
    write_json(args.output/'provenance.json',{'plan_sha256':sha(PLAN),'CPU_restore':'PASS',
               'warmup_excluded':warmup['run_id'],'Edge_raw_collected':True,
               'energy_scope':'Thor VIN only; full run energy unavailable until trace covers cleanup',
               'Thor_vs_Edge_clock_subtraction':False})


if __name__=='__main__':main()
