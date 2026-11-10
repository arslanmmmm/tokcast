"""Keep tokcast's data readable by its owner only. Standard library only (capture.py uses it).

The database stores full prompt text, which can contain pasted secrets, so on a shared
machine the default umask (world-readable files) isn't acceptable.
"""

from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def ensure_dir(path: Path, *, tighten_existing: bool) -> None:
    """Create ``path`` as 0700. An existing folder is tightened only when it's ours.

    A custom ``TOKCAST_HOME`` may point at a folder the user shares on purpose, so only
    tokcast's default folder is changed after the fact.
    """
    if not path.exists():
        path.mkdir(parents=True, mode=DIR_MODE)
        path.chmod(DIR_MODE)  # mkdir's mode is filtered by the umask
    elif tighten_existing:
        path.chmod(DIR_MODE)


def protect(*paths: Path) -> None:
    """Make the given files 0600; ones that don't exist (yet) are skipped."""
    for path in paths:
        if path.exists() and not path.is_symlink():
            path.chmod(FILE_MODE)
