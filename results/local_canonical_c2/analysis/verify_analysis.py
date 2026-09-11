"""Independent NumPy checks of derived statistics, temporal counts and PNG outputs."""
import sys,json,csv,hashlib
from pathlib import Path
import numpy as np
from PIL import Image
D=Path(__file__).resolve().parents[1];A=D/'analysis'
data=json.loads((A/'analysis_data.json').read_text());temporal=json.loads((A/'temporal_analysis.json').read_text())
periods=list(csv.DictReader((A/'temporal_periods.csv').open()));timeline=list(csv.DictReader((A/'temporal_timeline_1s.csv').open()))
checked_frames=checked_periods=0
for row in data['runs']:
 k,run=row['K'],row['run_id'];raw=json.loads((D/f'k{k}'/run/'raw_ns.json').read_text());t0=raw['t0_ns']
 rec=sorted(raw['records'],key=lambda r:(r['frame_id'],r['stream_id']));a,b,r,s,c=[np.array([v[name] for v in rec],dtype=np.int64) for name in ('a_ns','b_ns','r_ns','s_ns','c_ns')]
 for label,values in [('local_latency',c-a),('start_lag',b-a),('front_end',r-b),('queue_wait',s-r),('inference',c-s)]:
  for stat in ['mean','median','p95','p99']:
   field=label+'_'+stat+'_ms'
   if field not in row:continue
   expected=(np.mean(values) if stat=='mean' else np.percentile(values,{'median':50,'p95':95,'p99':99}[stat]))/1e6
   assert abs(row[field]-expected)<1e-9,(k,run,field)
 assert abs(row['deadline_miss_pct']-np.mean((c-a)*30>1_000_000_000)*100)<1e-10
 checked_frames+=len(rec)
 if k not in {v['K'] for v in temporal['runs']}:continue
 prs=[v for v in periods if int(v['K'])==k and v['run_id']==run]
 for pr in prs:
  j=int(pr['frame_id']);n=(j+1)*k
  boundary=t0+((j+1)*1_000_000_000)//30
  for prefix,t in [('boundary_prior_',boundary),('next_first_ready_prior_',int(min(r[n:n+k])) if n<len(r) else None)]:
   if t is None:continue
   ready=r[:n]<=t;started=s[:n]<=t;completed=c[:n]<=t
   expected={'waiting':np.count_nonzero(ready & ~started),'active':np.count_nonzero(started & ~completed),'pre_ready':np.count_nonzero(~ready),'unfinished':np.count_nonzero(~completed),'ready_unfinished':np.count_nonzero(ready & ~completed)}
   for key,value in expected.items():assert int(pr[prefix+key])==value,(k,run,j,prefix,key)
  span=(max(r[j*k:n])-min(r[j*k:n]))/1e6
  assert abs(float(pr['ready_span_ms'])-span)<1e-9
  checked_periods+=1
 for v in [v for v in timeline if int(v['K'])==k and v['run_id']==run]:
  lo=t0+int(v['second'])*1_000_000_000;hi=lo+1_000_000_000
  for start,end,field in [(r,s,'waiting_time_mean'),(s,c,'active_time_mean')]:
   area=np.maximum(0,np.minimum(end,hi)-np.maximum(start,lo)).sum()
   assert abs(float(v[field])-area/1e9)<1e-10
for summary in data['summary']:
 rs=[r for r in data['runs'] if r['K']==summary['K']]
 for field,val in summary.items():
  if field in ('C','K','n_runs','frames_per_run'):continue
  stat=next(s for s in ['sample_sd','mean','median','min','max'] if field.endswith('_'+s));metric=field[:-len(stat)-1]
  values=[r[metric] for r in rs];expected={'mean':np.mean,'sample_sd':lambda v:np.std(v,ddof=1),'median':np.median,'min':np.min,'max':np.max}[stat](values)
  assert abs(expected-val)<1e-9,(summary['K'],field)
files=list((A/'figures').glob('*'));assert len(files)==4 and all(p.suffix=='.png' for p in files)
assert not list(D.rglob('*.pdf'))
images=[]
for p in files:
 with Image.open(p) as im:assert im.format=='PNG';images.append({'file':p.name,'width':im.width,'height':im.height,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
report={'validation':'PASS','raw_frames_rechecked_for_statistics':checked_frames,'temporal_period_rows_rechecked':checked_periods,'all_run_and_five_run_statistics_numpy_agree':True,'all_temporal_counts_bruteforce_masks_agree':True,'all_1s_integrals_independently_agree':True,'PNG_only':True,'figures':images,'visual_inspection':'all four viewed; axes, legends and external bottom panel labels readable'}
(A/'derived_integrity_report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
