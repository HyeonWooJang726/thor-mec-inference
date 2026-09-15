"""Offline request-ID merge and descriptive latency statistics; no GPU imports."""
import argparse
import json
from pathlib import Path
import traceback

from split_inference.src.common import split_latency_profile as data


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def analyze(client, server, output):
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'status': 'running', 'client': str(client), 'server': str(server),
                'scope': data.SCOPE, 'excluded_samples': 0, 'clamped_samples': 0}
    try:
        cm = json.loads((client / 'run_manifest.json').read_text())
        sm = json.loads((server / 'run_manifest.json').read_text())
        data.require(cm['provenance'] == sm['provenance'] == 'measured', 'analysis requires measured endpoint artifacts')
        for directory in (client, server):
            data.require(not (directory / 'failure_manifest.json').exists(), 'endpoint failure manifest present')
            data.require(not (directory / 'stderr.log').read_bytes(), 'endpoint stderr not empty; review required')
        cr = data.read_csv(client / 'client_raw.csv', data.CLIENT_FIELDS)
        sr = data.read_csv(server / 'server_raw.csv', data.SERVER_FIELDS)
        vr = data.read_csv(client / 'correctness.csv', data.CORRECT_FIELDS)
        merged = data.merge_rows(cr, sr, vr, cm, sm)
        summary = data.summarize(merged, cm['config'])
        data.write_csv(output / 'merged_raw.csv', merged, data.MERGED_FIELDS)
        data.write_csv(output / 'summary_by_split.csv', summary, data.SUMMARY_FIELDS)
        metadata.update(status='passed', run_id=cm['config']['run_id'], config=cm['config'],
                        provenance='measured', research_result=cm['research_result'],
                        client_rows=len(cr), server_rows=len(sr), correctness_rows=len(vr),
                        client_phase_counts=data.counts(cm['config']),
                        server_phase_counts=data.counts(cm['config'], network=True),
                        measurement_p9_rows=sum(r['phase'] == 'measurement' and int(r['split_point']) == 9 for r in cr),
                        integrity='all requests retained; exact IDs, phases, shapes, lengths, hashes, durations and preflight validated',
                        p99_samples_per_split=len(cm['config']['sample_ids']) * cm['config']['rounds'],
                        interpretation='descriptive samples; no independent-environment tail guarantee or confidence interval',
                        source_artifact_sha256={str(p): data.sha(p) for p in [
                            client / 'client_raw.csv', client / 'correctness.csv', client / 'run_manifest.json',
                            server / 'server_raw.csv', server / 'run_manifest.json']})
    except BaseException:
        metadata.update(status='failed', error=traceback.format_exc())
        (output / 'stderr.log').write_text(metadata['error'])
        save(output / 'failure_manifest.json', metadata)
        raise
    finally:
        save(output / 'run_manifest.json', metadata)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New, nonexistent analysis directory')
    args = parser.parse_args()
    result = analyze(args.client, args.server, args.output)
    print(json.dumps({k: result[k] for k in ['status', 'run_id', 'client_rows', 'server_rows', 'correctness_rows', 'client_phase_counts', 'server_phase_counts']}))


if __name__ == '__main__':
    main()
