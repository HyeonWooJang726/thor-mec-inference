"""Analysis Revision01 exact code rebound only to the fresh scan02 result root."""
import argparse
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'analysis_revision01'))
sys.path.insert(0, str(HERE.parent))
import analyze_revision as frozen_analysis
from attempt02_config import ROOT, OUT, load_plan, sha


def verify_adapter():
    manifest = json.loads((OUT / 'attempt02_source_sha256.json').read_text())
    for relative, digest in manifest.items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError('Attempt02 source drift: ' + relative)
    frozen_analysis.verify_revision()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mechanism-reviews', type=Path)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Analysis output must be inside fresh scan02 namespace')
    fn = frozen_analysis.prior.require_restore
    fresh_restore = types.FunctionType(fn.__code__, dict(fn.__globals__, OUT=OUT))
    prior = types.SimpleNamespace(**dict(frozen_analysis.prior.__dict__, require_restore=fresh_restore))
    fn = frozen_analysis.main
    namespace = dict(fn.__globals__, OUT=OUT, prior=prior, load_plan=load_plan,
                     verify_revision=verify_adapter)
    return types.FunctionType(fn.__code__, namespace)()


if __name__ == '__main__':
    main()
