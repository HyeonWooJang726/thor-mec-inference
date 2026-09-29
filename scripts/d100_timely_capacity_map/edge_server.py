#!/usr/bin/env python3
"""Nine Hybrid sessions; original pruning protocol/backend, no A connections."""
import inspect
import pruning_edge_server as pruning

ORDERS=(('T160-A','T160-B','T200-B','T200-A','T240-A','T240-B'),
        ('T240-B','T240-A','T200-A','T200-B','T160-B','T160-A'),
        ('T200-A','T200-B','T240-B','T240-A','T160-A','T160-B'))
CELLS={'T160-A':(160,160,0),'T160-B':(160,144,16),'T200-A':(200,200,0),
       'T200-B':(200,184,16),'T240-A':(240,240,0),'T240-B':(240,200,40)}


def conditions(plan):
    if plan['freeze_status']!='FROZEN_D100_TIMELY_CAPACITY_MAP_V1' or len(plan['order'])!=18 or plan['smoke']:
        raise ValueError('Wrong D100 map')
    for i,c in enumerate(plan['order']):
        repeat=i//6+1;cell=ORDERS[repeat-1][i%6];target,local,edge=CELLS[cell]
        expected=dict(run_id=f'DTC_R{repeat}_{cell.replace("-","_")}_P01',kind='formal',repeat=repeat,
            order_index=i+1,cell=cell,supply_mode=cell[-1],target_service_FPS=target,local_r=local//8,edge_r=edge//8,
            deadline_ms=100,K=8,C=2,r=30,frequency='F1575',frequency_MHz=1575,seconds=60,
            pass_name=f'R{repeat}',**{'pass':f'R{repeat}'})
        if c!=expected:raise ValueError('Frozen order/condition mismatch')
    return [c for c in plan['order'] if c['edge_r']]


s=inspect.getsource(pruning.main)
for before,after in [("mode='expired_work_pruning'","mode='d100_timely_capacity_map'"),
    ('pruning_plan_sha256=','map_plan_sha256='),
    ('12 pruning sessions; no Edge-side cancellation','9 D100 Hybrid sessions; A never connects; no cancellation'),
    ('planned=12,','planned=9,')]:
    if s.count(before)!=1:raise RuntimeError('Frozen launcher hook changed: '+before)
    s=s.replace(before,after)
ns=dict(pruning.__dict__,__file__=__file__,conditions=conditions)
exec(compile(s,'<D100-edge-session-plan>','exec'),ns)
main=ns['main']


if __name__=='__main__':raise SystemExit(main())
