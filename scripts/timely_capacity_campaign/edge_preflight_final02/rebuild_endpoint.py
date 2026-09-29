"""Offline, one-time Final02 endpoint correction; performs no network or system calls."""
import argparse
import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from pathlib import Path

import config


OLD_SHA = 'b9c8b2b478d1740c677ad57a65f3ba66f7a4fb015cb0bf7e0369e6a18cb427ea'
FAILURE_NAME = 'NETWORK_REACHABILITY_FAILURE_18576305639059.json'
ARCHIVE = config.OUT / 'superseded_endpoint_192_168_0_7'


def dump(path, value, *, exclusive=False):
    with path.open('x' if exclusive else 'w') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def run(edge_ip, hostname):
    if ipaddress.ip_address(edge_ip).version != 4 or not hostname:
        raise ValueError('Explicit IPv4 endpoint and hostname required')
    out = config.OUT
    old = ARCHIVE / 'results/timely_capacity_campaign/v2_2/edge_preflight_final02'
    snapshot = json.loads((ARCHIVE / 'SNAPSHOT_SHA256.json').read_text())
    if config.sha(config.PLAN) != OLD_SHA or config.sha(old / 'plan.json') != OLD_SHA:
        raise RuntimeError('Stale plan not preserved or current plan already revised')
    if (out / 'ENDPOINT_REVISION_RECORD.json').exists() or (out / 'EDGE_ENDPOINT_MANIFEST.json').exists():
        raise RuntimeError('Endpoint revision already performed; no second overwrite')
    forbidden = ('CPU_PIN_READBACK.json', 'CPU_RESTORE_READBACK.json', 'campaign_attempt.json',
                 'NETWORK_REACHABILITY_CHECK.json', 'base', 'extension')
    if any((out / name).exists() for name in forbidden):
        raise RuntimeError('Final02 execution already started; do not revise in place')
    failure = json.loads((out / FAILURE_NAME).read_text())
    failure_rel = str((out / FAILURE_NAME).relative_to(config.ROOT))
    if config.sha(out / FAILURE_NAME) != snapshot['sha256'][failure_rel] \
            or failure['status'] != 'FAIL' or failure['plan_sha256'] != OLD_SHA:
        raise RuntimeError('Original pre-execution failure evidence changed')
    prior = json.loads((old / 'plan.json').read_text())
    old_ip = prior['edge_host']
    if failure['command'] != ['ping', '-c', '2', old_ip] or edge_ip == old_ip:
        raise RuntimeError('Endpoint revision does not match failure provenance')

    manifest = {
        'hostname': hostname, 'edge_ip': edge_ip, 'thor_ip': '192.168.0.189',
        'subnet': '192.168.0.0/24', 'inference_port': 5000,
        'verification_provenance': {
            'source': 'operator-supplied terminal observations; no live command by preparation tool',
            'Edge hostname': 'CY415AINET',
            'Edge hostname -I': edge_ip,
            'Edge ip -br addr': 'eth2 UP ' + edge_ip + '/24',
            'Edge ip route': 'default via 192.168.0.1 dev eth2',
            'Edge to Thor ping': 'PASS to 192.168.0.189',
            'Thor old Edge ping': '0/2 responses, operator observation',
            'observation_timestamp': 'unavailable; not inferred',
        },
        'old_endpoint': old_ip, 'old_endpoint_status': 'stale',
        'old_failure_file': FAILURE_NAME,
        'old_failure_sha256': config.sha(out / FAILURE_NAME),
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'timestamp_scope': 'manifest preparation time, not operator observation time',
    }
    dump(out / 'EDGE_ENDPOINT_MANIFEST.json', manifest, exclusive=True)

    source_map = json.loads((old / 'source_sha256.json').read_text())
    source_map[str(Path(__file__).resolve().relative_to(config.ROOT))] = config.sha(__file__)
    source_map = {name: config.sha(config.ROOT / name) for name in source_map}
    dump(out / 'source_sha256.json', source_map)

    plan = dict(prior)
    plan['edge_host'] = edge_ip
    plan['edge_ip'] = edge_ip
    plan['endpoint_manifest_sha256'] = config.sha(out / 'EDGE_ENDPOINT_MANIFEST.json')
    plan['pre_execution_guards'] = [guard.replace(old_ip, edge_ip)
                                    for guard in prior['pre_execution_guards']]
    changed_old_keys = [key for key in prior if plan[key] != prior[key]]
    if changed_old_keys != ['edge_host', 'pre_execution_guards']:
        raise RuntimeError('Unexpected scientific plan change: ' + str(changed_old_keys))
    dump(config.PLAN, plan)
    new_sha = config.sha(config.PLAN)
    (out / 'plan.sha256').write_text(new_sha + '\n')
    (out / 'edge_bundle/plan.json').write_bytes(config.PLAN.read_bytes())
    bundle = out / 'edge_bundle'
    files = sorted(path for path in bundle.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    (bundle / 'SHA256SUMS').write_text(''.join(config.sha(path) + '  ' + path.name + '\n'
                                             for path in files))
    dump(out / 'BUNDLE_SHA256.json', {path.name: config.sha(path) for path in files})

    old_without_endpoint = {key: value for key, value in prior.items() if key != 'edge_host'}
    new_without_endpoint = {key: value for key, value in plan.items()
                            if key not in ('edge_host', 'edge_ip', 'endpoint_manifest_sha256')}
    new_without_endpoint['pre_execution_guards'] = [guard.replace(edge_ip, old_ip)
                                                     for guard in plan['pre_execution_guards']]
    scientific_pass = old_without_endpoint == new_without_endpoint
    diff = {
        'status': 'SCIENTIFIC_CONDITIONS_UNCHANGED_EXCEPT_ENDPOINT' if scientific_pass else 'FAIL',
        'old_plan_sha256': OLD_SHA, 'new_plan_sha256': new_sha,
        'old_edge_ip': old_ip, 'new_edge_ip': edge_ip,
        'allowed_differences': ['edge_host', 'edge_ip', 'endpoint_manifest_sha256',
                                'IP literal inside pre_execution_guards'],
        'other_fields_exact_equal': scientific_pass,
        'base_order_equal': prior['base_order'] == plan['base_order'],
        'extension_orders_equal': prior['extension_orders'] == plan['extension_orders'],
    }
    dump(out / 'scientific_condition_diff_endpoint.json', diff, exclusive=True)
    if not scientific_pass:
        raise RuntimeError('Scientific condition diff failed')
    dump(out / 'ENDPOINT_REVISION_RECORD.json', {
        'status': 'PRE_EXECUTION_STALE_EDGE_ENDPOINT',
        'old_plan_sha256': OLD_SHA, 'new_plan_sha256': new_sha,
        'old_endpoint': old_ip, 'new_endpoint': edge_ip,
        'failure_file': FAILURE_NAME, 'failure_sha256': config.sha(out / FAILURE_NAME),
        'scientific_workload_started': False, 'CPU_pin_performed': False,
        'attempt_marker_created': False, 'capacity_result': False,
        'old_bundle_and_sources': str(ARCHIVE.relative_to(config.ROOT)),
        'old_plan_state': 'SUPERSEDED_ENDPOINT_STALE_PRESERVED',
    }, exclusive=True)
    print(json.dumps({'new_plan_sha256': new_sha, 'edge_ip': edge_ip,
                      'scientific_condition_diff': diff['status']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--edge-ip', required=True)
    parser.add_argument('--hostname', required=True)
    args = parser.parse_args()
    run(args.edge_ip, args.hostname)
