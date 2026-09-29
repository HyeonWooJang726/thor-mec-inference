"""Read-only GPU control readiness. No pin or sysfs write occurs here."""
import os
from datetime import datetime, timezone
from pathlib import Path

GPC = Path('/sys/class/devfreq/gpu-gpc-0')
TARGET_HZ = 1575000000


def observe(root=GPC, access=os.access):
    checks = {}
    errors = []
    for name in ('min_freq', 'max_freq'):
        path = root / name
        entry = {'path': str(path), 'exists': path.exists(),
                 'readable': access(path, os.R_OK),
                 'writable_by_current_user': access(path, os.W_OK)}
        try:
            st = path.stat()
            entry.update(owner_uid=st.st_uid, owner_gid=st.st_gid,
                         mode=oct(st.st_mode & 0o777), value_hz=int(path.read_text().strip()))
        except (OSError, ValueError) as exc:
            entry['error'] = repr(exc)
        if not all(entry.get(key) for key in ('exists', 'readable', 'writable_by_current_user')) or 'value_hz' not in entry:
            errors.append(name + ' unavailable/read-only')
        checks[name] = entry
    table = root / 'available_frequencies'
    try:
        available = [int(value) for value in table.read_text().split()]
    except (OSError, ValueError) as exc:
        available = []
        errors.append('available_frequencies: ' + repr(exc))
    lo, hi = checks['min_freq'].get('value_hz'), checks['max_freq'].get('value_hz')
    if TARGET_HZ not in available:
        errors.append('1575000000 Hz not listed as available')
    if lo is None or hi is None or not lo <= TARGET_HZ <= hi:
        errors.append('1575000000 Hz outside current allowed range')
    return {'status': 'PASS' if not errors else 'FAIL',
            'checked_at_utc': datetime.now(timezone.utc).isoformat(),
            'effective_uid': os.geteuid(), 'target_hz': TARGET_HZ,
            'files': checks, 'target_listed': TARGET_HZ in available,
            'current_allowed_range_hz': [lo, hi], 'errors': errors,
            'read_only': True, 'frequency_change_attempted': False}


def require_ready(observe_fn=observe):
    result = observe_fn()
    if result['status'] != 'PASS':
        raise PermissionError('GPU control read-only precheck failed before campaign attempt marker: ' + str(result['errors']))
    return result
