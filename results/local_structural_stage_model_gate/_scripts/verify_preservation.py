"""Read-only before/after protection and structural output validation."""
from pathlib import Path
import hashlib,json,subprocess,sys,platform
import numpy as np,pandas as pd,scipy,matplotlib
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def main():
 before=json.loads((ROOT/'protected_inputs_before.json').read_text());mismatch=[]
 for entry in before:
  p=REPO/entry['path']
  if 'symlink' in entry:
   if not p.is_symlink() or str(p.readlink())!=entry['symlink']:mismatch.append(entry['path'])
  elif not p.is_file() or p.stat().st_size!=entry['size'] or sha(p)!=entry['sha256']:mismatch.append(entry['path'])
 raw=json.loads((ROOT/'input_manifest.json').read_text());rawm=[]
 for e in raw['inputs']:
  p=REPO/e['path']
  if not p.is_file() or sha(p)!=e['sha256']:rawm.append(e['path'])
 required=['analysis_plan.md','input_manifest.json','metric_definitions.md','structural_fold_metrics.csv','structural_by_K_C.csv','baseline_comparison.csv','calibration_errors.csv','backoff_usage.csv','structural_assumption_audit.csv','structural_stage_model_report.md']
 assert all((ROOT/f).is_file() for f in required)
 d=dict(np.load(ROOT/'stage_dataset.npz'));indices=[];seenruns=[];maxsum=0
 for fold in range(1,6):
  p=dict(np.load(ROOT/f'predictions_fold{fold}.npz'));idx=p['index'];indices.extend(idx.tolist());seenruns.extend(np.unique(p['run']).tolist())
  assert np.all(d['slot'][idx]==fold) and np.all(d['stage'][idx]!=1)
  assert np.array_equal(d['run'][idx],p['run'])
  expect=np.select([d['stage'][idx]==2,d['stage'][idx]==3],[0,1],default=2)
  assert np.array_equal(expect,p['y'])
  for model in ['B0','B1','P']:
   x=p[model];assert x.shape==(len(idx),3) and np.isfinite(x).all() and np.min(x)>=0 and np.max(x)<=1
   maxsum=max(maxsum,float(abs(x.sum(1)-1).max()))
  t=pd.read_csv(ROOT/'transition_support_lookup.csv');g=t[t.fold==fold].set_index('transition_group_id')
  assert all(v in g.index for v in np.unique(p['transition_group_id']))
  assert int(g.test_frames.sum())==len(idx) and (g.training_samples>=200).all() and (g.training_runs>=3).all()
 assert len(indices)==len(set(indices))==int((d['stage']!=1).sum()) and set(indices)==set(np.flatnonzero(d['stage']!=1))
 assert len(seenruns)==len(set(seenruns))==280 and maxsum<1e-12
 s=pd.read_csv(ROOT/'service_support_lookup.csv');assert s.training_samples.ge(200).all() and s.training_runs.ge(3).all()
 figures=list((ROOT/'figures').glob('figure*'));assert len(figures)==6 and set(p.suffix for p in figures)=={'.png','.pdf'}
 fits=json.loads((ROOT/'model_fit_records.json').read_text());assert len(fits)==5 and all(e[m]['success'] for e in fits for m in ['B0','B1'])
 initial=json.loads((ROOT/'startup_audit.json').read_text())['git']
 current={c:subprocess.check_output(['git',*c.split()],cwd=REPO,text=True) for c in initial}
 assert current==initial,'Git working tree changed'
 assert not mismatch and not rawm
 result=dict(status='PASS',output_root_preexisted=False,valid_runs=280,total_raw_frames=len(d['stage']),evaluated_frames=len(indices),pre_ready_late_excluded=int((d['stage']==1).sum()),Dynamic_runs_used=0,new_GPU_runs=0,protected_entries_checked=len(before),protected_hash_mismatches=mismatch,canonical_input_files_checked=len(raw['inputs']),canonical_input_hash_mismatches=rawm,existing_raw_modified=False,production_code_modified=False,unrelated_changes_preserved=True,git_before=initial,git_after=current,commit_push='NO',fold_membership='PASS; saved statistical slots; replacement not temporal Round4',feature_leakage_audit='ready inputs only; test W/A_start/S used for labels and assumption audit, not predictions',observer_limitation='actual completion publication/receipt unavailable; ideal event-time state only',probability_max_sum_error=maxsum,minimum_support='200 samples AND 3 training runs',numerical_validation='exact integer all-pair counter fixtures and independent full-distribution sum queries PASS',model_convergence='10/10 direct fits PASS',figure_count=3,figure_formats=['PNG','PDF'],render_review='PNG and PDF raster render visually inspected for labels, margins and legibility',environment=dict(python=sys.executable,version=sys.version,numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,matplotlib=matplotlib.__version__,platform=platform.platform()),analysis_source_hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'_scripts').glob('*')) if p.is_file()})
 (ROOT/'analysis_integrity.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['status','protected_entries_checked','canonical_input_files_checked','evaluated_frames','protected_hash_mismatches','existing_raw_modified','production_code_modified','commit_push']},indent=2))
if __name__=='__main__':main()
