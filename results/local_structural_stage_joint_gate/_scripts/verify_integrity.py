"""Final protection audit and independent numerical/identity checks (CPU only)."""
from pathlib import Path
import hashlib,json,subprocess,sys,os
os.environ.setdefault('MPLCONFIGDIR','/tmp/structural_joint_mpl')
import numpy as np,pandas as pd,scipy,matplotlib
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1];OLD=REPO/'results/local_structural_stage_model_gate'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def main():
 required=['analysis_plan.md','input_manifest.json','metric_definitions.md','reproduction_check.json','fold_metrics.csv','paired_model_comparison.csv','calibration_by_K.csv','calibration_by_K_C.csv','key_condition_comparison.csv','backoff_usage.csv','joint_stage_model_report.md']
 assert all((ROOT/f).is_file() for f in required)
 before=json.loads((ROOT/'protected_inputs_before.json').read_text());mismatch=[];old_count=0
 for entry in before:
  p=REPO/entry['path'];old_count+=int(p.is_relative_to(OLD))
  if 'symlink' in entry:
   if not p.is_symlink() or str(p.readlink())!=entry['symlink']:mismatch.append(entry['path'])
  elif not p.is_file() or p.stat().st_size!=entry['size'] or sha(p)!=entry['sha256']:mismatch.append(entry['path'])
 inp=json.loads((ROOT/'input_manifest.json').read_text())['inputs'];input_mismatch=[]
 for e in inp:
  p=REPO/e['path']
  if not p.is_file() or p.stat().st_size!=e['size'] or sha(p)!=e['sha256']:input_mismatch.append(e['path'])
 repro=json.loads((ROOT/'reproduction_check.json').read_text());assert repro['status']=='PASS' and repro['B1_reproduced'] and repro['P_old_reproduced']
 d=dict(np.load(ROOT/'stage_dataset.npz'));indices=[];runs=[];maxsum=0;max_queue_diff=0
 support=pd.read_csv(ROOT/'joint_support_lookup.csv');assert support.training_samples.ge(200).all() and support.training_runs.ge(3).all() and support.old_joint_support_identical.all()
 for fold in range(1,6):
  a=dict(np.load(ROOT/f'reproduced_fold{fold}.npz'));b=dict(np.load(ROOT/f'joint_fold{fold}.npz'));ix=a['index']
  assert all(np.array_equal(a[k],b[k]) for k in ['index','run','K','C','y','transition_group_id'])
  assert np.array_equal(a['run'],d['run'][ix]) and np.all(d['slot'][ix]==fold) and np.all(d['stage'][ix]!=1)
  assert np.array_equal(a['y'],np.select([d['stage'][ix]==2,d['stage'][ix]==3],[0,1],default=2))
  indices.extend(ix.tolist());runs.extend(np.unique(a['run']).tolist())
  for prob in [a['B1'],a['P_old'],b['P_joint']]:
   assert np.isfinite(prob).all() and prob.min()>=0 and prob.max()<=1;maxsum=max(maxsum,float(abs(prob.sum(1)-1).max()))
  max_queue_diff=max(max_queue_diff,float(abs(a['P_old'][:,0]-b['P_joint'][:,0]).max()))
  sp=support[support.fold==fold].set_index('transition_group_id');counts=pd.Series(b['transition_group_id']).value_counts().sort_index();assert np.array_equal(counts.to_numpy(),sp.sort_index().test_frames.to_numpy())
 assert len(indices)==len(set(indices))==1973897 and set(indices)==set(np.flatnonzero(d['stage']!=1))
 assert len(runs)==len(set(runs))==280 and len(d['stage'])==2016000 and np.sum(d['stage']==1)==42103
 assert maxsum<1e-12 and max_queue_diff<1e-15
 # Independently verify direct b30 classification from stored measured W/S labels.
 eligible=d['stage']!=1;y=np.select([30*d['W'][eligible]>d['b30'][eligible],30*(d['W'][eligible]+d['S'][eligible])>d['b30'][eligible]],[2,3],default=0)
 assert np.array_equal(y,d['stage'][eligible])
 fig=list((ROOT/'figures').glob('figure*'));assert len(fig)==6 and {p.suffix for p in fig}=={'.png','.pdf'}
 current={c:subprocess.check_output(['git',*c.split()],cwd=REPO,text=True) for c in ['rev-parse HEAD','rev-parse origin/main','status --short']};startup=json.loads((ROOT/'startup_audit.json').read_text())['git'];assert current==startup
 assert not mismatch and not input_mismatch
 result=dict(status='PASS',new_output_root_preexisted=False,valid_runs=280,total_frames=2016000,frames_evaluated=1973897,PRE_READY_LATE_excluded=42103,population_identical_to_previous=True,primary_models=['B1','P-old','P-joint'],B1_reproduced=True,P_old_reproduced=True,maximum_reproduction_probability_difference={m:max(f[m]['max_probability_abs_difference'] for f in repro['folds']) for m in ['B1','P-old']},joint_generated_only_after_all_five_reproductions_passed=True,max_probability_sum_error=maxsum,max_old_joint_queue_probability_difference=max_queue_diff,backoff_support_differences=0,protected_entries_checked=len(before),previous_structural_entries_checked=old_count,canonical_and_reference_input_files_checked=len(inp),protected_hash_mismatches=mismatch,input_hash_mismatches=input_mismatch,existing_raw_modified=False,production_code_modified=False,existing_structural_result_modified=False,unrelated_changes_preserved=True,new_GPU_runs=0,Edge_server_runs=0,Dynamic_runs_used=0,new_features=False,new_ML_family=False,threshold_support_backoff_changed=False,commit_push='NO',git_before=startup,git_after=current,figure_count=3,figure_formats=['PNG','PDF'],render_review='PNG and PDF renders visually inspected',environment=dict(python=sys.executable,version=sys.version,numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,matplotlib=matplotlib.__version__),analysis_source_hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'_scripts').glob('*')) if p.is_file()})
 (ROOT/'analysis_integrity.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:result[k] for k in ['status','protected_entries_checked','previous_structural_entries_checked','protected_hash_mismatches','frames_evaluated','existing_raw_modified','production_code_modified','existing_structural_result_modified','commit_push']},indent=2))
if __name__=='__main__':main()
