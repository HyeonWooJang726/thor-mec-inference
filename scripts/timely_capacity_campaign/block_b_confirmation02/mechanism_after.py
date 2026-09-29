"""Optional post-restore descriptive carry-over replay; never affects C1-C5."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

from grid_config import OUT, order, load_plan


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Secondary output must be under Confirmation02 root')
    load_plan()
    restore=json.loads((OUT/'CPU_RESTORE_READBACK.json').read_text())
    if restore.get('status')!='PASS':
        raise RuntimeError('CPU restore PASS required before secondary audit')
    legacy=OUT.parent/'block_b_grid02/mechanism_audit01/run_audit.py'
    spec=importlib.util.spec_from_file_location('grid02_carryover_readonly',legacy)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.GRID=OUT  # Only source-directory binding; no legacy file is written.
    masks=json.loads((OUT/'CONFIRMATION_MASK_MANIFEST.json').read_text())
    selected={'L200S','L208S','L216A','L200A','L192S'}
    windows=[];slots=[];services=[];recoveries=[]
    for condition in order()[1:]:
        label=f"L{condition['target_service_FPS']}"+('A' if condition['admission_pattern']=='ALIGNED' else 'S')
        if label not in selected:continue
        w,s,sv,r,_=module.compute_run(condition,masks[label])
        windows+=w;slots+=s;services+=sv;recoveries.append(r)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,data in [('per_window_local_dynamics.csv',windows),('per_slot_carryover.csv',slots),
                      ('state_dependent_local_service.csv',services),('backlog_recovery_summary.csv',recoveries)]:
        with (args.output/name).open('x',newline='') as stream:
            writer=csv.DictWriter(stream,list(dict.fromkeys(k for row in data for k in row)))
            writer.writeheader();writer.writerows(data)
    with (args.output/'scope.json').open('x') as stream:
        json.dump({'role':'secondary descriptive only','selected_conditions':sorted(selected),
            'run_count':len(recoveries),'changes_C1_C5':False,
            'legacy_analyzer_read_only':str(legacy)},stream,indent=2)


if __name__=='__main__':main()
