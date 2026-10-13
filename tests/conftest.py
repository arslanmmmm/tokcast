import shutil
from pathlib import Path

import pytest

from tokcast.storage import db

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code"


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    """A private copy of the fixture logs, so tests can append to files safely."""
    target = tmp_path / "logs"
    shutil.copytree(FIXTURES, target)
    return target


@pytest.fixture
def con():
    connection = db.connect(":memory:")
    yield connection
    connection.close()
