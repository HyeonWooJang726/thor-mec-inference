"""Complete synthetic block analyzer roundtrip, isolated under /tmp."""
import argparse
import copy
import csv
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import campaign_config as cfg
import campaign_analysis as analysis
_spec=importlib.util.spec_from_file_location('tcc_cpu_fixture',Path(__file__).with_name('verify_cpu.py'))
_fixture_module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture_module)
fixture=_fixture_module.fixture


def run(block):
    destination=cfg.out(block)
    root=Path(tempfile.mkdtemp(prefix='tcc_full_replay_'+block+'_CPU_'))
    plan={'order':cfg.expected_order(block),'block':block}
    (root/'plan.json').write_text(json.dumps(plan));ph=cfg.sha(root/'plan.json')
    (root/'frequency_preflight.json').write_text(json.dumps(dict(status='PASS',plan_sha256=ph,provenance='CPU_SYNTHETIC_NO_CLOCK_ACCESS')))
    pre=cfg.sha(root/'frequency_preflight.json');cache={}
    for c in plan['order']:
        if c['cell'] not in cache:cache[c['cell']]=fixture(c)
        m,rows,power=copy.deepcopy(cache[c['cell']]);m.update(c)
        m.update(execution_manifest_sha256=ph,child_returncode=0,PROCESS_LIFECYCLE='PASS',status_finalized=True,
            frequency_restore_ok=True,active_phase_completed=True,drain_completed=True,cleanup_started=True,cleanup_completed=True,
            frequency_preflight={'sha256':pre},pin_readback_Hz={'min_freq':1575000000,'max_freq':1575000000},
            fixture_provenance='CPU_SYNTHETIC_NOT_MEASUREMENT')
        d=root/c['run_id'];d.mkdir()
        (d/'manifest.json').write_text(json.dumps(m))
        (d/'summary.json').write_text(json.dumps(analysis.summarize(m,rows,power)))
        for name,data in [('per_frame',rows),('power_trace',power)]:
            fields=list(dict.fromkeys(k for r in data for k in r))
            with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                w=csv.DictWriter(f,fields);w.writeheader();w.writerows(data)
    old_out,old_plan=cfg.out,cfg.load_plan
    cfg.out=lambda b:root;cfg.load_plan=lambda b:plan
    try:
        analysis.analyze(block,root/'analysis_valid')
        replay=json.loads((root/'analysis_valid/replay.json').read_text())
        assert len(replay)==len(plan['order']) and all(r['integrity_status']=='VALID' for r in replay),[(r['run_id'],r.get('errors')) for r in replay if r['integrity_status']!='VALID']
        read=analysis.read_csv
        def missing(path):
            if Path(path).parent.name==plan['order'][0]['run_id']:raise FileNotFoundError('CPU injected missing trace; no file deleted')
            return read(path)
        analysis.read_csv=missing
        try:analysis.analyze(block,root/'analysis_missing')
        finally:analysis.read_csv=read
        invalid=json.loads((root/'analysis_missing/replay.json').read_text())
        assert sum(r['integrity_status']=='INVALID' for r in invalid)==1
    finally:cfg.out, cfg.load_plan=old_out,old_plan
    with (destination/'full_analyzer_cpu_validation.json').open('x') as f:json.dump(dict(status='PASS',block=block,planned=len(plan['order']),
        raw_json_gzip_replay_valid=len(replay),injected_missing_invalid=1,scratch=str(root),
        provenance='CPU_SYNTHETIC_NOT_MEASUREMENT',GPU_executed=False,network_executed=False,frequency_control_executed=False),f,indent=2)
    print('PASS full analyzer',block,len(replay))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--block',choices=['A','B'],required=True);a=p.parse_args();run(a.block)
