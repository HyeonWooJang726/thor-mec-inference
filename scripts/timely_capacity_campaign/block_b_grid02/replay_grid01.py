"""Read-only Grid01 warm-up replay through the Grid02 post-drain summary."""
import json
from pathlib import Path

import block_b_summary
from grid_config import OUT, PLAN, ROOT, sha


PRIOR = ROOT / 'results/timely_capacity_campaign/v2_2/block_b_grid01'
RUN = PRIOR / 'BLOCKB01_WARMUP_L200_E40_S'


def replay():
    plan = json.loads(PLAN.read_text())
    condition = plan['order'][0]
    original = json.loads((RUN / 'manifest.json').read_text())
    original_summary = json.loads((RUN / 'summary.json').read_text())
    original_edge = json.loads((RUN / 'edge_final.json').read_text())
    if original_summary.get('integrity_status') != 'INVALID' or \
            original_edge.get('integrity_status') != 'VALID':
        raise RuntimeError('Grid01 provenance changed')
    # The prior process-exit error is a consequence of the prior summary
    # exception. Remove it only from this in-memory replay input.
    manifest = dict(original, errors=[], run_id=condition['run_id'],
                    plan_sha256=sha(PLAN), execution_manifest_sha256=sha(PLAN),
                    placement_schedule=plan['placement'],
                    analysis_class=condition['analysis_class'])
    frames = block_b_summary.read_csv(RUN / 'per_frame.csv.gz')
    power = block_b_summary.read_csv(RUN / 'power_trace.csv.gz')
    replayed = block_b_summary.summarize(manifest, frames, power)
    return {
        'scope': 'CPU/log-only replay; never reclassifies Grid01',
        'input_manifest_sha256': sha(RUN / 'manifest.json'),
        'input_per_frame_sha256': sha(RUN / 'per_frame.csv.gz'),
        'input_power_trace_sha256': sha(RUN / 'power_trace.csv.gz'),
        'input_edge_final_sha256': sha(RUN / 'edge_final.json'),
        'Grid01_original_verdict': original_summary['integrity_status'],
        'Grid01_original_summary_sha256': sha(RUN / 'summary.json'),
        'Grid01_edge_integrity_status': original_edge['integrity_status'],
        'replay_summary': replayed,
        'PASS': replayed.get('integrity_status') == 'VALID' and
                replayed.get('terminal_accounting_status') == 'PASS' and
                replayed.get('true_unfinished_after_drain') == 0 and
                not any('Unplanned pattern/rate' in e for e in replayed.get('errors', [])),
    }


def main():
    result = replay()
    with (OUT / 'GRID01_WARMUP_OFFLINE_REPLAY.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print('Grid01 warm-up offline replay', 'PASS' if result['PASS'] else 'FAIL')
    if not result['PASS']:
        for error in result['replay_summary'].get('errors', [])[:8]:
            print(error[:600])
    return 0 if result['PASS'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
