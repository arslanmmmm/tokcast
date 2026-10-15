"""Synthetic Claude Code logs for tests, demos and developing the predictor.

Real history is often small (a new user has a few dozen turns). This module writes
fake but realistic session logs in exactly the format the parser reads, so every
later step (stats, predict, eval) can run on thousands of turns.

The data-generating process is deliberately simple and documented below. That makes
it a fair test of the *pipeline*, but accuracy measured on synthetic data says nothing
about accuracy on real usage. Results are always labelled "synthetic".

Parameters were tuned by eye against a small real sample (50 turns, one model and one
effort level), matching the median and tail of calls per turn, output per call and
context size. Treat them as plausible, not as measured truth.

How a turn is generated:
- Task type, model and effort set a mean number of API calls; the actual count is
  heavy-tailed (lognormal), like real usage where one prompt can trigger 50+ calls.
- Every call re-reads the whole conversation (cache read) and adds its output plus a
  tool result to the context, so long turns get expensive fast.
- The context is compacted when it nears the window limit, and fully re-cached after
  a pause longer than the 1-hour cache lifetime.
- Bigger tasks sometimes start subagents, which write their own files.
"""

import json
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import duckdb

MARKER_FILE = "TOKCAST_SYNTHETIC"  # written into every generated folder
SYNTHETIC_PROJECT_PREFIX = "-synthetic-"


@dataclass(frozen=True)
class TaskProfile:
    weight: float  # how often this task type occurs
    calls: float  # mean API calls per turn at medium effort
    output: int  # median output tokens per call
    subagent_rate: float  # chance a turn starts subagents


TASKS = {
    "bugfix": TaskProfile(0.20, 4, 350, 0.05),
    "feature": TaskProfile(0.18, 8, 450, 0.20),
    "refactor": TaskProfile(0.12, 6, 420, 0.15),
    "tests": TaskProfile(0.10, 5, 480, 0.10),
    "explain": TaskProfile(0.14, 1.5, 500, 0.02),
    "docs": TaskProfile(0.08, 2, 550, 0.0),
    "shell": TaskProfile(0.10, 1.2, 200, 0.0),
    "other": TaskProfile(0.08, 1.5, 280, 0.0),
}


@dataclass(frozen=True)
class Multiplier:
    calls: float
    output: float
    thinking_share: float  # part of output tokens spent on thinking


EFFORTS = {
    "low": Multiplier(0.6, 0.7, 0.05),
    "medium": Multiplier(1.0, 1.0, 0.15),
    "high": Multiplier(1.35, 1.25, 0.30),
    "xhigh": Multiplier(1.6, 1.4, 0.40),
    "max": Multiplier(1.9, 1.6, 0.50),
}
EFFORT_WEIGHTS = {"low": 0.10, "medium": 0.45, "high": 0.30, "xhigh": 0.10, "max": 0.05}

MODELS = {
    "opus": ("claude-opus-5-5", Multiplier(0.9, 1.1, 1.0)),
    "sonnet": ("claude-sonnet-5-5", Multiplier(1.0, 1.0, 1.0)),
    "haiku": ("claude-haiku-5-5", Multiplier(1.1, 0.8, 0.5)),
}

PROJECTS = ["webapp", "data-pipeline", "cli-tool", "ml-notebook"]
CONTEXT_LIMIT = 400_000  # real sessions grew past 300k tokens without compacting
CACHE_TTL = timedelta(hours=1)

_FILES = ["auth.py", "api/routes.ts", "models/user.py", "pipeline.sql", "cli.py", "utils.js"]
_THINGS = ["login", "pagination", "caching", "retry", "date parsing", "the export job"]
_PROMPTS = {
    "bugfix": [
        "fix the {thing} bug in {file}",
        "{file} throws a KeyError when I run it, can you fix it",
        "tests are failing after the last change, please debug",
        "{thing} is broken again",
    ],
    "feature": [
        "add {thing} to {file}",
        "implement {thing} support",
        "build a new endpoint for {thing} with validation",
    ],
    "refactor": [
        "refactor {file} to use dependency injection",
        "clean up {file}, split it into smaller functions",
        "rename {thing} to something clearer everywhere",
    ],
    "tests": [
        "write tests for {file}",
        "add unit tests covering {thing}",
        "increase test coverage",
    ],
    "explain": ["explain how {thing} works", "what does {file} do?", "why is {thing} slow?"],
    "docs": ["update the README with {thing}", "write docstrings for {file}", "document {thing}"],
    "other": ["thanks!", "ok continue", "looks good, commit it", "what should we do next?"],
}
_SHELL = ["git status", "ls -la", "uv run pytest", "npm test", "git diff --stat"]
_TOOLS = ["Read", "Edit", "Bash", "Grep", "Write", "Glob"]


@dataclass
class SynthSummary:
    """What was generated. Tests compare this ground truth with what ingest loads."""

    sessions: int = 0
    prompts: int = 0
    requests: int = 0
    subagent_requests: int = 0
    malformed_lines: int = 0
    turn_totals: dict[str, int] = field(default_factory=dict)  # prompt_id -> total tokens


def generate(
    out_dir: Path,
    *,
    sessions: int = 200,
    days: int = 60,
    seed: int = 42,
    start: datetime = datetime(2026, 7, 1),
) -> SynthSummary:
    """Write ``sessions`` synthetic sessions spread over ``days`` days into ``out_dir``.

    The output is fully determined by the arguments: the same seed gives the same bytes.
    """
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MARKER_FILE).write_text(
        "These Claude Code logs were generated by `tokcast synth`. They are not real usage.\n"
    )
    summary = SynthSummary()
    starts = sorted(
        start + timedelta(days=rng.uniform(0, days), hours=rng.uniform(8, 14))
        for _ in range(sessions)
    )
    for i, session_start in enumerate(starts):
        progress = i / max(sessions - 1, 1)
        _Session(rng, out_dir, session_start, progress, summary).run()
    return summary


class _Session:
    def __init__(
        self,
        rng: random.Random,
        out_dir: Path,
        start: datetime,
        progress: float,
        summary: SynthSummary,
    ):
        self.rng = rng
        self.summary = summary
        self.session_id = self._uuid()
        project = rng.choice(PROJECTS)
        self.cwd = f"/synthetic/{project}"
        self.dir = out_dir / f"{SYNTHETIC_PROJECT_PREFIX}{project}"
        self.path = self.dir / f"{self.session_id}.jsonl"
        self.now = start
        self.lines: list[str] = []
        self.last_uuid: str | None = None
        # Mild drift over time: the user shifts from opus towards sonnet. This makes a
        # time-ordered train/test split meaningfully harder than a random one.
        opus_share = 0.55 - 0.20 * progress
        self.model = _pick(rng, {"opus": opus_share, "sonnet": 0.90 - opus_share, "haiku": 0.10})
        self.effort = _pick(rng, EFFORT_WEIGHTS)
        self.context = int(_lognormal(rng, 60_000, 0.10))  # system prompt, tools, CLAUDE.md
        self.cached = 0  # how much of the context is in the prompt cache
        self.cache_written_at = start

    def run(self) -> None:
        self.summary.sessions += 1
        n_turns = 1 + int(self.rng.expovariate(1 / 9))
        for _ in range(min(n_turns, 60)):
            if self.rng.random() < 0.10:  # users switch model or effort mid-session
                self.model = _pick(self.rng, {"opus": 0.4, "sonnet": 0.5, "haiku": 0.1})
            if self.rng.random() < 0.05:
                self.effort = _pick(self.rng, EFFORT_WEIGHTS)
            self._turn()
            self.now += timedelta(seconds=_lognormal(self.rng, 90, 1.2))
        self._write_noise_lines()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(self.lines))

    # -- one turn ---------------------------------------------------------------------

    def _turn(self) -> None:
        rng = self.rng
        task = _pick(rng, {name: t.weight for name, t in TASKS.items()})
        profile, effort = TASKS[task], EFFORTS[self.effort]
        model_id, model = MODELS[self.model]
        text, pasted = self._prompt_text(task)
        prompt_id = self._uuid()
        self.summary.prompts += 1
        self.summary.turn_totals[prompt_id] = 0

        content: Any = text
        if rng.random() < 0.02:
            content = [{"type": "image", "source": {"type": "base64", "data": "..."}}]
            content.append({"type": "text", "text": text})
        self._emit(
            {
                "type": "user",
                "promptId": prompt_id,
                "turnOrigin": "human",
                "message": {"role": "user", "content": content},
            }
        )
        if rng.random() < 0.5:
            self._emit({"type": "attachment", "attachment": {"type": "total_tokens_reminder"}})
        self.context += len(text) // 4

        mean_calls = profile.calls * effort.calls * model.calls * (1.3 if pasted else 1.0)
        n_calls = min(1 + int(_lognormal(rng, max(mean_calls - 1, 0.3), 1.0)), 120)
        spawn_at = None
        if rng.random() < profile.subagent_rate * effort.calls and n_calls > 1:
            spawn_at = rng.randrange(n_calls - 1)

        for call in range(n_calls):
            final = call == n_calls - 1
            output = max(
                1,
                min(
                    int(_lognormal(rng, profile.output * effort.output * model.output, 0.8)), 32_000
                ),
            )
            thinking = int(output * effort.thinking_share * model.thinking_share)
            tools = [] if final else ["Task"] if call == spawn_at else self._tools()
            total = self._call(model_id, output, thinking, tools, prompt_id)
            self.summary.turn_totals[prompt_id] += total
            if call == spawn_at:
                self._subagents(prompt_id)
            for _ in tools:
                result = min(int(_lognormal(rng, 1_200, 1.0)), 25_000)
                self.context += result
                self._emit(
                    {
                        "type": "user",
                        "promptId": prompt_id,
                        "message": {
                            "role": "user",
                            "content": [{"type": "tool_result", "content": "..."}],
                        },
                    }
                )
        if rng.random() < 0.01:  # an API error placeholder; not a real request
            self._emit(
                {
                    "type": "assistant",
                    "message": {
                        "model": "<synthetic>",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "API Error"}],
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                }
            )
        if self.context > CONTEXT_LIMIT:  # auto-compact: replace history by a summary
            self.context = int(_lognormal(rng, 60_000, 0.2))
            self.cached = 0

    def _call(
        self, model_id: str, output: int, thinking: int, tools: list[str], prompt_id: str
    ) -> int:
        """Write one API call (split into one line per content block). Returns its tokens."""
        rng = self.rng
        if self.now - self.cache_written_at > CACHE_TTL:
            self.cached = 0  # the cache expired during a long pause
        input_tokens = rng.randint(1, 6)
        cache_read = min(self.cached, self.context)
        cache_creation = self.context - cache_read
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_creation,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 0,
                "ephemeral_1h_input_tokens": cache_creation,
            },
            "output_tokens_details": {"thinking_tokens": thinking},
            "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
        }
        blocks: list[dict[str, Any]] = []
        if thinking:
            blocks.append({"type": "thinking", "thinking": "..."})
        if not tools or rng.random() < 0.5:
            blocks.append({"type": "text", "text": "..."})
        blocks += [{"type": "tool_use", "id": self._uuid(), "name": t, "input": {}} for t in tools]

        request_id = f"req_{self._uuid()}"
        message_id = f"msg_{self._uuid()}"
        partial = rng.random() < 0.1  # some versions log growing counts while streaming
        for i, block in enumerate(blocks):
            last = i == len(blocks) - 1
            line_usage = (
                usage
                if last or not partial
                else {**usage, "output_tokens": rng.randint(1, max(output // 4, 1))}
            )
            self._emit(
                {
                    "type": "assistant",
                    "requestId": request_id,
                    "effort": self.effort,
                    "message": {
                        "id": message_id,
                        "model": model_id,
                        "role": "assistant",
                        "stop_reason": "tool_use" if tools else "end_turn",
                        "content": [block],
                        "usage": line_usage,
                    },
                }
            )
        self.summary.requests += 1
        self.now += timedelta(seconds=2 + output / 60)
        self.cached = self.context
        self.cache_written_at = self.now
        self.context += output
        return input_tokens + cache_read + cache_creation + output

    def _subagents(self, prompt_id: str) -> None:
        """Start 1-3 subagents. Each writes its own file; its tokens count for this turn."""
        spawn_line = self.last_uuid  # the assistant line that called the Task tool
        for _ in range(self.rng.randint(1, 3)):
            self._subagent(prompt_id, spawn_line)

    def _subagent(self, prompt_id: str, parent: str | None) -> None:
        rng = self.rng
        agent_id = self._uuid().replace("-", "")[:16]
        model_id = MODELS[_pick(rng, {"sonnet": 0.6, "haiku": 0.4})][0]
        lines: list[str] = []
        context = int(_lognormal(rng, 12_000, 0.2))
        cached = 0

        records: list[dict[str, Any]] = [
            {
                "type": "user",
                "timestamp": _iso(self.now),
                "message": {"role": "user", "content": "Investigate and report back."},
            }
        ]
        n_calls = 1 + int(_lognormal(rng, 4, 0.6))
        for call in range(n_calls):
            final = call == n_calls - 1
            output = min(int(_lognormal(rng, 400, 0.7)), 16_000)
            cache_read = min(cached, context)
            cache_creation = context - cache_read
            block = (
                {"type": "text", "text": "..."}
                if final
                else {
                    "type": "tool_use",
                    "id": self._uuid(),
                    "name": rng.choice(_TOOLS),
                    "input": {},
                }
            )
            records.append(
                {
                    "type": "assistant",
                    "requestId": f"req_{self._uuid()}",
                    "timestamp": _iso(self.now),
                    "message": {
                        "id": f"msg_{self._uuid()}",
                        "model": model_id,
                        "role": "assistant",
                        "stop_reason": "end_turn" if final else "tool_use",
                        "content": [block],
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": output,
                            "cache_read_input_tokens": cache_read,
                            "cache_creation_input_tokens": cache_creation,
                        },
                    },
                }
            )
            self.summary.subagent_requests += 1
            self.summary.turn_totals[prompt_id] += 3 + cache_read + cache_creation + output
            self.now += timedelta(seconds=2 + output / 80)
            cached = context
            context += output + (0 if final else min(int(_lognormal(rng, 900, 0.9)), 20_000))

        for rec in records:
            rec.update(
                uuid=self._uuid(),
                parentUuid=parent,
                sessionId=self.session_id,
                agentId=agent_id,
                isSidechain=True,
                cwd=self.cwd,
            )
            parent = rec["uuid"]
            lines.append(json.dumps(rec, separators=(",", ":")) + "\n")
        path = self.dir / self.session_id / "subagents" / f"agent-{agent_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(lines))

    # -- helpers ----------------------------------------------------------------------

    def _prompt_text(self, task: str) -> tuple[str, bool]:
        rng = self.rng
        if task == "shell":
            return f"<bash-input>{rng.choice(_SHELL)}</bash-input>", False
        text = rng.choice(_PROMPTS[task]).format(file=rng.choice(_FILES), thing=rng.choice(_THINGS))
        pasted = rng.random() < 0.15  # a pasted stack trace or log
        if pasted:
            text += "\n\n" + "Traceback (most recent call last):\n  ...\n" * rng.randint(5, 60)
        return text, pasted

    def _tools(self) -> list[str]:
        return [self.rng.choice(_TOOLS) for _ in range(2 if self.rng.random() < 0.15 else 1)]

    def _emit(self, rec: dict[str, Any]) -> None:
        """Add the common fields every Claude Code line carries and buffer the line."""
        rec.setdefault("uuid", self._uuid())
        rec.setdefault("parentUuid", self.last_uuid)
        stamp = self.now
        if rec["type"] == "attachment" and self.rng.random() < 0.3:
            stamp -= timedelta(milliseconds=200)  # real logs have small time inversions
        rec.update(
            sessionId=self.session_id,
            timestamp=_iso(stamp),
            cwd=self.cwd,
            gitBranch="main",
            version="2.1.295",
            isSidechain=False,
        )
        self.last_uuid = rec["uuid"]
        self.lines.append(json.dumps(rec, separators=(",", ":")) + "\n")

    def _write_noise_lines(self) -> None:
        self.lines.insert(
            0,
            json.dumps(
                {"type": "custom-title", "customTitle": "synthetic", "sessionId": self.session_id}
            )
            + "\n",
        )
        if self.rng.random() < 0.05:  # a half-written line, as if the app crashed mid-write
            self.lines.append('{"type":"assistant","requestId":"req_trunc\n')
            self.summary.malformed_lines += 1

    def _uuid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))


def is_synthetic(root: Path) -> bool:
    """True if ``root`` holds generated logs (marker file or synthetic project folders)."""
    if (root / MARKER_FILE).exists():
        return True
    return root.is_dir() and any(
        p.name.startswith(SYNTHETIC_PROJECT_PREFIX) for p in root.iterdir()
    )


def is_synthetic_db(con: "duckdb.DuckDBPyConnection") -> bool:
    """True if a database holds generated sessions (their cwd starts with /synthetic/)."""
    row = con.execute("SELECT count(*) FROM sessions WHERE cwd LIKE '/synthetic/%'").fetchone()
    return bool(row and row[0])


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _lognormal(rng: random.Random, median: float, sigma: float) -> float:
    """Lognormal sample with the given median: most values near it, a long right tail."""
    return rng.lognormvariate(math.log(median), sigma)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
