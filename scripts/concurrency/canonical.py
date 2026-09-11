#!/usr/bin/env python3
"""Route canonical tools to their immutable, checkpointed source snapshots.

This adapter only resolves imports and script invocation paths. All source pins,
output collision checks, timing, termination, and analysis logic remain intact.
"""
import argparse
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from script_paths import REPO, configure
configure()

ROOT = REPO / 'results/local_canonical_c2'
TOOLS = {
    'profile': 'code/profile_fullsource.py',
    'run': 'code/run_fullsource.py',
    'plot': 'analysis/plot_figures.py',
    'analyze': 'analysis/analyze.py',
    'temporal': 'analysis/temporal.py',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=TOOLS)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    source = ROOT / TOOLS[args.tool]
    sys.path[:0] = [str(ROOT / 'code'), str(ROOT / 'analysis')]
    sys.argv = [str(source), *args.arguments]
    runpy.run_path(str(source), run_name='__main__')


if __name__ == '__main__':
    main()
