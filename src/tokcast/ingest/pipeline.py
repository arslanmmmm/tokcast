"""Incremental ingest: find changed log files, parse them, load them atomically.

Incremental strategy: a file is re-read only if its size or modification time changed
since the last run. A changed file is parsed *in full*, because a new line's parent
(needed to find its turn) may sit in the part of the file read last time.

Loading is append-only ("upsert"): rows are inserted or updated by their id, and
never deleted because they disappeared from a file. Claude Code rewrites session
files on resume/compact (dropping lines) and deletes them after 30 days by default,
so the database must be the durable record of history, not a mirror of the files.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa

from tokcast.ingest.records import ParsedFile
from tokcast.ingest.sources.base import LogSource


@dataclass
class IngestReport:
    files_seen: int = 0
    files_parsed: int = 0
    files_skipped: int = 0
    prompts_before: int = 0
    prompts_after: int = 0
    requests_before: int = 0
    requests_after: int = 0
    errors: int = 0  # malformed lines found in the files parsed this run
    error_files: list[str] = field(default_factory=list)

    @property
    def new_prompts(self) -> int:
        return self.prompts_after - self.prompts_before

    @property
    def new_requests(self) -> int:
        return self.requests_after - self.requests_before


def ingest(
    con: duckdb.DuckDBPyConnection,
    source: LogSource,
    root: Path,
    *,
    store_text: bool = True,
    full: bool = False,
) -> IngestReport:
    """Load every new or changed log file under ``root``. Safe to run repeatedly."""
    report = IngestReport()
    report.prompts_before, report.requests_before = _counts(con)
    known = {
        path: (size, mtime)
        for path, size, mtime in con.execute(
            "SELECT path, size_bytes, mtime_ns FROM ingested_files"
        ).fetchall()
    }

    for path in source.discover(root):
        report.files_seen += 1
        try:
            stat = path.stat()
        except OSError:
            continue  # vanished between discover() and now
        state = (stat.st_size, stat.st_mtime_ns)
        if not full and known.get(str(path)) == state:
            report.files_skipped += 1
            continue
        parsed = source.parse_file(path, store_text=store_text)
        _load_file(con, parsed, size=state[0], mtime_ns=state[1])
        report.files_parsed += 1
        if parsed.errors:
            report.errors += len(parsed.errors)
            report.error_files.append(str(path))

    report.prompts_after, report.requests_after = _counts(con)
    return report


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _counts(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    row = con.execute(
        "SELECT (SELECT count(*) FROM prompts), (SELECT count(*) FROM requests)"
    ).fetchone()
    assert row is not None
    return row[0], row[1]


# Explicit Arrow schemas: types must not depend on the data (e.g. a file whose requests
# all have empty tool lists would otherwise get a list<null> column).
_SESSIONS = pa.schema(
    [
        ("session_id", pa.string()),
        ("source", pa.string()),
        ("source_file", pa.string()),
        ("project", pa.string()),
        ("cwd", pa.string()),
        ("git_branch", pa.string()),
        ("tool_version", pa.string()),
    ]
)
_PROMPTS = pa.schema(
    [
        ("prompt_id", pa.string()),
        ("session_id", pa.string()),
        ("source_file", pa.string()),
        ("line_no", pa.int32()),
        ("ts", pa.timestamp("us")),
        ("kind", pa.string()),
        ("text", pa.string()),
        ("text_chars", pa.int32()),
        ("text_sha256", pa.string()),
        ("has_image", pa.bool_()),
    ]
)
_REQUESTS = pa.schema(
    [
        ("request_id", pa.string()),
        ("session_id", pa.string()),
        ("prompt_id", pa.string()),
        ("source_file", pa.string()),
        ("line_no", pa.int32()),
        ("ts", pa.timestamp("us")),
        ("model", pa.string()),
        ("effort", pa.string()),
        ("stop_reason", pa.string()),
        ("input_tokens", pa.int64()),
        ("output_tokens", pa.int64()),
        ("cache_read_tokens", pa.int64()),
        ("cache_creation_tokens", pa.int64()),
        ("cache_creation_5m_tokens", pa.int64()),
        ("cache_creation_1h_tokens", pa.int64()),
        ("thinking_tokens", pa.int64()),
        ("web_search_requests", pa.int32()),
        ("web_fetch_requests", pa.int32()),
        ("tool_names", pa.list_(pa.string())),
        ("n_tool_calls", pa.int32()),
        ("is_sidechain", pa.bool_()),
        ("agent_id", pa.string()),
    ]
)


def _load_file(
    con: duckdb.DuckDBPyConnection, parsed: ParsedFile, *, size: int, mtime_ns: int
) -> None:
    """Upsert one file's rows in a single transaction: all of it lands, or none of it.

    Rows are bulk-loaded: each table's rows become one Arrow table that DuckDB reads
    in place, followed by a single set-based INSERT ... SELECT. Inserting row by row
    (executemany) was ~100x slower.
    """
    f = parsed.path
    sessions = pa.Table.from_pylist(
        [
            {
                "session_id": s.session_id,
                "source": parsed.source,
                "source_file": f,
                "project": os.path.basename(s.cwd.rstrip("/")) if s.cwd else None,
                "cwd": s.cwd,
                "git_branch": s.git_branch,
                "tool_version": s.version,
            }
            for s in parsed.sessions
        ],
        schema=_SESSIONS,
    )
    prompts = pa.Table.from_pylist(
        [
            {
                "prompt_id": p.prompt_id,
                "session_id": p.session_id,
                "source_file": f,
                "line_no": p.line_no,
                "ts": p.ts,
                "kind": p.kind,
                "text": p.text,
                "text_chars": p.text_chars,
                "text_sha256": p.text_sha256,
                "has_image": p.has_image,
            }
            for p in parsed.prompts
        ],
        schema=_PROMPTS,
    )
    requests = pa.Table.from_pylist(
        [
            {
                "request_id": r.request_id,
                "session_id": r.session_id,
                "prompt_id": r.prompt_id,
                "source_file": f,
                "line_no": r.line_no,
                "ts": r.ts,
                "model": r.model,
                "effort": r.effort,
                "stop_reason": r.stop_reason,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "cache_creation_tokens": r.cache_creation_tokens,
                "cache_creation_5m_tokens": r.cache_creation_5m_tokens,
                "cache_creation_1h_tokens": r.cache_creation_1h_tokens,
                "thinking_tokens": r.thinking_tokens,
                "web_search_requests": r.web_search_requests,
                "web_fetch_requests": r.web_fetch_requests,
                "tool_names": r.tool_names,
                "n_tool_calls": len(r.tool_names),
                "is_sidechain": r.is_sidechain,
                "agent_id": r.agent_id,
            }
            for r in parsed.requests
        ],
        schema=_REQUESTS,
    )

    con.begin()
    try:
        con.register("staged_sessions", sessions)
        con.register("staged_prompts", prompts)
        con.register("staged_requests", requests)

        # Keep what we knew; fill in session fields that were missing before.
        con.execute(
            """INSERT INTO sessions BY NAME SELECT * FROM staged_sessions
               ON CONFLICT (session_id) DO UPDATE SET
                   project      = coalesce(sessions.project, excluded.project),
                   cwd          = coalesce(sessions.cwd, excluded.cwd),
                   git_branch   = coalesce(sessions.git_branch, excluded.git_branch),
                   tool_version = coalesce(sessions.tool_version, excluded.tool_version)"""
        )
        # A prompt is never deleted. When it is seen again, fields derived from its text
        # are refreshed, so parser improvements reach old rows via `ingest --full`.
        # Where and when it was first seen (source_file, line_no, ts) stays.
        con.execute(
            """INSERT INTO prompts BY NAME SELECT * FROM staged_prompts
               ON CONFLICT (prompt_id) DO UPDATE SET
                   kind        = excluded.kind,
                   text        = excluded.text,
                   text_chars  = excluded.text_chars,
                   text_sha256 = excluded.text_sha256,
                   has_image   = excluded.has_image"""
        )
        # Token counts can only grow: a request first seen half-written gets its final
        # numbers later, but a rewritten file can never shrink them.
        # BY NAME matches columns by name, not position: older databases got agent_id
        # through ALTER TABLE, so column positions can differ between installs.
        con.execute(
            """INSERT INTO requests BY NAME SELECT * FROM staged_requests
               ON CONFLICT (request_id) DO UPDATE SET
                   prompt_id   = coalesce(requests.prompt_id, excluded.prompt_id),
                   stop_reason = coalesce(excluded.stop_reason, requests.stop_reason),
                   effort      = coalesce(requests.effort, excluded.effort),
                   agent_id    = coalesce(requests.agent_id, excluded.agent_id),
                   input_tokens  = greatest(requests.input_tokens, excluded.input_tokens),
                   output_tokens = greatest(requests.output_tokens, excluded.output_tokens),
                   cache_read_tokens =
                       greatest(requests.cache_read_tokens, excluded.cache_read_tokens),
                   cache_creation_tokens =
                       greatest(requests.cache_creation_tokens, excluded.cache_creation_tokens),
                   cache_creation_5m_tokens = greatest(
                       requests.cache_creation_5m_tokens, excluded.cache_creation_5m_tokens),
                   cache_creation_1h_tokens = greatest(
                       requests.cache_creation_1h_tokens, excluded.cache_creation_1h_tokens),
                   thinking_tokens = greatest(requests.thinking_tokens, excluded.thinking_tokens),
                   web_search_requests =
                       greatest(requests.web_search_requests, excluded.web_search_requests),
                   web_fetch_requests =
                       greatest(requests.web_fetch_requests, excluded.web_fetch_requests),
                   tool_names = CASE
                       WHEN len(excluded.tool_names) > len(requests.tool_names)
                       THEN excluded.tool_names ELSE requests.tool_names END,
                   n_tool_calls = greatest(requests.n_tool_calls, excluded.n_tool_calls)"""
        )
        # Errors describe the file as it is now, so they are replaced, not accumulated.
        con.execute("DELETE FROM ingest_errors WHERE source_file = ?", [f])
        if parsed.errors:
            con.executemany(  # few rows; row-by-row is fine here
                "INSERT INTO ingest_errors VALUES (?, ?, ?)",
                [(f, e.line_no, e.error) for e in parsed.errors],
            )
        con.execute(
            "INSERT OR REPLACE INTO ingested_files VALUES (?, ?, ?, ?, ?, ?, ?)",
            [f, parsed.source, size, mtime_ns, parsed.n_lines, len(parsed.errors), _utcnow()],
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        for name in ("staged_sessions", "staged_prompts", "staged_requests"):
            con.unregister(name)
