"""Parser for Claude Code session logs: ``~/.claude/projects/<project>/<session>.jsonl``.

The format is undocumented and changes between Claude Code versions, so the parser is
defensive: every field is optional, and a bad line is reported, never raised.

Facts about the format this parser relies on (verified on real logs, v2.1.x):

1. Each API response is written as one line per content block (thinking, text,
   tool_use), and every one of those lines repeats the same ``usage``. Summing lines
   would overcount ~2.4x, so lines are merged by ``requestId``.
2. A *turn* starts with a human prompt: a ``user`` line with ``turnOrigin == "human"``
   (older versions lack that field, so there's a fallback rule). Tool results are
   also ``user`` lines, but they continue the current turn.
3. Assistant lines carry no prompt id. They are linked to their turn by walking the
   ``parentUuid`` chain up to the nearest user line. If the chain is broken, the most
   recent prompt in file order is used instead.
4. Timestamps can go backwards between neighbouring lines, so ordering uses line
   numbers, not time.
5. Subagents (the Task tool) write their own file, ``<session>/subagents/agent-<id>.jsonl``,
   with an ``agentId`` on each line. Their first user line is the task handed over by
   the main agent, not a human prompt. Their parent links point into the main file, so
   they are linked to a turn later, in SQL (see ``views.sql``).
   This layout comes from community reports; it isn't verified on real logs yet.
"""

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tokcast.ingest.records import LineError, ParsedFile, Prompt, Request, SessionInfo

# A prompt that starts with a tag, e.g. "<bash-input>ls</bash-input>", is a special kind
# of input (a shell command typed in the app, a slash command, ...). Kept as `kind`.
_LEADING_TAG = re.compile(r"\s*<([a-zA-Z][\w-]*)>")

# Claude Code writes placeholder assistant messages (e.g. for API errors) with this
# model name. They are not real API calls and have no meaningful usage.
_SYNTHETIC_MODEL = "<synthetic>"


class ClaudeCodeSource:
    name = "claude_code"

    def discover(self, root: Path) -> Iterable[Path]:
        if not root.is_dir():
            return []
        return sorted(root.glob("**/*.jsonl"))

    def parse_file(self, path: Path, *, store_text: bool = True) -> ParsedFile:
        out = ParsedFile(path=str(path), source=self.name)
        records = _read_records(path, out)
        _FileParser(records, out, store_text, agent_id=_agent_id_from_path(path)).run()
        return out


def _read_records(path: Path, out: ParsedFile) -> list[tuple[int, dict[str, Any]]]:
    """Read JSON objects line by line. Bad lines go to ``out.errors``."""
    records: list[tuple[int, dict[str, Any]]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh, start=1):
                out.n_lines = line_no
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    out.errors.append(LineError(line_no, f"invalid JSON: {exc.msg}"))
                    continue
                if not isinstance(obj, dict):
                    out.errors.append(
                        LineError(line_no, f"expected a JSON object, got {type(obj).__name__}")
                    )
                    continue
                records.append((line_no, obj))
    except OSError as exc:
        out.errors.append(LineError(0, f"cannot read file: {exc}"))
    return records


class _FileParser:
    """Turns the records of one file into prompts, requests and sessions."""

    def __init__(
        self,
        records: list[tuple[int, dict[str, Any]]],
        out: ParsedFile,
        store_text: bool,
        agent_id: str | None = None,
    ):
        self.records = records
        self.file_agent_id = agent_id
        self.out = out
        self.store_text = store_text
        self.by_uuid = {rec["uuid"]: rec for _, rec in records if isinstance(rec.get("uuid"), str)}
        self.prompts: dict[str, Prompt] = {}
        self.requests: dict[str, Request] = {}
        self.tool_ids: dict[str, set[str]] = {}
        self.sessions: dict[str, SessionInfo] = {}
        self.chain_memo: dict[str, str | None] = {}

    def run(self) -> None:
        current_prompt: str | None = None  # fallback: most recent prompt in file order
        for line_no, rec in self.records:
            try:
                self._note_session(rec)
                if _is_human_prompt(rec):
                    current_prompt = self._add_prompt(line_no, rec)
                elif rec.get("type") == "assistant":
                    prompt_id = self._resolve_prompt(rec.get("parentUuid")) or current_prompt
                    self._add_request(line_no, rec, prompt_id)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                # Valid JSON with an unexpected shape. Skip the line, keep going.
                self.out.errors.append(
                    LineError(line_no, f"unexpected structure: {type(exc).__name__}: {exc}")
                )
        self.out.prompts = list(self.prompts.values())
        self.out.requests = list(self.requests.values())
        self.out.sessions = list(self.sessions.values())

    def _note_session(self, rec: dict[str, Any]) -> None:
        sid = rec.get("sessionId")
        if not isinstance(sid, str):
            return
        info = self.sessions.setdefault(sid, SessionInfo(sid, None, None, None))
        info.cwd = info.cwd or rec.get("cwd")
        info.git_branch = info.git_branch or rec.get("gitBranch")
        info.version = info.version or rec.get("version")

    def _add_prompt(self, line_no: int, rec: dict[str, Any]) -> str:
        key = _prompt_key(rec) or f"{self.out.path}:{line_no}"
        text, has_image = _prompt_text(rec["message"].get("content"))
        existing = self.prompts.get(key)
        if existing is not None:
            # Rare: one prompt split over two lines (e.g. an image, then its text).
            text = "\n".join(t for t in (existing.text, text) if t)
            has_image = has_image or existing.has_image
            line_no, ts = existing.line_no, existing.ts
        else:
            ts = _parse_ts(rec.get("timestamp"))
        match = _LEADING_TAG.match(text)
        kind = match.group(1).lower() if match else ("image" if has_image and not text else "text")
        self.prompts[key] = Prompt(
            prompt_id=key,
            session_id=rec.get("sessionId") or "",
            line_no=line_no,
            ts=ts,
            kind=kind,
            text=text if self.store_text else None,
            text_chars=len(text),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            has_image=has_image,
        )
        return key

    def _resolve_prompt(self, uuid: str | None) -> str | None:
        """Walk parentUuid links up to the nearest user line and return its prompt id."""
        visited: list[str] = []
        result: str | None = None
        while isinstance(uuid, str) and uuid not in visited:
            if uuid in self.chain_memo:
                result = self.chain_memo[uuid]
                break
            visited.append(uuid)
            rec = self.by_uuid.get(uuid)
            if rec is None:  # parent lives in another file, or the chain is broken
                break
            if rec.get("type") == "user":
                result = _prompt_key(rec) if _is_human_prompt(rec) else rec.get("promptId")
                if result:
                    break
            uuid = rec.get("parentUuid")
        for seen in visited:  # memoize, so long chains are walked only once
            self.chain_memo[seen] = result
        return result

    def _add_request(self, line_no: int, rec: dict[str, Any], prompt_id: str | None) -> None:
        msg = rec.get("message")
        if not isinstance(msg, dict) or msg.get("model") == _SYNTHETIC_MODEL:
            return
        key = rec.get("requestId") or msg.get("id")
        if not isinstance(key, str):
            return
        req = self.requests.get(key)
        if req is None:
            req = Request(
                request_id=key,
                session_id=rec.get("sessionId") or "",
                prompt_id=prompt_id,
                line_no=line_no,
                ts=_parse_ts(rec.get("timestamp")),
                model=msg.get("model"),
                effort=rec.get("effort"),
                stop_reason=None,
                is_sidechain=bool(rec.get("isSidechain")),
                agent_id=rec.get("agentId") or self.file_agent_id,
            )
            self.requests[key] = req
            self.tool_ids[key] = set()

        # Every line of a request repeats its usage. Taking the max (not the sum) is
        # correct whether the lines are identical (current versions) or show growing
        # partial counts while streaming (some older versions).
        usage = msg.get("usage") or {}
        cache = usage.get("cache_creation") or {}
        details = usage.get("output_tokens_details") or {}
        server = usage.get("server_tool_use") or {}
        req.input_tokens = max(req.input_tokens, _int(usage.get("input_tokens")))
        req.output_tokens = max(req.output_tokens, _int(usage.get("output_tokens")))
        req.cache_read_tokens = max(
            req.cache_read_tokens, _int(usage.get("cache_read_input_tokens"))
        )
        req.cache_creation_tokens = max(
            req.cache_creation_tokens, _int(usage.get("cache_creation_input_tokens"))
        )
        req.cache_creation_5m_tokens = max(
            req.cache_creation_5m_tokens, _int(cache.get("ephemeral_5m_input_tokens"))
        )
        req.cache_creation_1h_tokens = max(
            req.cache_creation_1h_tokens, _int(cache.get("ephemeral_1h_input_tokens"))
        )
        req.thinking_tokens = max(req.thinking_tokens, _int(details.get("thinking_tokens")))
        req.web_search_requests = max(
            req.web_search_requests, _int(server.get("web_search_requests"))
        )
        req.web_fetch_requests = max(req.web_fetch_requests, _int(server.get("web_fetch_requests")))
        req.stop_reason = msg.get("stop_reason") or req.stop_reason
        req.effort = req.effort or rec.get("effort")

        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_id = block.get("id") or f"{line_no}:{block.get('name')}"
                if tool_id not in self.tool_ids[key]:
                    self.tool_ids[key].add(tool_id)
                    req.tool_names.append(str(block.get("name")))


def _is_human_prompt(rec: dict[str, Any]) -> bool:
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary"):
        return False
    if rec.get("agentId") or rec.get("isSidechain"):  # a task handed to a subagent
        return False
    if "turnOrigin" in rec:  # newer versions say it explicitly
        return rec["turnOrigin"] == "human"
    # Older versions: a user line is human input unless it only carries tool results.
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        types = {b.get("type") for b in content if isinstance(b, dict)}
        return bool(types & {"text", "image"}) and "tool_result" not in types
    return False


def _agent_id_from_path(path: Path) -> str | None:
    """``.../<session>/subagents/agent-<id>.jsonl`` -> ``<id>``."""
    if path.parent.name == "subagents" and path.stem.startswith("agent-"):
        return path.stem.removeprefix("agent-")
    return None


def _prompt_key(rec: dict[str, Any]) -> str | None:
    key = rec.get("promptId") or rec.get("uuid")
    return key if isinstance(key, str) else None


def _prompt_text(content: Any) -> tuple[str, bool]:
    if isinstance(content, str):
        return content, False
    texts: list[str] = []
    has_image = False
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif block.get("type") == "image":
            has_image = True
    return "\n".join(texts), has_image


def _parse_ts(value: Any) -> datetime | None:
    """ISO-8601 string -> naive UTC datetime (stored as UTC everywhere)."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _int(value: Any) -> int:
    # bool is a subclass of int in Python; exclude it so `true` isn't read as 1 token.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return int(value)
