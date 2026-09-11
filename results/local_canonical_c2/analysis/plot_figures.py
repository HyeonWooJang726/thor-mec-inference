#!/usr/bin/env python3
"""Four fresh PNG figures after independent integrity and analysis gates."""
from pathlib import Path
import os,json,csv,argparse,hashlib
D=Path(__file__).resolve().parents[1];A=D/'analysis'
os.environ['MPLCONFIGDIR']=str(A/'.matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from analyze import gate

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--replace-generated',action='store_true',help='Replace only the four final PNGs and their caption manifest.')
 parser.add_argument('--from-derived',action='store_true',help='Use hash-pinned compact inputs and the recorded formal PASS; does not revalidate absent raw frames.')
 args=parser.parse_args()
 if args.from_derived:
  pins=json.loads((A/'plot_inputs_sha256.json').read_text())
  for name,sha in pins.items():assert hashlib.sha256((D/name).read_bytes()).hexdigest()==sha,name
  report=json.loads((D/'formal_integrity_report.json').read_text())
  assert report['validation']=='PASS' and report['valid_runs']==35 and report['frames']==252000
 else:
  gate()
 assert json.loads((A/'analysis_validation.json').read_text())['validation']=='PASS'
 T=json.loads((A/'temporal_analysis.json').read_text());assert T['validation']=='PASS'
 data=json.loads((A/'analysis_data.json').read_text());runs=data['runs'];ks=list(range(1,8));pair=T['selected_transition_pair']
 F=A/'figures';F.mkdir(exist_ok=args.replace_generated)
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
   'axes.grid':True,'grid.alpha':.18,'axes.axisbelow':True,'savefig.dpi':220})
 axis_limits=json.loads((A/'plot_axis_limits.json').read_text())
 blue='#0072B2';red='#D55E00';green='#009E73';orange='#E69F00';manifest=[]
 def series(metric,K=ks):return np.array([[r[metric] for r in runs if r['K']==k] for k in K])
 def err(ax,metric,label,color,K=ks,marker='o'):
  a=series(metric,K);ax.errorbar(K,a.mean(axis=1),yerr=a.std(axis=1,ddof=1),label=label,color=color,marker=marker,capsize=3,lw=1.5)
  ax.set_xticks(K);ax.set_xlabel('Video streams K')
 def bottom_titles(fig,axes,titles=(),*,component_legend=False):
  fig.subplots_adjust(bottom=.36 if component_legend else .23,wspace=.3)
  for title,ax in zip(titles,axes):
   bb=ax.get_position();fig.text((bb.x0+bb.x1)/2,.18 if component_legend else .035,title,ha='center',va='bottom',fontsize=plt.rcParams['axes.titlesize'])
 def save(fig,name,caption):
  for ax,limits in zip(fig.axes,axis_limits[name]):
   assert ax.get_xscale()==limits['xscale'] and ax.get_yscale()==limits['yscale']
   ax.set_xlim(limits['xlim']);ax.set_ylim(limits['ylim'])
  p=F/(name+'.png');fig.savefig(p,bbox_inches='tight');plt.close(fig)
  manifest.append({'figure':name,'path':str(p.relative_to(D)),'caption':caption,'format':'PNG'})
 fig,axes=plt.subplots(1,2,figsize=(10,4.1))
 err(axes[0],'local_latency_mean_ms','Mean',blue);err(axes[0],'local_latency_p95_ms','p95',red,marker='^')
 axes[0].axhline(1000/30,color='black',ls='--',lw=1,label='Candidate deadline: 33.333… ms')
 axes[0].set_yscale('log');axes[0].set_ylabel('Local latency (ms, log scale)');axes[0].legend(fontsize=8)
 err(axes[1],'deadline_miss_pct','Deadline miss',red);axes[1].set_ylabel('Candidate deadline misses (%)');axes[1].set_ylim(-3,105)
 bottom_titles(fig,axes,['Local latency','Deadline QoS']);save(fig,'figure_1_local_qos','Canonical C2 only. Mean and p95: arithmetic means of five run statistics; error bars sample SD. Individual run statistics remain in the accompanying tables. Deadline computed exactly from integer ns; candidate cadence deadline, not application SLA. Log latency axis retains all K without excluding startup.')
 # All components remain in ms. Split high-load scale only when its mean dwarfs lower K.
 ratio=series('local_latency_mean_ms')[-1].mean()/series('local_latency_mean_ms')[-2].mean()
 groups=[ks[:6],[7]] if ratio>3 else [ks]
 fig,axes=plt.subplots(1,len(groups),figsize=(10 if len(groups)==2 else 7,4.2),squeeze=False,gridspec_kw={'width_ratios':[3,1]} if len(groups)==2 else None)
 axes=list(axes[0]);labels=['Start lag','Front end','Inference queue wait','Inference service'];colors=['#999999','#56B4E9',red,green]
 for ax,K in zip(axes,groups):
  bottom=np.zeros(len(K))
  for comp,label,color in zip(['start_lag','front_end','queue_wait','inference'],labels,colors):
   values=series(comp+'_mean_ms',K).mean(axis=1);ax.bar(K,values,bottom=bottom,color=color,label=label);bottom+=values
  ax.set_xticks(K);ax.set_xlabel('Video streams K');ax.set_ylabel('Mean per-frame local latency (ms)');ax.set_ylim(bottom=0)
 fig.legend(labels,loc='lower center',bbox_to_anchor=(.5,.015),ncol=4,frameon=False,fontsize=10.2);fig.subplots_adjust(top=.88)
 bottom_titles(fig,axes,component_legend=True);save(fig,'figure_2_latency_decomposition','Each stacked height is the mean of five run-level component means. All components are per-frame wall-clock latency, in ms; independent K7 axis used only for readability if necessary. Mean components add exactly; component percentiles are never added.')
 with (A/'temporal_timeline_1s.csv').open() as f:timeline=list(csv.DictReader(f))
 tr=T['runs'];fig,axes=plt.subplots(1,3,figsize=(13,4.3))
 x=np.arange(2);width=.32
 for j,(metric,label,color) in enumerate([('ready_span_ms_mean','Mean',blue),('ready_span_ms_p95','p95',red)]):
  a=np.array([[r[metric] for r in tr if r['K']==k] for k in pair]);pos=x+(j-.5)*width
  axes[0].bar(pos,a.mean(axis=1),width,yerr=a.std(axis=1,ddof=1),capsize=3,label=label,color=color)
 axes[0].set_xticks(x,[f'K{k}' for k in pair]);axes[0].set_ylabel('Within-period ready-time span (ms)');axes[0].legend(fontsize=8)
 measures=['boundary_prior_waiting_positive_pct','boundary_prior_active_positive_pct','next_first_ready_prior_unfinished_positive_pct']
 names=['Waiting at\nboundary','Active at\nboundary','Prior unfinished at\nnext first-ready'];x=np.arange(3)
 for i,(k,col) in enumerate(zip(pair,[blue,red])):
  a=np.array([[r[m] for r in tr if r['K']==k] for m in measures])
  axes[1].bar(x+(i-.5)*width,a.mean(axis=1),width,yerr=a.std(axis=1,ddof=1),capsize=3,label=f'K{k}',color=col)
 axes[1].set_xticks(x,names,fontsize=8);axes[1].set_ylabel('Periods with carry-over (%)');axes[1].set_ylim(0,108);axes[1].legend(fontsize=8)
 for k,col in zip(pair,[blue,red]):
  for rep in range(1,6):
   rows=[r for r in timeline if int(r['K'])==k and r['run_id']==f'run{rep:02d}']
   axes[2].plot([float(r['second'])+.5 for r in rows],[float(r['waiting_time_mean']) for r in rows],color=col,alpha=.65,lw=.9,label=f'K{k}' if rep==1 else None)
 axes[2].set_xlabel('Actual time relative to t0 (s)');axes[2].set_ylabel('Waiting queue: 1 s time mean');axes[2].set_ylim(bottom=0);axes[2].legend(fontsize=8)
 bottom_titles(fig,axes,['Arrival-to-ready dispersion','Waiting and active are distinct','All five runs; startup included']);save(fig,'figure_3_temporal_queue',f'Observed transition K{pair[0]}→K{pair[1]}. Ready span is max(r)-min(r) for K frames in one logical period. Boundary is t0+floor((j+1)*1e9/30); counts earlier logical IDs only. Waiting r<=t<s excludes active s<=t<c. Next first-ready checks all prior unfinished work, including not-yet-ready work. Boundary fractions use 1800 periods; next-first-ready fractions 1799. Bars: five run-level mean ± sample SD. Right: separate exact event-integrated one-second queue traces, never sampled depth. No sum of overlapping service times is interpreted as capacity.')
 fig,axes=plt.subplots(1,2,figsize=(10,5.2))
 err(axes[0],'deadline_miss_pct','Deadline miss',red);axes[0].set_ylabel('Candidate deadline misses (%)');axes[0].set_ylim(-3,105)
 err(axes[1],'queue_wait_mean_ms','Queue wait',red);err(axes[1],'inference_mean_ms','Inference service',green,marker='s')
 axes[1].set_ylabel('Mean per-frame duration (ms, log scale)');axes[1].set_yscale('log')
 handles,legend_labels=axes[1].get_legend_handles_labels()
 fig.legend(handles,legend_labels,loc='lower center',bbox_to_anchor=(.5,.015),ncol=2,frameon=False,fontsize=9)
 for ax in axes:ax.axvspan(pair[0],pair[1],color=orange,alpha=.1)
 bottom_titles(fig,axes,['QoS degradation with concurrent inference','Queueing versus service duration'],component_legend=True);save(fig,'figure_4_concurrency_queue_deadline','C2-safe motivation summary. Left: exact candidate deadline miss by K. Right: per-frame queue wait and inference service duration, not period service sums or GPU demand. Shading marks the selected observed transition. Five-run means and sample SD retained; individual values remain in accompanying tables. Concurrent outstanding host intervals do not prove physical GPU kernel overlap.')
 with (A/'figure_manifest.json').open('w' if args.replace_generated else 'x') as f:json.dump({'validation':'PASS','PNG_only':True,'old_figures_modified':False,'period_service_sum_reused':False,'figures':manifest},f,indent=2)
 print('Generated four PNG figures')
if __name__=='__main__':main()
