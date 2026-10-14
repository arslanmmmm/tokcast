"""Build the feature table the predictor learns from."""

from dataclasses import dataclass
from datetime import datetime

import duckdb
import pandas as pd

from tokcast.features.classify import classify
from tokcast.storage.db import load_sql


def load_turns(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per usable past turn, oldest first, with task type and phase added."""
    df = con.execute(load_sql("predict/training_turns.sql")).df()
    return add_features(df)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Columns derived in Python (the classifier) rather than SQL."""
    out = df.copy()
    out["task_type"] = [
        classify(text, kind).task_type for text, kind in zip(out["text"], out["kind"], strict=True)
    ]
    out["first_turn"] = out["turn_index"] == 1
    return out


@dataclass(frozen=True)
class CurrentConversation:
    session_id: str
    ts: datetime
    context_tokens: int
    model: str
    effort: str | None


def current_conversation(con: duckdb.DuckDBPyConnection) -> CurrentConversation | None:
    """The most recent conversation in the logs, as of the last ingest."""
    row = con.execute(load_sql("predict/current_context.sql")).fetchone()
    return CurrentConversation(*row) if row else None


def new_chat_context(con: duckdb.DuckDBPyConnection) -> tuple[float, int]:
    """Median context before the first prompt of a session, and how many sessions back it."""
    row = con.execute(load_sql("predict/first_turn_context.sql")).fetchone()
    return (row[0], row[1]) if row and row[1] else (0.0, 0)
