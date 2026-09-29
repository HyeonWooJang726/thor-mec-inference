"""CPU-only end-to-end analyzer output verification, synthetic files under /tmp."""
import json
from pathlib import Path
import shutil
import tempfile
from bootstrap import OUT,frozen as cfg
import config_v2 as conf
import analysis_v2 as analysis

def main():
    fixtures=Path(json.loads((OUT/'v2/cpu_validation.json').read_text())['scratch'])
    source={}
    for p in fixtures.glob('*/manifest.json'):
        m=json.loads(p.read_text());source[(m['target_service_FPS'],m['local_r'],m['edge_r'])]=p.parent
    scratch=Path(tempfile.mkdtemp(prefix='TCC_V2_roundtrip_CPU_'));records=[]
    load,branch=conf.load,conf.branch_path
    try:
        for e in conf.LEVELS:
            root=scratch/f'E_MAX_{e}';root.mkdir();plan={'order':conf.order(e),'phase':'campaign','E_max':e}
            pp=root/'plan.json';pp.write_text(json.dumps(plan));ph=cfg.sha(pp)
            pf=root/'frequency_preflight.json';pf.write_text(json.dumps(dict(status='PASS',plan_sha256=ph,provenance='CPU_SYNTHETIC_NO_CLOCK_ACCESS')))
            for c in plan['order']:
                d=root/c['run_id'];d.mkdir();src=source[c['target_service_FPS'],c['local_r'],c['edge_r']]
                m=json.loads((src/'manifest.json').read_text());m.update(c)
                m.update(execution_manifest_sha256=ph,child_returncode=0,PROCESS_LIFECYCLE='PASS',status_finalized=True,
                    frequency_restore_ok=True,active_phase_completed=True,drain_completed=True,cleanup_started=True,cleanup_completed=True,
                    frequency_preflight={'sha256':cfg.sha(pf)},pin_readback_Hz={'min_freq':1575000000,'max_freq':1575000000})
                (d/'manifest.json').write_text(json.dumps(m))
                for name in ('per_frame.csv.gz','power_trace.csv.gz','summary.json'):shutil.copyfile(src/name,d/name)
            conf.load=lambda p:plan;conf.branch_path=lambda n:pp
            analysis.analyze(e,root/'analysis')
            replay=json.loads((root/'analysis/replay.json').read_text())
            assert len(replay)==35 and all(r['integrity_status']=='VALID' for r in replay),[(r['run_id'],r.get('errors')) for r in replay if r['integrity_status']!='VALID']
            records.append(dict(E_max=e,valid=35,full_analyzer_output='PASS'))
        original=analysis.read_csv
        def missing(p):
            if Path(p).parent.name==plan['order'][0]['run_id']:raise FileNotFoundError('CPU injected missing file; no artifact removed')
            return original(p)
        analysis.read_csv=missing
        try:analysis.analyze(80,root/'analysis_missing')
        finally:analysis.read_csv=original
        r=json.loads((root/'analysis_missing/replay.json').read_text());assert sum(x['integrity_status']=='INVALID' for x in r)==1
    finally:conf.load,conf.branch_path=load,branch
    with (OUT/'v2/full_analyzer_validation.json').open('x') as f:json.dump(dict(status='PASS',branches=records,missing_injection='PASS',scratch=str(scratch),provenance='CPU_SYNTHETIC_NOT_MEASUREMENT'),f,indent=2)
    print('PASS140 full analyzer runs + injected missing trace')

if __name__=='__main__':main()
