"""Typed records produced by log parsers.

Every log source (Claude Code today; Codex CLI or Cursor later) converts its own raw
format into these records. Everything downstream (storage, stats, prediction) only
knows about these types, so adding a new source never touches the rest of the code.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Prompt:
    """One message the human sent. It starts a *turn*."""

    prompt_id: str
    session_id: str
    line_no: int  # position in the file; used for ordering (timestamps can go backwards)
    ts: datetime | None
    kind: str  # "text", or the leading tag such as "bash-input"
    text: str | None  # None when the user ingests with --no-text
    text_chars: int
    text_sha256: str
    has_image: bool


@dataclass
class Request:
    """One API call to the model, deduplicated across the lines it was split into."""

    request_id: str
    session_id: str
    prompt_id: str | None  # the turn this call belongs to (None if it can't be linked)
    line_no: int  # first line of this request in the file
    ts: datetime | None
    model: str | None
    effort: str | None
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    thinking_tokens: int = 0
    web_search_requests: int = 0
    web_fetch_requests: int = 0
    tool_names: list[str] = field(default_factory=list)
    is_sidechain: bool = False


@dataclass
class SessionInfo:
    session_id: str
    cwd: str | None
    git_branch: str | None
    version: str | None


@dataclass
class LineError:
    line_no: int
    error: str


@dataclass
class ParsedFile:
    """Everything one log file contributed. Loaded into the database as one unit."""

    path: str
    source: str
    prompts: list[Prompt] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    sessions: list[SessionInfo] = field(default_factory=list)
    errors: list[LineError] = field(default_factory=list)
    n_lines: int = 0
