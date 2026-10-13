import json
import socket

import pytest

from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource

SOURCE = ClaudeCodeSource()


def count(con, table):
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def append(path, *records):
    with path.open("a") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def assistant(uuid, parent, request_id, output_tokens, cache_read=5000):
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "s1",
        "requestId": request_id,
        "effort": "high",
        "timestamp": "2026-10-01T10:10:00Z",
        "message": {
            "model": "claude-sonnet-5-5",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": 1,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": 0,
            },
        },
    }


def test_first_ingest_loads_all_tables(con, logs_dir):
    report = pipeline.ingest(con, SOURCE, logs_dir)
    assert (report.files_seen, report.files_parsed, report.files_skipped) == (2, 2, 0)
    assert count(con, "prompts") == 3  # p1, p2 in s1 + L1 in legacy
    assert count(con, "requests") == 6  # r1, r2, r4 + lr1, lr2, lr3
    assert count(con, "sessions") == 2
    assert count(con, "ingest_errors") == 2
    assert report.errors == 2


def test_second_run_skips_unchanged_files(con, logs_dir):
    pipeline.ingest(con, SOURCE, logs_dir)
    report = pipeline.ingest(con, SOURCE, logs_dir)
    assert (report.files_parsed, report.files_skipped) == (0, 2)
    assert (report.new_prompts, report.new_requests) == (0, 0)


def test_full_rerun_does_not_duplicate_rows(con, logs_dir):
    pipeline.ingest(con, SOURCE, logs_dir)
    report = pipeline.ingest(con, SOURCE, logs_dir, full=True)
    assert report.files_parsed == 2
    assert (count(con, "prompts"), count(con, "requests"), count(con, "ingest_errors")) == (3, 6, 2)


def test_appended_lines_are_picked_up(con, logs_dir):
    s1 = logs_dir / "-Users-dev-myapp" / "s1.jsonl"
    pipeline.ingest(con, SOURCE, logs_dir)

    # Turn p2 continues (its parent was loaded in the previous run), then a new turn starts.
    append(
        s1,
        assistant("x7", "x6", "r5", output_tokens=30),
        {
            "type": "user",
            "uuid": "u5",
            "parentUuid": "x7",
            "sessionId": "s1",
            "promptId": "p3",
            "turnOrigin": "human",
            "timestamp": "2026-10-01T10:20:00Z",
            "message": {"content": "now add tests"},
        },
        assistant("x8", "u5", "r6", output_tokens=500),
    )
    report = pipeline.ingest(con, SOURCE, logs_dir)
    assert (report.files_parsed, report.files_skipped) == (1, 1)
    assert (report.new_prompts, report.new_requests) == (1, 2)
    n_requests = con.execute("SELECT n_requests FROM turns WHERE turn_id = 'p2'").fetchone()[0]
    assert n_requests == 2  # the old turn grew


def test_half_written_last_line_is_fixed_on_next_run(con, logs_dir):
    # Claude Code may still be writing a line while we read the file.
    s1 = logs_dir / "-Users-dev-myapp" / "s1.jsonl"
    full_line = json.dumps(assistant("x9", "x6", "r9", output_tokens=7))
    with s1.open("a") as fh:
        fh.write(full_line[:40])
    pipeline.ingest(con, SOURCE, logs_dir)
    assert count(con, "ingest_errors") == 3

    with s1.open("a") as fh:
        fh.write(full_line[40:] + "\n")
    pipeline.ingest(con, SOURCE, logs_dir)
    assert count(con, "ingest_errors") == 2  # the old error for that file is replaced
    assert con.execute("SELECT count(*) FROM requests WHERE request_id = 'r9'").fetchone()[0] == 1


def test_turns_view_aggregates_each_turn(con, logs_dir):
    pipeline.ingest(con, SOURCE, logs_dir)
    row = con.execute(
        """SELECT turn_index, project, model_family, effort, n_requests, n_tool_calls,
                  context_tokens_before, output_tokens, total_tokens
           FROM turns WHERE turn_id = 'p1'"""
    ).fetchone()
    # r1: 3 + 1000 + 500 in, 120 out.  r2: 1 + 1500 + 50 in, 60 out.
    assert row == (1, "myapp", "sonnet", "high", 2, 1, 1503, 180, 1623 + 1611)
    index = con.execute("SELECT turn_index FROM turns WHERE turn_id = 'p2'").fetchone()[0]
    assert index == 2


def test_no_text_option_stores_no_prompt_text(con, logs_dir):
    pipeline.ingest(con, SOURCE, logs_dir, store_text=False)
    assert con.execute("SELECT count(*) FROM prompts WHERE text IS NOT NULL").fetchone()[0] == 0


def test_ingest_makes_no_network_calls(con, logs_dir, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tokcast must not open network connections")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    pipeline.ingest(con, SOURCE, logs_dir)


def test_failed_load_leaves_no_partial_rows(con, logs_dir, monkeypatch):
    real_parse = SOURCE.parse_file

    def corrupt(path, **kwargs):
        parsed = real_parse(path, **kwargs)
        parsed.requests[0].session_id = None  # violates NOT NULL -> insert fails
        return parsed

    monkeypatch.setattr(SOURCE, "parse_file", corrupt)
    with pytest.raises(Exception):  # noqa: B017 - any DB error is fine here
        pipeline.ingest(con, SOURCE, logs_dir)
    assert count(con, "prompts") == 0  # the transaction was rolled back
    assert count(con, "ingested_files") == 0


def test_turn_totals_are_plain_64bit_integers(con, logs_dir):
    pipeline.ingest(con, SOURCE, logs_dir)
    types = dict(
        con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'turns'"
        ).fetchall()
    )
    for col in ("n_tool_calls", "output_tokens", "input_processed_tokens", "total_tokens"):
        assert types[col] == "BIGINT", col
