"""Result-independent canonical admission/split branches and contiguous-PASS selector."""
import json
from bootstrap import frozen as cfg,OUT,V2
LEVELS=(56,64,72,80)

def order(emax):
    if emax not in LEVELS:raise ValueError('Unsupported branch')
    rows=[]
    for old in cfg.expected_order('B'):
        c=dict(old); demand=old['target_service_FPS'];local=8*old['local_r']
        edge=min(8*old['edge_r'],emax);admitted=local+edge
        capped=edge!=8*old['edge_r']
        cell=f'S{demand}-L{local}E{edge}'+(f'-CAPPED-A{admitted}' if capped else '')
        c.update(cell=cell,original_cell=old['cell'],source_demand_FPS=demand,
            target_service_FPS=admitted,admitted_FPS=admitted,admission_r=admitted//8,
            edge_r=edge//8,branch_E_max=emax,analysis_class='B-CAPPED' if capped else 'B-PRIMARY',
            original_condition_status='EDGE_PATH_LIMITED' if capped else 'EXECUTABLE',
            source_normalization_FPS=240,
            run_id=f'TCCBV2_E{emax}_R{c["repeat"]}_{cell.replace("-","_")}_P01')
        rows.append(c)
    return rows

def preflight_order():
    return [dict(run_id=f'TCCBV2_PREFLIGHT_R{rep}_E{rate}_P01',rate=rate,seconds=30,repeat=rep)
        for rep,rates in ((1,LEVELS),(2,tuple(reversed(LEVELS)))) for rate in rates]

def select(runs):
    """Invalid/missing evidence never becomes PASS or a measured FAIL."""
    statuses={};reason=[]
    if len(runs)!=8 or any(r.get('rate') not in LEVELS for r in runs):reason.append('RUN_SET_MISMATCH')
    for rate in LEVELS:
        rows=[r for r in runs if r.get('rate')==rate]
        if len(rows)!=2 or {r.get('repeat') for r in rows}!={1,2} or any(r.get('integrity_status')!='VALID' or r.get('Edge_timely_ratio') is None for r in rows):
            statuses[rate]='INCONCLUSIVE';reason.append(rate)
        else:statuses[rate]='PASS' if all(r['Edge_timely_ratio']>=.90 for r in rows) else 'FAIL'
    flags=[];seen_fail=False
    for status in statuses.values():
        if status=='FAIL':seen_fail=True
        if seen_fail and status=='PASS':flags=['EDGE_PREFLIGHT_NON_MONOTONE']
    if statuses[56]=='FAIL':status='EDGE_PATH_LIMITED_BELOW_E56';emax=None
    elif reason:status='INCONCLUSIVE';emax=None
    else:
        emax=None
        for rate in LEVELS:
            if statuses[rate]!='PASS':break
            emax=rate
        status='BRANCH_SELECTED'
    return dict(status=status,E_max=emax,branch=f'E_MAX_{emax}' if emax else None,
        per_load={str(k):v for k,v in statuses.items()},flags=flags,invalid_or_missing_loads=reason,
        gate_basis='2/2 integrity-valid D100 assigned-normalized timely ratio >=0.90; contiguous PASS only')

def branch_path(emax):return V2/f'E_MAX_{emax}'/'plan.json'

def load(path):
    from pathlib import Path
    path=Path(path);data=json.loads(path.read_text())
    if cfg.sha(path)!=path.with_suffix('.sha256').read_text().split()[0]:raise ValueError('Plan hash mismatch')
    if data.get('phase')=='preflight':assert data['order']==preflight_order()
    elif data.get('phase')=='campaign':assert data['order']==order(data['E_max'])
    else:raise ValueError('Unexpected plan phase')
    for rel,h in data['source_sha256'].items():
        if cfg.sha(cfg.ROOT/rel)!=h:raise ValueError('Frozen dependency mismatch: '+rel)
    return data
