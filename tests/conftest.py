import shutil
from pathlib import Path

import pytest

from tokcast.features.build import load_turns
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.storage import db
from tokcast.synth import generate

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


@pytest.fixture(scope="session")
def synthetic_turns(tmp_path_factory):
    """A synthetic history of 150 sessions (~1,400 turns), generated once per test run."""
    logs = tmp_path_factory.mktemp("synth") / "logs"
    generate(logs, sessions=150, seed=5)
    connection = db.connect(":memory:")
    pipeline.ingest(connection, ClaudeCodeSource(), logs)
    turns = load_turns(connection)
    connection.close()
    return turns
