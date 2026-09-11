"""Import and source-file paths shared by the role-based script directories."""
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
ROLES = ('common', 'local', 'concurrency', 'initial_profiling', 'edge', 'network')


def configure():
    """Resolve legacy module names without copying experiment implementations."""
    if str(SCRIPTS) not in sys.path:
        sys.path.append(str(SCRIPTS))
    for role in reversed(ROLES):
        directory = str(SCRIPTS / role)
        if directory not in sys.path:
            sys.path.insert(0, directory)


def script_path(name):
    """Locate a relocated source by its unique basename for provenance hashing."""
    matches = [SCRIPTS / role / name for role in ROLES
               if (SCRIPTS / role / name).is_file()]
    if len(matches) != 1:
        raise ValueError(f'Expected one script named {name}: {matches}')
    return matches[0]
