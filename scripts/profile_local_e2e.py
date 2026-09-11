"""Compatibility import for the intentionally unmoved edge working-tree script.

The implementation and maintained entrypoint are scripts/local/profile_local_e2e.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'common'))
from script_paths import configure
configure()
from local.profile_local_e2e import *  # noqa: F401,F403

if __name__ == '__main__':
    main()
