"""Post-restore, read-only raw analysis for the frozen eight E48 runs."""
import argparse
import csv
import json
import statistics
from pathlib import Path

from config import OUT, PLAN, frozen_order, load_plan, sha, validate_source_rows
from run_thor import cpu_report


def read_csv(path):
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def percentile(values,p):
    if not values: return None
    values=sorted(values); x=(len(values)-1)*p/100; i=int(x)
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(x-i)


def write_json(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')


def write_csv(path,rows):
    with path.open('x',newline='') as stream:
        if rows:
            writer=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
            writer.writeheader();writer.writerows(rows)


def verdict(rows):
    by={(r['C_E'],r['pattern'],r['repeat']):r for r in rows}
    if len(by)!=8 or any(r['integrity_status']!='VALID' for r in rows):
        return {'primary_verdict':'INVALID_NO_CAPACITY_SELECTION','C_E_selected':None,
                'repeat_ambiguity':False,'Delta_R1':None,'Delta_R2':None}
    def tir(c,p,j): return by[c,p,j]['overall_TIR']
    deltas=[tir(2,'ALIGNED',j)-tir(1,'ALIGNED',j) for j in (1,2)]
    if all(d>=.10 for d in deltas): primary,selected='EDGE_BURST_CONCURRENCY_SENSITIVE',2
    elif all(d<.10 for d in deltas): primary,selected='EDGE_BURST_CONCURRENCY_ROBUST',1
    else: primary,selected='EDGE_C_REPEAT_AMBIGUOUS',None
    return {'CE1_ALIGNED_TIR_R1':tir(1,'ALIGNED',1),
            'CE1_ALIGNED_TIR_R2':tir(1,'ALIGNED',2),
            'CE2_ALIGNED_TIR_R1':tir(2,'ALIGNED',1),
            'CE2_ALIGNED_TIR_R2':tir(2,'ALIGNED',2),
            'Delta_R1':deltas[0], 'Delta_R2':deltas[1],
            'C_E_selected':selected,'primary_verdict':primary,
            'repeat_ambiguity':primary=='EDGE_C_REPEAT_AMBIGUOUS',
            'aligned_staggered_gap_CE1':[tir(1,'STAGGERED',j)-tir(1,'ALIGNED',j) for j in (1,2)],
            'aligned_staggered_gap_CE2':[tir(2,'STAGGERED',j)-tir(2,'ALIGNED',j) for j in (1,2)],
            'server_configuration_method':'METHOD_B_PROCESS_RESTART',
            'selection_metric':'overall E48 ALIGNED TIR only; absolute +0.10 both repeats'}


def run_row(c):
    directory=OUT/'sessions'/c['run_id']
    edge=OUT/'received_edge'/c['run_id']
    s=json.loads((directory/'summary.json').read_text())
    m=json.loads((directory/'manifest.json').read_text())
    es=json.loads((edge/'summary.json').read_text())
    source=read_csv(directory/'source_frames.csv')
    requests=read_csv(edge/'requests.csv')
    fidelity=validate_source_rows(source,c,m['active_start_ns'])
    admitted=[r for r in source if r['admitted']=='1']
    completed=[r for r in admitted if r.get('response_completion_ns') not in (None,'')]
    timely=[r for r in completed if int(r['response_completion_ns'])-int(r['logical_arrival_ns'])<=100_000_000]
    expired=[r for r in admitted if r.get('terminal_state')=='EXPIRED_DROP']
    stream_tir=[]
    for sid in range(8):
        selected=[r for r in admitted if int(r['stream_id'])==sid]
        stream_tir.append(sum(r in timely for r in selected)/len(selected))
    def duration(rows,a,b):
        return [(int(r[b])-int(r[a]))/1e6 for r in rows if r.get(a) not in (None,'') and r.get(b) not in (None,'')]
    queue=duration(requests,'queue_enter_ns','queue_start_ns')
    service=duration(requests,'inference_start_ns','inference_end_ns')
    offload=duration(admitted,'logical_arrival_ns','socket_submission_ns')
    response=duration(completed,'socket_submission_ns','response_completion_ns')
    backend=es.get('backend_workers',[])
    valid=(s.get('integrity_status')=='VALID' and fidelity['status']=='PASS' and
           es.get('integrity_status')=='VALID' and es.get('drain_completed') is True and
           es.get('worker_thread_exited') is True and es.get('cleanup_completed') is True and
           len(admitted)==1440 and len(completed)+len(expired)==1440 and
           es.get('received')==es.get('completed')==es.get('responses_sent')==len(requests)==len(completed) and
           es.get('configured_C_E')==c['edge_C'] and es.get('worker_count')==c['edge_C'] and
           es.get('context_count')==c['edge_C'] and len(backend)==c['edge_C'] and
           es.get('warmup_inferences')==50*c['edge_C'] and
           es.get('active_concurrency',{}).get('peak',c['edge_C']+1)<=c['edge_C'] and
           m.get('plan_sha256')==sha(PLAN) and m.get('condition')==c and
           s.get('automatic_retry_count')==0 and s.get('edge_transport_error_count')==0)
    return {'run_id':c['run_id'],'C_E':c['edge_C'],'pattern':c['pattern'],'repeat':c['repeat'],
            'assigned_Edge_FPS':len(admitted)/30,'completed_Edge_FPS':len(completed)/30,
            'overall_TIR':len(timely)/1440 if valid else None,
            'timely_FPS':len(timely)/30 if valid else None,
            'worst_stream_TIR':min(stream_tir) if valid else None,
            'per_stream_TIR':json.dumps(stream_tir) if valid else None,
            'Thor_offload_wait_p50_ms':percentile(offload,50),
            'Thor_offload_wait_p95_ms':percentile(offload,95),
            'request_response_p50_ms':percentile(response,50),
            'request_response_p95_ms':percentile(response,95),
            'server_queue_wait_p50_ms':percentile(queue,50),
            'server_queue_wait_p95_ms':percentile(queue,95),
            'server_service_p50_ms':percentile(service,50),
            'server_service_p95_ms':percentile(service,95),
            'pending_mean':s.get('Thor_client_pending_active_mean'),
            'pending_peak':s.get('Thor_client_pending_peak'),
            'active_concurrency_mean':es.get('active_concurrency',{}).get('mean'),
            'active_concurrency_p95':es.get('active_concurrency',{}).get('p95'),
            'active_concurrency_peak':es.get('active_concurrency',{}).get('peak'),
            'network_TX_bytes_delta':s.get('network_TX_bytes_delta'),
            'observed_transmitted_data_rate_Mbps':s.get('network_TX_bytes_delta',0)*8/30/1e6,
            'worker_count':es.get('worker_count'),'context_count':es.get('context_count'),
            'integrity_status':'VALID' if valid else 'INVALID',
            'errors':json.dumps([] if valid else ['Raw Thor/server/frozen cardinality or accounting check failed'])}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--approve-plan-sha256',required=True)
    args=parser.parse_args()
    plan=load_plan()
    if args.approve_plan_sha256!=sha(PLAN): raise RuntimeError('Exact plan SHA required')
    restore=json.loads((OUT/'CPU_RESTORE_READBACK.json').read_text())
    if restore.get('status')!='PASS' or restore.get('plan_sha256')!=sha(PLAN) or \
            cpu_report('restored')['status']!='PASS':
        raise RuntimeError('CPU restore PASS required before analysis')
    for n in (1,2,3):
        stage=json.loads((OUT/'sessions'/f'stage{n}_status.json').read_text())
        if stage.get('status')!=('CAMPAIGN_COMPLETE' if n==3 else 'STAGE_COMPLETE_WAITING_FOR_EDGE_RESTART'):
            raise RuntimeError('Stage lifecycle incomplete')
    rows=[run_row(c) for c in frozen_order()]
    result=verdict(rows)
    analysis=OUT/'analysis01';analysis.mkdir(exist_ok=False)
    write_csv(analysis/'per_run.csv',rows)
    write_csv(analysis/'paired_aligned_comparison.csv',
              [{'repeat':j,'CE1_TIR':result.get(f'CE1_ALIGNED_TIR_R{j}'),
                'CE2_TIR':result.get(f'CE2_ALIGNED_TIR_R{j}'),
                'Delta_absolute':result.get(f'Delta_R{j}')} for j in (1,2)])
    write_csv(analysis/'placement_robustness_summary.csv',
              [{'C_E':ce,'repeat':j,'staggered_minus_aligned_TIR':result.get(f'aligned_staggered_gap_CE{ce}',[None,None])[j-1]}
               for ce in (1,2) for j in (1,2)])
    write_json(analysis/'edge_C_robustness.json',result)
    write_json(analysis/'validity_summary.json',{'valid_runs':sum(r['integrity_status']=='VALID' for r in rows),
                  'planned_runs':8,'all_valid':all(r['integrity_status']=='VALID' for r in rows)})
    print(result['primary_verdict'])


if __name__=='__main__':main()
