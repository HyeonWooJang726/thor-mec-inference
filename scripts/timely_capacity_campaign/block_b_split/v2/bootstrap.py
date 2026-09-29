"""Resolve frozen Thor modules; Edge bundle falls back to its own portable files."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=Path(__file__).resolve().parents[4]
COMMON=ROOT/'scripts/timely_capacity_campaign/common'
if (HERE/'campaign_config.py').is_file():sys.path.insert(0,str(HERE))
elif COMMON.is_dir():sys.path.insert(0,str(COMMON))
import campaign_config as frozen
OUT=ROOT/'results/timely_capacity_campaign/block_b_split'
V2=OUT/'v2'
