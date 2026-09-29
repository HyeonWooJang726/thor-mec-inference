import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'))
from run_campaign import main
if __name__=='__main__':raise SystemExit(main('B',__file__))
