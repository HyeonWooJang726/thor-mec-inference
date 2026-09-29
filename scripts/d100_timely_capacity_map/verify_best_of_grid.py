#!/usr/bin/env python3
"""CPU-only exact ranking, tie, aggregate and preservation checks."""
import argparse
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import analyze_best_of_grid as analysis


def fixture():
    rows=[]
    for c in analysis.expected_order():
        n={'T160-A':600,'T200-A':720,'T240-A':680,'T160-B':620,'T200-B':810,'T240-B':760}[c['cell']]
        rows.append(dict(c,integrity_status='VALID',source_frames=14400,
            admitted_identity_sha256=f"CPU_{c['target_service_FPS']}_{c['repeat']}",
            per_stream=[dict(stream_id=k,timely_completed_frames=n) for k in range(8)],
            worst_stream_timely_FPS=n/60,worst_stream_TIR=n/1800,timely_FPS=8*n/60,
            late_completed_FPS=1.,expired_drop_FPS=2.,VIN_J_per_timely_frame=.5))
    return rows


def set_count(rows,cell,repeat,n):
    r=next(r for r in rows if r['cell']==cell and r['repeat']==repeat)
    for s in r['per_stream']:s['timely_completed_frames']=n
    r.update(worst_stream_timely_FPS=n/60,worst_stream_TIR=n/1800,timely_FPS=8*n/60)


def verify():
    good=fixture();checks=[]
    candidates,selected,comp,d=analysis.evaluate(good)
    assert d['verdict']=='EDGE_TIMELY_CAPACITY_EXTENSION_SUPPORTED'
    assert len(candidates)==24 and len(selected)==8 and len(comp)==4
    assert all(r['Best_Local']=='T200-A' and r['Best_Hybrid']=='T200-B' for r in comp)
    assert d['repeat_worst_stream_gain_FPS']==[1.5]*3
    checks.append('18repeat candidates +6condition means; repeat and aggregate winners by worst-stream service, required metrics/deltas')
    bad=copy.deepcopy(good)
    for repeat in (1,2,3):set_count(bad,'T160-A',repeat,900)
    d=analysis.evaluate(bad)[-1]
    assert d['verdict']=='NO_BEST_OF_GRID_EDGE_GAIN'
    assert any(p['verdict']=='HYBRID_TIMELY_CAPACITY_GAIN' for p in d['pairwise_context'])
    varying=copy.deepcopy(good);set_count(varying,'T240-B',2,840)
    d=analysis.evaluate(varying)[-1]
    assert all(x>0 for x in d['repeat_worst_stream_gain_FPS']) and d['verdict']=='INCONCLUSIVE'
    mixed=copy.deepcopy(good)
    for cell,n in [('T160-B',600),('T200-B',700),('T240-B',650)]:set_count(mixed,cell,2,n)
    assert analysis.evaluate(mixed)[-1]['verdict']=='INCONCLUSIVE'
    checks.append('Pair-level gain can coexist with no best-of-grid gain; changing selected point overrides3positive gains; mixed gain signs inconclusive')
    tied=copy.deepcopy(good)
    for repeat in (1,2,3):
        set_count(tied,'T240-A',repeat,720);set_count(tied,'T240-B',repeat,810)
    _,selected,comp,d=analysis.evaluate(tied)
    assert d['verdict']=='EDGE_TIMELY_CAPACITY_EXTENSION_SUPPORTED' and len(selected)==16 and len(comp)==16
    assert all(r['tie_count']==2 for r in selected)
    varying=copy.deepcopy(good)
    for rep in (1,2,3):
        set_count(varying,'T160-A',rep,[1000,500,500][rep-1])
        set_count(varying,'T200-A',rep,800)
    _,selected,_,_=analysis.evaluate(varying)
    a=next(s for s in selected if s['repeat']=='ALL' and s['supply_mode']=='A')
    assert a['cell']=='T200-A' and a['worst_stream_timely_FPS']==800/60
    assert a['worst_stream_timely_FPS']!=(1000+800+800)/180
    checks.append('All exact ties preserved without secondary tie-break; aggregate=max(condition mean), never mean(repeat maxima)')
    for kind in ('missing','duplicate','invalid','wrong_count','wrong_deadline','malformed_stream'):
        rows=copy.deepcopy(good)
        if kind=='missing':rows=rows[1:]
        if kind=='duplicate':rows.append(copy.deepcopy(rows[0]))
        if kind=='invalid':rows[0]['integrity_status']='INVALID'
        if kind=='wrong_count':rows[0]['worst_stream_timely_FPS']+=1
        if kind=='wrong_deadline':rows[0]['deadline_ms']=150
        if kind=='malformed_stream':rows[0]['per_stream']=None
        assert analysis.evaluate(rows)[-1]['verdict']=='INCONCLUSIVE',kind
    rows=copy.deepcopy(good)
    for r in rows:r['VIN_J_per_timely_frame']=None
    _,_,comp,d=analysis.evaluate(rows)
    assert d['verdict']=='EDGE_TIMELY_CAPACITY_EXTENSION_SUPPORTED'
    assert all(r['delta_VIN_J_per_timely_frame'] is None for r in comp)
    checks.append('Missing/duplicate/invalid grid and wrong count/deadline fail closed; unavailable energy stays N/A without fabricating capacity data')
    scratch=Path(tempfile.mkdtemp(prefix='D100_best_grid_CPU_'));source=scratch/'input';source.mkdir()
    (source/'replay.json').write_text(json.dumps(good))
    (source/'paired_comparison.csv').write_text('CPU_ORIGINAL_PAIRWISE_FIXTURE\n')
    before={str(p):analysis.sha(p) for p in source.iterdir()}
    with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'extension',source)
    assert all(analysis.sha(Path(p))==h for p,h in before.items())
    assert json.loads((scratch/'extension/best_of_grid_verdict.json').read_text())['verdict']=='EDGE_TIMELY_CAPACITY_EXTENSION_SUPPORTED'
    original=analysis.pairwise.analyze
    def frozen_mock(output):
        output.mkdir();(output/'replay.json').write_text(json.dumps(good))
        (output/'paired_comparison.csv').write_text('CPU_ORIGINAL_PAIRWISE_FIXTURE\n')
    analysis.pairwise.analyze=frozen_mock
    try:
        with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'combined')
    finally:analysis.pairwise.analyze=original
    assert (scratch/'combined/paired_comparison.csv').read_text()=='CPU_ORIGINAL_PAIRWISE_FIXTURE\n'
    try:analysis.analyze(scratch/'combined',source)
    except RuntimeError:pass
    else:raise AssertionError('Overwrite allowed')
    checks.append('Existing-analysis and combined-entry output paths both preserve pairwise files byte-identically; existing output rejected')
    return dict(status='PASS',provenance='SYNTHETIC_CPU_TEST_NOT_MEASUREMENT',checks=checks,
                GPU_executed=False,network_executed=False,scratch_path=str(scratch))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise RuntimeError('No overwrite')
    r=verify()
    with a.output.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
