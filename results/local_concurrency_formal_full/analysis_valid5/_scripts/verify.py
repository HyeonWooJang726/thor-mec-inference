"""Final CPU-only cross-checks; no acquisition functions imported or invoked."""
import csv,hashlib,json,math,subprocess
from pathlib import Path
from collections import Counter
from analyze import D,ROOT,REPO,sha

def main():
 def read(path):return list(csv.DictReader(path.open()))
 r=read(D/'analysis_per_run.csv');pairs=read(D/'adjacent_c_round_paired_deltas.csv')
 assert len(r)==280 and Counter(x['acquisition_phase'] for x in r)=={'ORIGINAL_CAMPAIGN':279,'POST_CAMPAIGN_REPLACEMENT':1}
 assert len(pairs)==7*7*12*5
 missing=[x for x in pairs if x['delta']=='']
 assert len(missing)==12 and all((x['K'],x['C_low'],x['C_high'],x['original_round_id'])==('2','1','2','4') for x in missing)
 assert all(x['replacement_used']=='False' for x in pairs)
 reference=json.loads((ROOT/'c1/k2/run01/metadata.json').read_text())
 for x in r:
  d=REPO/x['source_artifact'];m=json.loads((d/'metadata.json').read_text());v=json.loads((d/'formal_integrity.json').read_text())
  assert (v['K'],v['C'])==(int(x['K']),int(x['C']))
  assert m['K_list']==[int(x['K'])] and m['concurrency']==int(x['C'])
  for k in ['model','engine_path','engine_sha256','batch_size','frames_per_stream','fps','candidate_deadline_ms','preprocessing_identity','integer_ns_miss_comparison_rule']:
   assert m[k]==reference[k]
  assert v['concurrency']['max_active_inferences']<=int(x['C'])
  if int(x['C'])==1:assert v['concurrency']['max_active_inferences']==1
 pins=json.loads((ROOT/'campaign_code_hashes.json').read_text())['sha256']
 assert all(sha(Path(p))==h for p,h in pins.items())
 original=read(ROOT/'campaign_drift_summary.csv')
 assert all(int(x['valid_cells'])==(55 if x['round_id']=='4' else 56) for x in original)
 table=['## Original 279-valid-run drift reference','',
        'Read directly from unchanged ../campaign_drift_summary.csv. Its original cell centering uses four valid observations for K2/C1 and five elsewhere; this is distinct from the complete 55-cell panel above.','',
        '| Round | Valid cells | Original service centered ms | Original DMR centered pp |','|---|---|---|---|']
 for rd in range(1,6):
  service=next(x for x in original if x['round_id']==str(rd) and x['metric']=='service_mean_ms')
  dmr=next(x for x in original if x['round_id']==str(rd) and x['metric']=='deadline_miss_percent')
  table.append(f"| {rd} | {service['valid_cells']} | {float(service['cell_centered_mean']):+.6f} | {float(dmr['cell_centered_mean']):+.6f} |")
 p=D/'round_drift_analysis.md';base=p.read_text().split('## Original 279-valid-run drift reference')[0].rstrip()
 p.write_text(base+'\n\n'+'\n'.join(table)+'\n')
 expected=['analysis_integrity.json','metric_definitions.md','kc_full_summary.csv','adjacent_c_deltas.csv',
  'adjacent_c_round_paired_deltas.csv','static_best_observed_c_by_k.csv','static_c_regret.csv','dmr_shape_by_k.csv',
  'round_drift_analysis.csv','round_drift_analysis.md','replacement_sensitivity.md','dynamic_transition_candidates.csv','formal_static_concurrency_analysis.md']
 assert all((D/p).is_file() and (D/p).stat().st_size>0 for p in expected)
 for ext in ['png','pdf','svg']:assert len(list((D/'figures').glob('*.'+ext)))==9
 before=json.loads((D/'protected_inputs_before.json').read_text())
 bad=[p for p,h in before.items() if not Path(p).is_file() or sha(Path(p))!=h['sha256']]
 assert not bad,bad
 audit=json.loads((D/'analysis_integrity.json').read_text())
 audit.update(final_verification='PASS',formal_metadata_consistency='PASS',measurement_critical_hashes='MATCH',
     round_pair_rows=len(pairs),missing_pair_rows=len(missing),missing_pair_reason='K2 C1->C2 original Round4; 12 metrics',
     original_drift_reference_sha256=sha(ROOT/'campaign_drift_summary.csv'),originals_hash_mismatches=bad,
     source_script_sha256={p.name:sha(p) for p in (D/'_scripts').glob('*.py')})
 (D/'analysis_integrity.json').write_text(json.dumps(audit,indent=2)+'\n')
 (D/'_scripts/README.md').write_text('CPU-only reproduction into a fresh analysis_valid5 output directory: analyze.py, render.py, verify.py. analyze.py refuses to overwrite existing analysis tables. Original inputs are immutable. No GPU/acquisition command is invoked. Matplotlib uses Agg; its cache stays under this directory.\n')
 print(json.dumps({k:audit[k] for k in ['validation','final_verification','conditions','valid_runs','primary_frames','physical_acquisition_completed_frames','protected_files_checked','hash_mismatches','GPU_runs','verdict']},indent=2))
 print(subprocess.check_output(['git','status','--short'],cwd=REPO,text=True))

if __name__=='__main__':main()
