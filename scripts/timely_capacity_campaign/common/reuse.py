"""Only imports frozen CPU-safe modules; CUDA and sockets remain execution-only."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts/d100_timely_capacity_map'))
import map_common as previous
import run_map_d100 as previous_runner
import analyze_map_d100 as previous_analysis
pruning=previous.pruning
canonical=previous.canonical
prior=previous.prior
replace_once=prior.hybrid.replace_once
