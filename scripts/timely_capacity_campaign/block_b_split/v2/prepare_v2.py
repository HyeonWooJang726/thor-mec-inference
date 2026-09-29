"""Create new frozen V2 artifacts only; preserve all Block A and Block B V1 bytes."""
import copy
import csv
import json
from datetime import datetime,timezone
from pathlib import Path
from bootstrap import ROOT,HERE,OUT,V2,frozen as cfg
import config_v2 as conf

OLD='98dfe7df667349eaa3993581950857c2ee241d2dea82e55acecf11becc9f0368'
PRED='65f6852533bc57918564357f0f5a6faa17075dd231dcdce3767f587ad7d27d53'

def text(p,s):
    with p.open('x') as f:f.write(s)
def save(p,obj):text(p,json.dumps(obj,indent=2)+'\n')
def freeze(p,obj):
    save(p,obj);h=cfg.sha(p);text(p.with_suffix('.sha256'),h+'  '+p.name+'\n');return h
def csvfile(p,rows):
    with p.open('x',newline='') as f:
        w=csv.DictWriter(f,list(dict.fromkeys(k for r in rows for k in r)));w.writeheader()
        w.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
def edge_files():
    return {**{n:HERE/n for n in ('bootstrap.py','config_v2.py','edge_v2.py')},
        'campaign_config.py':ROOT/'scripts/timely_capacity_campaign/common/campaign_config.py',
        'pruning_edge_server.py':ROOT/'scripts/expired_work_pruning/edge_server.py',
        **{n:ROOT/'scripts/edge_raw_capacity_gate'/n for n in ('formal_server.py','formal_protocol.py','profile_edge_concurrency.py')}}

def prepare():
    assert cfg.sha(OUT/'plan.json')==OLD
    assert cfg.sha(ROOT/'scripts/timely_capacity_campaign/common/PREDICTION.md')==PRED
    assert json.loads((V2/'cpu_validation.json').read_text())['status']=='PASS'
    old=json.loads((OUT/'plan.json').read_text());sources=dict(old['source_sha256'])
    for rel,h in sources.items():assert cfg.sha(ROOT/rel)==h,rel
    sources.update({str(p.relative_to(ROOT)):cfg.sha(p) for p in HERE.glob('*.py')})
    deps={name:cfg.sha(p) for name,p in edge_files().items()};branches={}
    now=datetime.now(timezone.utc).isoformat()
    for e in conf.LEVELS:
        d=V2/f'E_MAX_{e}';d.mkdir(exist_ok=False);p=copy.deepcopy(old)
        p.update(version='BLOCK_B_V2',phase='campaign',E_max=e,order=conf.order(e),frozen_utc=now,
            source_sha256=sources,edge_dependency_sha256=deps,edge_preflight_order=conf.preflight_order(),
            freeze_status='FROZEN_B_V2',approval='Block B V2 only; never authorizes Block A or automatic workload execution',
            B_gate='B-PRIMARY only, R1-R3 paired reference; capped excluded. No automatic global gate from primary Edge ratio; record observed degradation.',
            B_preflight='E56/E64/E72/E80 30s x2, ascending/reverse; contiguous2/2D100>=.90; E56FAIL stops; any invalid unresolved stops; nonmonotone flag alone does not stop.',
            CPU_validation_sha256={x.name:cfg.sha(x) for x in V2.glob('*validation.json')},
            normalization='Source denominator240 for all runs including capped; original demand and actual admitted separately reported',
            wifi='iw dev wlP1p1s0 link at start/end only; optional failure visible; no periodic polling/settings. Reconnects between endpoints UNOBSERVED.',
            predictions='Original unchanged; never gate inputs. Original full240 maxima unidentifiable for incomplete capped grid => INCONCLUSIVE.')
        cells={c['cell']:c for c in p['order']};entries={}
        masks=[]
        for name,c in cells.items():
            ms,slots=cfg.schedule(c['target_service_FPS'],8*c['edge_r'])
            entries[name]=dict(admitted_frame_ids_mod30=[list(m) for m in ms],edge_slots=[dict(stream_id=s,frame_id_mod30=f,request_id=q,release_ns=t) for (s,f),(q,t) in slots.items()])
            for f in range(30):
                for sid in range(8):masks.append(dict(cell=name,**cfg.decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=f*10**9//30),0,c)))
        p['placement']=dict(source_phase_ns=[0]*8,source_due='t0+floor(frame_index*1e9/30)',physical_decode_resize_FPS=240,
            admission='Existing canonical floor accumulator, aligned across streams; capped changes only integer per-stream rate',
            edge_eligibility='Existing round-robin q%8 and latest admitted slot at first_due+q/Edge_FPS; modulo30 repeat',cells=entries)
        h=freeze(d/'plan.json',p);branches[str(e)]=dict(path=str((d/'plan.json').relative_to(ROOT)),sha256=h)
        csvfile(d/'run_order.csv',p['order']);csvfile(d/'condition_list.csv',list(cells.values()));csvfile(d/'periodic_frame_ids.csv',masks)
        lines=[f'# E_MAX_{e} — 35 frozen runs',f'Plan SHA256: `{h}`','',
            '|Order|Run ID|Class|Original demand|Admitted/r|Local/Edge|','|---:|---|---|---:|---:|---:|']
        for c in p['order']:lines.append(f"|{c['order_index']}|{c['run_id']}|{c['analysis_class']}|{c['source_demand_FPS']}|{c['admitted_FPS']}/{c['admission_r']}|{8*c['local_r']}/{8*c['edge_r']}|")
        lines+=['','R1–R3 only for B-PRIMARY gate. R4–R5 retained for the four original L176/L184 logical conditions. Fixed10s interrun idle; original expired-only FIFO; no retry. B-CAPPED is descriptive admission+placement, never a split-only causal comparison. Source normalization remains240.']
        text(d/'PLAN.md','\n'.join(lines)+'\n')
    pf=dict(version='BLOCK_B_V2',phase='preflight',order=conf.preflight_order(),branches=branches,
        source_sha256=sources,edge_dependency_sha256=deps,cache=old['cache'],edge_host=old['edge_host'],idle_seconds=10,
        criterion='Per load2/2 integrityVALID and assigned-normalized timely ratioD100>=0.90. Select maximal contiguous PASS from56. Invalid/missing means INCONCLUSIVE; E56FAIL means EDGE_PATH_LIMITED_BELOW_E56.',
        non_monotone='Any PASS above a lower FAIL => EDGE_PREFLIGHT_NON_MONOTONE; retain contiguous branch.',
        workload='Existing real cachedRAW64030 cyclic, B1/C_E1, expired-only, no Local inference or clock control',
        wifi='Read-only iw endpoint snapshots, no polling/configuration',frozen_utc=now)
    pfsha=freeze(V2/'preflight_plan.json',pf);csvfile(V2/'preflight_run_order.csv',pf['order'])
    master=dict(status='BLOCK_B_V2_READY_WAITING_FOR_PREFLIGHT_APPROVAL',frozen_utc=now,previous_plan_sha256=OLD,
        previous_status='SUPERSEDED_BUT_PRESERVED',branches=branches,preflight=dict(path=str((V2/'preflight_plan.json').relative_to(ROOT)),sha256=pfsha),
        prediction_sha256=PRED,source_sha256=sources,CPU_validation_sha256=pf['source_sha256'] and {x.name:cfg.sha(x) for x in V2.glob('*validation.json')},
        rules='No outcomes used to design branches. Block A remains byte-identical. No workload/control execution in preparation.')
    mainsha=freeze(OUT/'block_b_plan_v2.json',master)
    save(OUT/'revision_record.json',dict(old_path='plan.json',old_sha256=OLD,old_status='SUPERSEDED_BUT_PRESERVED',new_sha256=mainsha,
        reasons=['Wi-Fi path','RAW640691200 bytes','E72/E80 near historical TCP throughput','Measured Edge ceiling branches','Conservative contiguous PASS with nonmonotone flag','Canonical integer per-stream admission in capped regime'],
        Block_A_sha256='70fbd32b8e3f77d0714dd15095c2b1e8af45268dc30a46224419b036e5f20409',prediction_sha256=PRED,
        deployment_document='v2/DEPLOYMENT.md; original DEPLOYMENT.md preserved'))
    text(OUT/'BLOCK_B_PLAN_V2.md',f'''# Block B V2 — preparation only

Status: BLOCK_B_V2_READY_WAITING_FOR_PREFLIGHT_APPROVAL
Master SHA256: {mainsha}
V1 {OLD}: SUPERSEDED_BUT_PRESERVED; Block A unchanged.

Eight preflight runs: R1 E56→E64→E72→E80; R2 E80→E72→E64→E56; active30s, idle10s, no Local inference.
Each load PASS iff2/2 VALID and Edge timely ratio>=0.90. E_max is the last contiguous PASS starting at56. E56FAIL stops; missing/invalid stops inconclusive. Nonmonotonicity is flagged and does not alone stop a valid contiguous branch.
All four branch JSONs and run orders were frozen before any preflight. Each retains35 runs and original logical repeat policy. All mean/sampleSD/min/max/repeat values retained.

B-PRIMARY: same admitted IDs within demand, original split conditions only. R1–R3 paired reference verdict; R4–R5 descriptive additional replication.
B-CAPPED: original240 demand remains; canonical r=(Local+E_max)/8; physical decode/resize240. Source-normalized TIR denominator240; excluded work reported. No split-only causal verdict.

Expired-only Local/Edge checks, non-cancellation after start/submission, FIFO survivor order, canonical preprocessing and source phases remain frozen. Requested/readback frequency, restore, OC3, temperature and VIN remain recorded. Wi-Fi start/end observations optional with explicit unavailable reasons; intervening disconnect/reconnect unobserved. PHY and historical TCP never select E_max.

Prediction file remains unchanged. B1/B2 cannot resolve the original full240 grid maximum if capped points replace unmeasured original conditions: report INCONCLUSIVE. B4 evaluated from all eight valid preflight outcomes. No threshold is invented for qualitative A2; it stays descriptive under Block A analysis.

See v2/E_MAX_*/PLAN.md, run_order.csv and periodic_frame_ids.csv. See v2/DEPLOYMENT.md for exact future commands and hashes. No automatic deployment, retry, branch redesign or workload execution.
''')
    bundle=V2/'edge_bundle_v2';bundle.mkdir()
    for name,p in edge_files().items():
        with (bundle/name).open('xb') as f:f.write(p.read_bytes())
    for name,p in [('preflight_plan.json',V2/'preflight_plan.json')]+[(f'E_MAX_{e}.json',conf.branch_path(e)) for e in conf.LEVELS]:
        with (bundle/name).open('xb') as f:f.write(p.read_bytes())
    sums=''.join(f'{cfg.sha(p)}  {p.name}\n' for p in sorted(bundle.iterdir()) if p.is_file())
    text(bundle/'SHA256SUMS',sums)
    deployment(master,mainsha,sums)
    print(json.dumps(dict(master_sha256=mainsha,preflight_sha256=pfsha,branches=branches),indent=2))

def deployment(master,mainsha,sums):
    pf=master['preflight']['sha256'];edge='scripts/timely_capacity_campaign/block_b_split/edge_v2'
    thor='scripts/timely_capacity_campaign/block_b_split/v2'
    lines=[f'# Block B V2 — WAITING FOR PREFLIGHT APPROVAL\n\nMaster SHA: `{mainsha}`. No execution yet. Block A unaffected.',
        'Manually transfer all14 files (13 payload files plus SHA256SUMS) from `results/timely_capacity_campaign/block_b_split/v2/edge_bundle_v2/` to NEW `/tmp/tcc_edge_v2/` on Edge. No automatic SSH/deployment. Existing engine/cache reused.',
        '```text\n'+sums+'```','## [Edge Server · Terminal] Deploy to a NEW path',
        """```bash
cd ~/research/thor-mec-inference
./venv/bin/python -B - <<'PYDEPLOY'
from pathlib import Path
import hashlib
src=Path('/tmp/tcc_edge_v2'); dst=Path('scripts/timely_capacity_campaign/block_b_split/edge_v2')
assert not dst.exists(), 'STOP: never overwrite existing deployment'
entries=[]
for line in (src/'SHA256SUMS').read_text().splitlines():
    digest,name=line.split('  ',1)
    assert Path(name).name==name
    data=(src/name).read_bytes()
    assert hashlib.sha256(data).hexdigest()==digest,name
    entries.append((name,data))
assert len(entries)==13
"""+f"assert hashlib.sha256((src/'preflight_plan.json').read_bytes()).hexdigest()=='{pf}'\n"+"""dst.mkdir(parents=True,exist_ok=False)
for name,data in entries+[('SHA256SUMS',(src/'SHA256SUMS').read_bytes())]:
    with (dst/name).open('xb') as f:f.write(data)
print(dst.resolve())
PYDEPLOY
```"""]
    def edgecmd(plan,sha,out):return f'''```bash
cd ~/research/thor-mec-inference
./venv/bin/python -B {edge}/edge_v2.py --plan {edge}/{plan} \\
  --engine server/models/rtdetr_warehouse_v1.0.2.fp16.b1.engine \\
  --cache results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz \\
  --output results/timely_capacity_campaign/block_b_split/v2/{out} \\
  --approve-plan-sha256 {sha}
```'''
    lines+=['## [Edge Server · Terminal] Preflight — only after explicit approval',edgecmd('preflight_plan.json',pf,'edge_preflight01'),
        '## [Thor · Terminal] Preflight — after Edge LISTENING',f'''```bash
cd /home/ainet/research/thor-mec-rate-dvfs-gate
python3 -B {thor}/preflight_v2.py --approve-plan-sha256 {pf}
```''',
        'Inspect `results/timely_capacity_campaign/block_b_split/v2/preflight01/selection.json`. E56 FAIL or invalid/missing means STOP. Non-monotone valid evidence uses contiguous branch. No automatic campaign launch. Execute exactly the frozen selected branch; never substitute a higher branch.']
    for e in conf.LEVELS:
        h=master['branches'][str(e)]['sha256']
        lines += [f'## Selected E_MAX_{e} ONLY — future separately approved campaign',edgecmd(f'E_MAX_{e}.json',h,f'edge_E_MAX_{e}_primary01'),f'''[Thor · Terminal]
```bash
cd /home/ainet/research/thor-mec-rate-dvfs-gate
python3 -B {thor}/run_v2.py campaign --emax {e} --approve-plan-sha256 {h}
python3 -B {thor}/analysis_v2.py --emax {e} --output results/timely_capacity_campaign/block_b_split/v2/E_MAX_{e}/analysis01
```''']
    lines+=['Thor raw results: `v2/E_MAX_<selected>/TCCBV2_*/`. Preserve failures; no retry/overwrite. Return Edge outputs manually into NEW `v2/received_edge_preflight01/` and `v2/received_edge_E_MAX_<selected>_primary01/`; never merge into Thor run directories.','Wi-Fi queries are read-only `iw dev wlP1p1s0 link`; no sudo or settings changes. If unavailable, retain the reason; do not invent signal/bitrate/reconnect data. User may reduce unrelated AP traffic manually; code never controls it.']
    text(V2/'DEPLOYMENT.md','\n\n'.join(lines)+'\n')

if __name__=='__main__':prepare()
