"""Incremental ingest: find changed log files, parse them, load them atomically.

Incremental strategy: a file is re-read only if its size or modification time changed
since the last run. A changed file is parsed *in full* and its rows replaced. That
costs a little extra work on an appended file, but it is always correct: a new line's
parent (needed to find its turn) may sit in the part of the file read last time, and
a turn's totals change when lines are appended to it.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

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
        _replace_file(con, parsed, size=state[0], mtime_ns=state[1])
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


def _replace_file(
    con: duckdb.DuckDBPyConnection, parsed: ParsedFile, *, size: int, mtime_ns: int
) -> None:
    """Swap one file's rows in a single transaction: all of it lands, or none of it."""
    f = parsed.path
    con.begin()
    try:
        for table in ("ingest_errors", "prompts", "requests", "sessions"):
            con.execute(f"DELETE FROM {table} WHERE source_file = ?", [f])

        # ON CONFLICT DO NOTHING: if another file already holds the same request or
        # prompt (e.g. a resumed session that copied history), keep the first copy.
        if parsed.sessions:
            con.executemany(
                """INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                [
                    (
                        s.session_id,
                        parsed.source,
                        f,
                        os.path.basename(s.cwd.rstrip("/")) if s.cwd else None,
                        s.cwd,
                        s.git_branch,
                        s.version,
                    )
                    for s in parsed.sessions
                ],
            )
        if parsed.prompts:
            con.executemany(
                """INSERT INTO prompts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                [
                    (
                        p.prompt_id,
                        p.session_id,
                        f,
                        p.line_no,
                        p.ts,
                        p.kind,
                        p.text,
                        p.text_chars,
                        p.text_sha256,
                        p.has_image,
                    )
                    for p in parsed.prompts
                ],
            )
        if parsed.requests:
            con.executemany(
                """INSERT INTO requests VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                [
                    (
                        r.request_id,
                        r.session_id,
                        r.prompt_id,
                        f,
                        r.line_no,
                        r.ts,
                        r.model,
                        r.effort,
                        r.stop_reason,
                        r.input_tokens,
                        r.output_tokens,
                        r.cache_read_tokens,
                        r.cache_creation_tokens,
                        r.cache_creation_5m_tokens,
                        r.cache_creation_1h_tokens,
                        r.thinking_tokens,
                        r.web_search_requests,
                        r.web_fetch_requests,
                        r.tool_names,
                        len(r.tool_names),
                        r.is_sidechain,
                    )
                    for r in parsed.requests
                ],
            )
        if parsed.errors:
            con.executemany(
                "INSERT INTO ingest_errors VALUES (?, ?, ?)",
                [(f, e.line_no, e.error) for e in parsed.errors],
            )
        con.execute(
            """INSERT OR REPLACE INTO ingested_files VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [f, parsed.source, size, mtime_ns, parsed.n_lines, len(parsed.errors), _utcnow()],
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
