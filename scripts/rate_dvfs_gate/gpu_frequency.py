#!/usr/bin/env python3
"""Gate-only GPC control. No sudo, governor or nvpmodel changes.

`set MHz` holds the pin until SIGINT/SIGTERM, then restores. Import pinned()
for a scoped workload. `restore` restores the user-specified default range.
"""

import json
import os
from pathlib import Path
import subprocess
import time
import argparse
import signal
from contextlib import contextmanager
from datetime import datetime, timezone


GPC = Path('/sys/class/devfreq/gpu-gpc-0')
POINTS = {'LOW': 945000000, 'MID': 1260000000, 'HIGH': 1575000000}
DEFAULT_MIN, DEFAULT_MAX = 315000000, 1575000000


def inspect():
    result = {
        'schema_version': 1,
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'observation_monotonic_ns': time.monotonic_ns(),
        'provenance': 'read-only host observation; no switching or GPU workload',
        'uid': os.getuid(),
        'interface': str(GPC),
        'switching_attempted': False,
        'switching_samples': [],
        'command_to_observed_delay_ms': None,
        'requested_to_actual_verified': False,
        'set_method': 'candidate only: pin min_freq=max_freq to a supported Hz value; untested',
        'readback_method': str(GPC / 'cur_freq'),
        'errors': [],
    }
    try:
        power = subprocess.run(['nvpmodel', '-q'], text=True, capture_output=True,
                               timeout=10, check=False)
        result['nvpmodel'] = {'returncode': power.returncode,
                              'stdout': power.stdout, 'stderr': power.stderr}
        if power.returncode or 'NV Power Mode: MAXN' not in power.stdout:
            result['errors'].append('MAXN could not be confirmed; no mode change attempted')
    except (OSError, subprocess.TimeoutExpired) as error:
        result['errors'].append(f'nvpmodel: {error}')

    observed = {}
    for name in ('available_frequencies', 'available_governors', 'governor',
                 'min_freq', 'max_freq', 'cur_freq'):
        try:
            observed[name] = (GPC / name).read_text().strip()
        except OSError as error:
            observed[name] = None
            result['errors'].append(f'{name}: {error}')
    result['raw_sysfs'] = observed
    try:
        frequencies = sorted(set(map(int, (observed['available_frequencies'] or '').split())))
        if not frequencies or frequencies[0] <= 0:
            raise ValueError('no positive supported frequency table')
        result['supported_frequencies_Hz'] = frequencies
        result['supported_frequencies_MHz'] = [f / 1e6 for f in frequencies]
        selected = {name: min(frequencies, key=lambda f: (abs(f - ratio * frequencies[-1]), f))
                    for name, ratio in (('LOW', .6), ('MID', .8), ('HIGH', 1.))}
        if len(set(selected.values())) != 3:
            raise ValueError('three distinct supported points unavailable')
        result['selected_frequencies_MHz'] = {name: f / 1e6 for name, f in selected.items()}
        result['selection_status'] = 'supported candidates; primary plan not frozen'
        result['selection_status'] = 'user-fixed supported Gate points'
        result['available_frequency_minimum_MHz'] = frequencies[0] / 1e6
        result['default_allowed_minimum_MHz'] = DEFAULT_MIN / 1e6
        result['maximum_MHz'] = frequencies[-1] / 1e6
        result['current_allowed_minimum_MHz'] = int(observed['min_freq']) / 1e6
        result['current_allowed_maximum_MHz'] = int(observed['max_freq']) / 1e6
    except (ValueError, TypeError) as error:
        result['errors'].append(f'frequency table: {error}')

    permissions = {}
    for name in ('min_freq', 'max_freq'):
        path = GPC / name
        try:
            stat = path.stat()
            permissions[name] = {'path': str(path), 'uid': stat.st_uid,
                                 'gid': stat.st_gid, 'mode': oct(stat.st_mode & 0o777),
                                 'writable_by_current_user': os.access(path, os.W_OK)}
        except OSError as error:
            result['errors'].append(f'permission {name}: {error}')
    result['permissions'] = permissions
    if result['errors']:
        result['status'] = 'FREQUENCY_CONTROL_UNAVAILABLE'
    elif not all(p['writable_by_current_user'] for p in permissions.values()):
        result['status'] = 'FREQUENCY_CONTROL_PERMISSION_REQUIRED'
    else:
        result['status'] = 'FREQUENCY_SWITCHING_NOT_TESTED'
    return result


def read_range():
    return {name: int((GPC / name).read_text()) for name in ('min_freq', 'max_freq', 'cur_freq')}


def require_control():
    capability = inspect()
    if capability['status'] != 'FREQUENCY_SWITCHING_NOT_TESTED':
        raise PermissionError(json.dumps(capability))
    if not set(POINTS.values()) <= set(capability['supported_frequencies_Hz']):
        raise RuntimeError('Gate frequencies not supported')


def _range(minimum, maximum):
    """Expand the existing range before contraction; check every final bound."""
    current = read_range()
    def write(name, value):
        (GPC / name).write_text(str(value))
    if minimum > current['max_freq']:
        write('max_freq', maximum)
        write('min_freq', minimum)
    else:
        # Lowering, restore, or a target already inside the current range.
        write('min_freq', minimum)
        write('max_freq', maximum)
    observed = read_range()
    if (observed['min_freq'], observed['max_freq']) != (minimum, maximum):
        raise RuntimeError(f'frequency range mismatch: {observed}')
    return observed


def set_frequency(mhz):
    target = int(mhz) * 1000000
    if target not in POINTS.values() or mhz != target / 1000000:
        raise ValueError('Only 945, 1260, 1575 MHz are allowed')
    require_control()
    return _range(target, target)


def restore():
    require_control()
    return _range(DEFAULT_MIN, DEFAULT_MAX)


@contextmanager
def pinned(mhz=None):
    require_control()
    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f'signal {signum}')
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        if mhz is not None:
            set_frequency(mhz)
        yield
    finally:
        # Prevent a second Ctrl-C from interrupting the two restoration writes.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            restore()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='inspect', choices=('inspect', 'set', 'restore'))
    parser.add_argument('mhz', nargs='?', type=int, choices=(945,1260,1575))
    args = parser.parse_args()
    if args.action == 'inspect':
        capability = inspect()
        print(json.dumps(capability, indent=2))
        raise SystemExit({'FREQUENCY_CONTROL_PERMISSION_REQUIRED': 2,
                         'FREQUENCY_CONTROL_UNAVAILABLE': 3}.get(capability['status'], 0))
    elif args.action == 'restore':
        print(json.dumps(restore()))
    else:
        if args.mhz is None:
            parser.error('set requires MHz')
        try:
            with pinned(args.mhz):
                print(json.dumps(read_range()), flush=True)
                while True:
                    signal.pause()
        except KeyboardInterrupt:
            print(json.dumps({'restored': read_range()}))
