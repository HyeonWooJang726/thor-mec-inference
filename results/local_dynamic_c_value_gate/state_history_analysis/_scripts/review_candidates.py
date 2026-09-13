"""Qualify screening candidates without fitting a substantial-effect threshold."""
from pathlib import Path
import pandas as pd
R=Path(__file__).resolve().parents[1];d=pd.read_csv(R/'state_aliasing_candidates.csv')
fields=['difference_start_A','difference_start_ready_queue','difference_start_unfinished_backlog','difference_start_unfinished_slack_p10_ms','difference_start_unfinished_slack_median_ms','difference_start_unfinished_late_count']
def review(r):
 changed=any(pd.notna(r[x]) and r[x]!=0 for x in fields)
 if not changed:return 'NO_DETECTED_BOUNDARY_STATE_DIFFERENCE'
 if r.phase_a==0:return 'STARTUP_CONFOUNDED_STATE_ALIASING_CANDIDATE'
 return 'SMALL_COUNT_CHANGE_REQUIRES_EFFECT_SIZE_REVIEW'
d['review']=d.apply(review,axis=1);d.to_csv(R/'state_aliasing_candidate_review.csv',index=False)
