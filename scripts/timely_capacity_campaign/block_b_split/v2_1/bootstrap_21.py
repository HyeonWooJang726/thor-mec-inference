"""V2.1 imports immutable V2; never changes a frozen source or condition plan."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
V2_SOURCE=HERE.parent/'v2'
sys.path.insert(0,str(V2_SOURCE))
import bootstrap as v2boot
OUT=ROOT/'results/timely_capacity_campaign/block_b_split/v2_1'
PLAN=v2boot.V2/'E_MAX_72/plan.json'
EXPECTED_PLAN_SHA='402ac3935a1397929e657ebb49c6db84bcb27845c4df701b07ba79891f28d117'

