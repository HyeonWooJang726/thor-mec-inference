"""Recovery-only terminal row bookkeeping; shared by CPU fixtures and live runner."""
from core import *
def checkpoint(root,state):
 state['last_update']=utc();atomic(Path(root)/'continuation_status.json',state)
def success(root,state,row,summary):
 if row['status']!='RUNNING':raise ValueError('success requires RUNNING')
 if summary['integrity']!='PASS' or summary['completed_frames']!=row['expected_frames']:raise ValueError('invalid success summary')
 row.update(status='PASS',completed_frames=summary['completed_frames'],finished_at=utc());checkpoint(root,state)
def failure(root,state,row,error):
 if row is not None and row['status']=='RUNNING':row.update(status='FAIL',reason=f'{type(error).__name__}: {error}')
 state.update(campaign_status='HALTED',halt_reason=f'{type(error).__name__}: {error}',finish_time=utc());checkpoint(root,state)
 path=Path(root)/'HALT_REASON.md'
 with path.open('x') as f:f.write('# Recovery continuation HALTED\n\n'+state['halt_reason']+'\n\nNo retry. Original campaign remains HALTED.\n')
def complete(root,state):
 if not all(r['status']=='PASS' for r in state['rows']):raise ValueError('non-PASS continuation row')
 state.update(campaign_status='COMPLETED',finish_time=utc());checkpoint(root,state)
