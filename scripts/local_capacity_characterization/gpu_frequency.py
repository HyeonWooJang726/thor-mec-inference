#!/usr/bin/env python3
"""Supported 315..1575 MHz states; reuse historical safe sysfs write ordering."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('_historical_gate_frequency', ROOT/'scripts/rate_dvfs_gate/gpu_frequency.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
GPC = legacy.GPC
read_range = legacy.read_range


def supported():
    return list(map(int,(GPC/'available_frequencies').read_text().split()))


def validate_target(mhz):
    if isinstance(mhz,bool) or not isinstance(mhz,(int,float)) or int(mhz)!=mhz:
        raise ValueError('integer MHz required')
    target = int(mhz)*1000000
    if not 315000000 <= target <= 1575000000 or target not in supported():
        raise ValueError('unsupported or out-of-domain frequency')
    return target


def require_control():
    mode = subprocess.check_output(['nvpmodel','-q'],text=True)
    if 'NV Power Mode: MAXN' not in mode:
        raise RuntimeError('MAXN required; no mode change attempted')
    if not all(os.access(GPC/n,os.W_OK) for n in ('min_freq','max_freq')):
        raise PermissionError('GPC min/max not writable by current process')


def set_frequency(mhz):
    target = validate_target(mhz)
    require_control()
    return legacy._range(target,target)


def restore():
    # Restore even if a preceding capability/readback check failed.
    return legacy._range(315000000,1575000000)


@contextmanager
def pinned(mhz):
    require_control()
    def interrupted(signum,_frame):
        raise KeyboardInterrupt(f'signal {signum}')
    old = {sig:signal.signal(sig,interrupted) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        set_frequency(mhz)
        yield
    finally:
        for sig in old:signal.signal(sig,signal.SIG_IGN)
        try:restore()
        finally:
            for sig,handler in old.items():signal.signal(sig,handler)
