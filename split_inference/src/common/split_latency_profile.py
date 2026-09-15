"""CPU-only schedule, raw schema and strict offline duration accounting."""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from . import split_tensor_protocol as wire

NA = 'NA'
SCHEMA = 'single-flight-split-latency-v1'
SCOPE = 'single-flight closed-loop split-inference baseline'
IDENTITY = {
    'canonical_sha256': 'dcac15dc687d43926f62a7942918dc73d11372abbb612352336b4d5840ca4710',
    'checkpoint_sha256': 'dd5fe13b1d60ec15317ccc8ca158186e134d3366c3dde9cb9a4e301f2dc66c74',
    'selection_sha256': 'f198e9fd3da063f0f4ae66dff1d6c76fdb66c7875abae88d462b37f96d338bc2',
    'evidence_sha256': '5706419efb22bd224d7c1b4bac5cceb22d479c3ec1336cc4e9cbb467301bf794',
    'manifest_sha256': '55784ef6efb555b5bfe48f1f939dca2eb721df32a773d4d8299c0018f15e737d',
    'partitions_sha256': 'f072436d18e672e9c6cdca4142c09d7238322675c290023449bc2ba08e1d48af',
}
ORDER_FIELDS = ['request_id', 'phase', 'round', 'iteration', 'sample_id', 'split_point']
TENSOR_FIELDS = ['activation_shape', 'payload_bytes', 'request_payload_sha256',
                 'output_shape', 'response_payload_bytes', 'response_payload_sha256']
CLIENT_FIELDS = ORDER_FIELDS + ['network_used'] + TENSOR_FIELDS + [
    'device_inference_wall_ms', 'device_inference_cuda_ms', 'remote_roundtrip_ms',
    'e2e_inference_ms', 'success', 'error']
SERVER_FIELDS = ORDER_FIELDS + TENSOR_FIELDS + [
    'edge_inference_wall_ms', 'edge_inference_cuda_ms', 'success', 'error']
CORRECT_FIELDS = ORDER_FIELDS + ['output_shape', 'finite', 'top1', 'reference_top1',
    'top1_matches', 'max_abs_error', 'mean_abs_error', 'max_rel_error', 'assert_close_passed', 'error']
MERGED_FIELDS = CLIENT_FIELDS + ['edge_inference_wall_ms', 'edge_inference_cuda_ms',
                               'device_inference_ms', 'edge_inference_ms', 'offloading_overhead_ms']
METRICS = {
    'device_inference_ms': 'device-side inference',
    'edge_inference_ms': 'edge-side inference',
    'offloading_overhead_ms': 'offloading overhead',
    'e2e_inference_ms': 'E2E inference latency',
    'device_inference_cuda_ms': 'device-side inference (CUDA Event auxiliary)',
    'edge_inference_cuda_ms': 'edge-side inference (CUDA Event auxiliary)',
    'remote_roundtrip_ms': 'activation-ready to CPU logits roundtrip',
}
SUMMARY_FIELDS = ['split_point', 'aggregation', 'round', 'metric', 'term', 'count',
    'mean', 'sample_standard_deviation', 'p50', 'p95', 'p99', 'min', 'max', 'provenance', 'interpretation']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def config(mode, run_id):
    require(mode in ('formal', 'pilot'), 'unknown profile mode')
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', run_id) is not None, 'invalid/missing run ID')
    return {'schema': SCHEMA, 'run_id': run_id, 'mode': mode,
            'sample_ids': list(range(300)) if mode == 'formal' else [0, 149, 299],
            'split_points': list(range(10)) if mode == 'formal' else [0, 4, 8, 9],
            'preflight_sample_ids': [0, 149, 299], 'warmup_per_split': 32 if mode == 'formal' else 2,
            'rounds': 10 if mode == 'formal' else 1, 'image_order': 'committed selection order, every round',
            'concurrency': 1, 'outstanding_requests': 1, 'verify_payload': True,
            'protocol_version': 2, 'header_bytes': 48, 'trailer_bytes': 32}


def schedule(cfg):
    """P9 consumes a local request ID; these IDs must be absent from Server CSV."""
    require(cfg == config(cfg['mode'], cfg['run_id']), 'configuration differs from the declared preset')
    rid = 0
    phases = [('preflight', 0, cfg['preflight_sample_ids']),
              ('warmup', 0, [cfg['preflight_sample_ids'][i % 3] for i in range(cfg['warmup_per_split'])])]
    phases += [('measurement', r, cfg['sample_ids']) for r in range(1, cfg['rounds'] + 1)]
    for phase, round_id, samples in phases:
        for iteration, sid in enumerate(samples):
            for point in cfg['split_points']:
                rid += 1
                yield dict(zip(ORDER_FIELDS, [rid, phase, round_id, iteration, sid, point]))


def counts(cfg, network=False):
    return dict(Counter(r['phase'] for r in schedule(cfg) if not network or r['split_point'] < 9))


def milliseconds(value, name):
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name}: missing/invalid duration {value!r}') from exc
    require(math.isfinite(result) and result >= 0, f'{name}: nonfinite/negative duration {value!r}')
    return result


def integer(value, name):
    require(re.fullmatch(r'0|[1-9][0-9]*', str(value)) is not None, f'{name}: invalid integer')
    return int(value)


def shape(value, expected, name):
    actual = json.loads(value)
    require(isinstance(actual, list) and all(type(n) is int for n in actual)
            and actual == list(expected), f'{name}: shape mismatch')


def indexed(rows, name):
    result = {}
    for row in rows:
        rid = integer(row['request_id'], name + ' request ID')
        require(rid not in result, f'{name}: duplicate request ID {rid}')
        result[rid] = row
    return result


def validate_manifests(client, server):
    cfg = client['config']
    require(cfg == config(cfg['mode'], cfg['run_id']) == server['config'], 'run/config mismatch')
    require(client['role'] == 'client' and server['role'] == 'server', 'endpoint roles')
    for m in (client, server):
        require(m['status'] == 'passed' and m['shutdown'] == 'CLOSE/BYE', 'run failed/incomplete shutdown')
        require(m['identity'] == IDENTITY, 'model/checkpoint/selection/evidence/group hash mismatch')
        require(m['correctness_tolerance'] == {'rtol': 1e-4, 'atol': 1e-5}, 'correctness tolerance changed')
        require(m['connections'] == m['handshakes'] == m['model_loads'] == 1, 'connection/handshake/load count')
        require(m['retries'] == 0 and m['fallback'] is False and m['failed_requests'] == 0, 'retry/failure/fallback')
        require(m['phase_counts'] == counts(cfg, network=m['role'] == 'server'), 'manifest phase counts')
    require(client['source_sha256'] and client['source_sha256'] == server['source_sha256'], 'endpoint source hash mismatch')
    return cfg


def merge_rows(client, server, correct, client_manifest, server_manifest):
    cfg = validate_manifests(client_manifest, server_manifest)
    plan = list(schedule(cfg))
    ci, si, vi = indexed(client, 'client'), indexed(server, 'server'), indexed(correct, 'correctness')
    require(set(ci) == {p['request_id'] for p in plan}, 'client request IDs missing/extra')
    require(set(si) == {p['request_id'] for p in plan if p['split_point'] < 9}, 'server request IDs missing/extra/P9')
    require(set(vi) == {p['request_id'] for p in plan if p['phase'] == 'preflight'}, 'correctness request IDs missing/extra')
    # Preserve order as a further single-flight evidence check, not just set equality.
    require(list(ci) == sorted(ci) and list(si) == sorted(si), 'request order is not strictly increasing')
    merged = []
    for planned in plan:
        rid, point = planned['request_id'], planned['split_point']
        c, s = ci[rid], si.get(rid)
        for name, row in [('client', c)] + ([('server', s)] if s is not None else []):
            for key in ORDER_FIELDS:
                require(str(row[key]) == str(planned[key]), f'{name} ID {rid}: {key} mismatch')
            require(str(row['success']).lower() == 'true' and row['error'] == '', f'{name} ID {rid}: failed row')
            shape(row['activation_shape'], wire.SHAPES[point], f'{name} ID {rid} activation')
            shape(row['output_shape'], wire.LOGITS_SHAPE, f'{name} ID {rid} logits')
        device_wall = milliseconds(c['device_inference_wall_ms'], f'ID {rid} device wall')
        device_cuda = milliseconds(c['device_inference_cuda_ms'], f'ID {rid} device CUDA')
        e2e = milliseconds(c['e2e_inference_ms'], f'ID {rid} E2E')
        require(e2e >= device_wall, f'ID {rid}: E2E shorter than device-side inference')
        if point == 0:
            require(device_wall == device_cuda == 0, f'ID {rid}: P0 must have no device DNN execution')
        result = dict(c, device_inference_ms=device_wall)
        if point == 9:
            require(str(c['network_used']).lower() == 'false' and c['remote_roundtrip_ms'] == NA, 'P9 network/remote field')
            require(integer(c['payload_bytes'], 'P9 payload') == integer(c['response_payload_bytes'], 'P9 response') == 0, 'P9 wire bytes')
            require(c['request_payload_sha256'] == c['response_payload_sha256'] == NA, 'P9 wire hashes')
            result.update(edge_inference_wall_ms=NA, edge_inference_cuda_ms=NA,
                          edge_inference_ms=NA, offloading_overhead_ms=NA)
        else:
            require(str(c['network_used']).lower() == 'true', f'ID {rid}: network flag')
            for key in TENSOR_FIELDS:
                require(c[key] == s[key], f'ID {rid}: client/server {key} mismatch')
            require(integer(c['payload_bytes'], 'payload') == math.prod(wire.SHAPES[point]) * 4, f'ID {rid}: payload bytes')
            require(integer(c['response_payload_bytes'], 'response') == 4000, f'ID {rid}: response bytes')
            for key in ['request_payload_sha256', 'response_payload_sha256']:
                require(re.fullmatch(r'[0-9a-f]{64}', c[key]) is not None, f'ID {rid}: missing/invalid SHA-256')
            remote = milliseconds(c['remote_roundtrip_ms'], f'ID {rid} remote')
            edge = milliseconds(s['edge_inference_wall_ms'], f'ID {rid} edge wall')
            cuda = milliseconds(s['edge_inference_cuda_ms'], f'ID {rid} edge CUDA')
            overhead = remote - edge
            milliseconds(overhead, f'ID {rid} offloading overhead')  # Fail; never clamp/substitute/drop.
            require(math.isclose(device_wall + remote, e2e, rel_tol=1e-12, abs_tol=1e-9), f'ID {rid}: client duration boundaries do not close')
            result.update(edge_inference_wall_ms=edge, edge_inference_cuda_ms=cuda,
                          edge_inference_ms=edge, offloading_overhead_ms=overhead)
        if planned['phase'] == 'preflight':
            v = vi[rid]
            require(all(str(v[k]) == str(planned[k]) for k in ORDER_FIELDS), f'ID {rid}: correctness identity')
            shape(v['output_shape'], wire.LOGITS_SHAPE, 'correctness logits')
            require(all(str(v[k]).lower() == 'true' for k in ['finite', 'top1_matches', 'assert_close_passed'])
                    and v['error'] == '', f'ID {rid}: correctness failure')
            require(integer(v['top1'], 'top1') == integer(v['reference_top1'], 'reference top1') < 1000, 'top1 mismatch')
            for key in ['max_abs_error', 'mean_abs_error', 'max_rel_error']:
                milliseconds(v[key], key)
        merged.append(result)
    return merged


def percentile(values, q):
    ordered = sorted(values)
    offset = (len(ordered) - 1) * q
    low, high = math.floor(offset), math.ceil(offset)
    return ordered[low] + (ordered[high] - ordered[low]) * (offset - low)


def summarize(merged, cfg, provenance='measured'):
    rows = [r for r in merged if r['phase'] == 'measurement']
    output = []
    for point in cfg['split_points']:
        for round_id in [None] + list(range(1, cfg['rounds'] + 1)):
            group = [r for r in rows if int(r['split_point']) == point
                     and (round_id is None or int(r['round']) == round_id)]
            expected = len(cfg['sample_ids']) * (cfg['rounds'] if round_id is None else 1)
            require(len(group) == expected, 'summary measurement count mismatch')
            for metric, term in METRICS.items():
                values = [milliseconds(r[metric], metric) for r in group if r[metric] != NA]
                require(len(values) == (0 if point == 9 and metric in (
                    'edge_inference_ms', 'offloading_overhead_ms', 'edge_inference_cuda_ms', 'remote_roundtrip_ms') else expected), 'summary missing timing')
                row = dict(split_point=point, aggregation='pooled' if round_id is None else 'round',
                           round=NA if round_id is None else round_id, metric=metric, term=term,
                           count=len(values), provenance=provenance,
                           interpretation='descriptive samples; no independent-environment tail guarantee or confidence interval')
                row.update(dict.fromkeys(['mean', 'sample_standard_deviation', 'p50', 'p95', 'p99', 'min', 'max'], NA))
                if values:
                    row.update(mean=statistics.mean(values),
                               sample_standard_deviation=statistics.stdev(values) if len(values) > 1 else NA,
                               p50=percentile(values, .5), p95=percentile(values, .95), p99=percentile(values, .99),
                               min=min(values), max=max(values))
                output.append(row)
    return output


def read_csv(path, fields):
    with Path(path).open(newline='') as f:
        reader = csv.DictReader(f)
        require(reader.fieldnames == fields, f'{path}: CSV schema mismatch')
        rows = list(reader)
    require(all(set(r) == set(fields) and all(v is not None for v in r.values()) for r in rows), 'malformed CSV row')
    return rows


def write_csv(path, rows, fields):
    with Path(path).open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
