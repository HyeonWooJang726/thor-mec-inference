"""CPU-only server-to-Thor-analyzer structural path over in-memory transport."""
import csv
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

import analyze
import config
import regression_cpu as test
import formal_protocol as wire

_spec=importlib.util.spec_from_file_location('edge_inflight_production_server',
    Path(__file__).with_name('edge_server.py'))
server=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def one_case(c):
    with tempfile.TemporaryDirectory(prefix='edge_inflight_analysis_') as temporary:
        root=Path(temporary)
        edge=root/'received_edge'/c['run_id']
        edge.parent.mkdir(parents=True)
        left,right=test.memory_pair()
        expected=server.expected_hello(c,config.sha(config.PLAN),wire.load_runtime_helpers().CACHE_SHA256)
        outcome=[]
        def serve():
            try:outcome.append(server.serve_session(left,edge,expected,c['edge_C'],lambda i:test.FakeBackend(i)))
            finally:left.close()
        thread=threading.Thread(target=serve)
        thread.start()
        wire.send_message(right,wire.HELLO,metadata=expected)
        kind,_,ready,_=wire.recv_message(right)
        assert kind==wire.READY and ready['backend']['C_E']==c['edge_C']
        for rid in (0,1):wire.send_message(right,wire.REQUEST,rid,payload=bytes(wire.RAW_BYTES))
        wire.send_message(right,wire.END,metadata={'submitted':2,'assigned':1440,
            'expired_request_ids':list(range(2,1440))})
        while True:
            kind,_,_,_=wire.recv_message(right)
            if kind==wire.FINAL:break
        right.close();thread.join(timeout=10)
        assert outcome[0]['integrity_status']=='VALID'
        session=root/'sessions'/c['run_id'];session.mkdir(parents=True)
        start=1_000_000_000_000
        rows=[];assigned=0
        for frame in range(900):
            due=start+frame*1_000_000_000//30
            for sid in range(8):
                admitted=config.bit(c['pattern'],sid,frame)
                row={'stream_id':sid,'frame_id':frame,'logical_arrival_ns':due,
                     'admission_timestamp_ns':due,'admission_observed_ns':due+sid,
                     'admitted':admitted,'placement':'EDGE' if admitted else 'SKIP'}
                if admitted:
                    rid=assigned;assigned+=1
                    row.update(edge_request_id=rid,edge_release_target_ns=due,
                               absolute_deadline_ns=due+100_000_000)
                    if rid<2:
                        row.update(terminal_state='COMPLETED',
                                   socket_submission_ns=due+1_000_000,
                                   response_completion_ns=due+50_000_000)
                    else:
                        row.update(terminal_state='EXPIRED_DROP',
                                   expired_drop_ns=due+100_000_000)
                rows.append(row)
        assert assigned==1440
        with (session/'source_frames.csv').open('x',newline='') as stream:
            fields=list(dict.fromkeys(key for row in rows for key in row))
            writer=csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader();writer.writerows(rows)
        write_json(session/'manifest.json',{'active_start_ns':start,'active_end_ns':start+30_000_000_000,
                   'condition':c,'plan_sha256':config.sha(config.PLAN)})
        write_json(session/'summary.json',{'integrity_status':'VALID',
                   'automatic_retry_count':0,'edge_transport_error_count':0,
                   'network_TX_bytes_delta':2*691200})
        previous=analyze.OUT
        analyze.OUT=root
        try:result=analyze.run_row(c)
        finally:analyze.OUT=previous
        assert result['integrity_status']=='VALID',result
        assert result['C_E']==c['edge_C'] and result['overall_TIR']==2/1440
        assert result['worker_count']==result['context_count']==c['edge_C']
        return 'PASS'


def main():
    order=config.frozen_order()
    result={'C_E1_ALIGNED_server_to_Thor_analysis':one_case(order[0]),
            'C_E2_STAGGERED_server_to_Thor_analysis':one_case(order[3])}
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
