#!/usr/bin/env python3
"""Exactly 35 canonical fixed C2 full-source runs; fail fast."""
import argparse,json,shlex,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1]
sys.path.append(str(REPO/'scripts'))
from screening_metrics import validate_run
from run_local_concurrency_formal_control import preflight
from run_local_concurrency_trtexec_probe import save,digest,ENGINE
ORDER=[[(2,((rep+offset)%7)+1) for offset in range(7)] for rep in range(5)]
def source_hashes():
    paths=list((ROOT/'code').glob('*.py'))+[REPO/'scripts'/p.name for p in (ROOT/'source_snapshot').glob('*.py')]
    return {str(p.relative_to(REPO)):digest(p) for p in paths}
def command(c,k,rep=0):
    assert c == 2 and 1 <= k <= 7 and 1 <= rep <= 5
    run_id=f'run{rep:02d}'
    output=ROOT/f'k{k}'/run_id
    argv=['/usr/bin/python3','-B',str((ROOT/'code/profile_fullsource.py').relative_to(REPO)),
          '--formal','--concurrency',str(c),'--k',str(k),
          '--frames-per-stream','1800','--run-id',run_id,'--output-dir',str(output)]
    return argv,output,run_id

def plan():
    return {'artifact_class':'CANONICAL STATIC C2 LOCAL','C':[2],'K':list(range(1,8)),
        'repetitions':5,'fps':30,'frames_per_stream':1800,'offered_duration_s':60,
        'expected_runs':35,'expected_frames':252000,'batch':1,'engine':ENGINE,'engine_sha256':digest(REPO/ENGINE),
        'power':'MAXN','DVFS':'unlocked','jetson_clocks':'OFF','CUDA_Graph':False,
        'warmup':'NONE','sample_exclusion':'NONE','deliberate_cooldown':'NONE','drop':'NONE',
        'candidate_deadline':'local_latency_ns * 30 > 1000000000; candidate, not final SLA',
        'source_termination':'natural full-source bus EOS for every source AND complete acquisition/drain/clean joins/NULL shutdown',
        'runtime_watchdog_s':300,'outer_child_timeout_s':420,
        'watchdog_source':'same 300-second runtime watchdog as existing full-source formal; no change after failure',
        'runs':[{'sequence':(rep-1)*7+pos,'C':c,'K':k,'rep':rep,'argv':command(c,k,rep)[0]}
                for rep,group in enumerate(ORDER,1) for pos,(c,k) in enumerate(group,1)]}

def one_run(c,k,rep,pinned,engine_sha):
    assert source_hashes()==pinned,'source changed during campaign'
    assert digest(REPO/ENGINE)==engine_sha,'engine changed during campaign'
    argv,output,run_id=command(c,k,rep)
    if output.exists():raise RuntimeError(f'existing run forbidden: {output}')
    label=f'c{c}_k{k}_{run_id}';logs=ROOT/'orchestration'
    save(logs/f'{label}_command.json',{'argv':argv,'exact_command':shlex.join(argv),'cwd':str(REPO)})
    save(logs/f'{label}_environment_before.json',preflight())
    print(f'START {label}',flush=True)
    started,utc=time.monotonic_ns(),time.time_ns()
    with (logs/f'{label}_stdout.log').open('x') as out,(logs/f'{label}_stderr.log').open('x') as err:
        try:
            child=subprocess.run(argv,cwd=REPO,stdout=out,stderr=err,timeout=420)
            code,error=child.returncode,None
        except subprocess.TimeoutExpired:
            code,error=-1,'outer watchdog timeout; campaign stops, no retry'
    save(logs/f'{label}_exit.json',{'exit_code':code,'error':error,'retried':False,
        'started_utc_ns':utc,'finished_utc_ns':time.time_ns(),'wall_clock_duration_s':(time.monotonic_ns()-started)/1e9})
    save(logs/f'{label}_environment_after.json',preflight())
    if output.is_dir():
        for suffix in ('command.json','stdout.log','stderr.log','exit.json','environment_before.json','environment_after.json'):
            shutil.copy2(logs/f'{label}_{suffix}',output/suffix)
        (output/'command.txt').write_text(shlex.join(argv)+'\n')
    if code:raise RuntimeError(f'{label}: exit {code}; campaign stopped; no retry')
    summary,check=validate_run(output,c,k,1800,run_id)
    save(output/'independent_validation.json',check)
    print(f'PASS {label} frames={summary["frames"]} natural_EOS={sum(check["termination"]["eos_observed"])}/{k} '
          f'miss={summary["deadline_miss_pct"]:.4f}% local={summary["local_latency_mean_ms"]:.3f}ms '
          f'queue={summary["queue_wait_mean_ms"]:.3f}ms active={summary["max_active_inferences"]}',flush=True)
    return summary,check

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');args=p.parse_args()
    if not args.execute:print(json.dumps(plan(),indent=2));return
    assert json.loads((ROOT/'regression_result.json').read_text())['validation']=='PASS'
    assert json.loads((ROOT/'runtime_audit.json').read_text())['validation']=='PASS'
    planned=plan();assert len(planned['runs'])==len({(v['C'],v['K'],v['rep']) for v in planned['runs']})==35
    assert sum(v['K']*1800 for v in planned['runs'])==252000
    assert json.loads((ROOT/'formal_plan.json').read_text())==planned
    # Exact plan was saved before execution.
    pinned=source_hashes();save(ROOT/'source_sha256.json',pinned)
    (ROOT/'orchestration').mkdir(exist_ok=False);save(ROOT/'preflight.json',preflight())
    checks=[];current=None
    try:
        for rep,group in enumerate(ORDER,1):
            for c,k in group:
                current={'C':c,'K':k,'rep':rep,'gate':False}
                summary,check=one_run(c,k,rep,pinned,planned['engine_sha256']);checks.append(check)
                save(ROOT/'orchestration'/f'completed_{len(checks):02d}.json',{'completed_runs':len(checks),'latest':summary})
    except Exception as error:
        save(ROOT/'campaign_failure.json',{'status':'INCOMPLETE','reason':str(error),'failed_configuration':current,
            'completed_runs':checks,'retried_runs':0})
        raise
    assert len(checks)==35 and sum(x['frames'] for x in checks)==252000
    save(ROOT/'campaign_completion.json',{'validation':'PASS','valid_runs':35,'frames':252000,'failed_runs':0,
        'retried_runs':0,'runs':checks,'source_unchanged':source_hashes()==pinned})
    print('COMPLETE 35/35 runs / 252000 frames; independent whole-campaign gate required before analysis',flush=True)
if __name__=='__main__':main()
