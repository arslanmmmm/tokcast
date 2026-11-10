"""tokcast's data holds full prompt text, so only the user may read it (0700 / 0600)."""

import json
import stat

from tokcast import capture, config
from tokcast.storage import db


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_new_database_is_private(tmp_path):
    home = tmp_path / "home"
    db.connect(home / config.DB_FILENAME).close()

    assert mode(home) == 0o700
    assert mode(home / config.DB_FILENAME) == 0o600


def test_existing_world_readable_database_is_tightened(tmp_path):
    home = tmp_path / "home"
    db.connect(home / config.DB_FILENAME).close()
    (home / config.DB_FILENAME).chmod(0o644)  # as tokcast 0.1 left it

    db.connect(home / config.DB_FILENAME).close()

    assert mode(home / config.DB_FILENAME) == 0o600


def test_status_line_files_are_private(tmp_path):
    home = tmp_path / "home"
    payload = {"rate_limits": {"five_hour": {"used_percentage": 5, "resets_at": 1_791_400_000}}}

    capture.run(json.dumps(payload), home)

    assert mode(home) == 0o700
    assert mode(home / capture.SNAPSHOT_FILE) == 0o600
    assert mode(home / capture.STATE_FILE) == 0o600


def test_a_custom_existing_folder_keeps_its_own_mode(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    monkeypatch.setenv("TOKCAST_HOME", str(shared))

    db.connect(shared / config.DB_FILENAME).close()

    assert mode(shared) == 0o755  # not ours to lock down
    assert mode(shared / config.DB_FILENAME) == 0o600  # our file still is
