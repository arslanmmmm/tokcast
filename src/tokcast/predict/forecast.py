"""Put it together: one prompt in, estimates for several model/effort options out.

This is the function front ends call (the CLI today, a browser extension later). It
needs only a table of past turns, so it works with an empty history too.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

import pandas as pd

from tokcast.calibrate.mapping import Calibration, Reading
from tokcast.features.build import CurrentConversation
from tokcast.features.classify import Classification, classify
from tokcast.predict import advice as advice_mod
from tokcast.predict import priors
from tokcast.predict.baseline import BaselinePredictor, Estimate, Query, Range
from tokcast.predict.similar import similar_turns

CHARS_PER_TOKEN = 4  # rough size of the prompt itself; good enough next to the context


class Predictor(Protocol):
    """Anything that can learn from past turns and estimate a new one."""

    def fit(self, turns: pd.DataFrame) -> "Predictor": ...

    def predict(self, q: Query) -> Estimate: ...


class Method(Protocol):
    """A predictor class as `tokcast eval` uses it: named, and built with no arguments."""

    @property
    def name(self) -> str: ...

    def __call__(self) -> Predictor: ...


@dataclass
class ContextInfo:
    mode: str  # "new chat", "continue" or "given"
    tokens: float  # context before the prompt
    prompt_tokens: int
    note: str  # where the number comes from

    @property
    def total(self) -> float:
        return self.tokens + self.prompt_tokens


@dataclass
class Forecast:
    prompt_chars: int
    classification: Classification
    context: ContextInfo
    estimates: list[Estimate]  # the requested option first
    history_turns: int
    similar: list[dict] = field(default_factory=list)
    new_chat: Estimate | None = None  # same request in a fresh conversation, if cheaper
    limit_window: str | None = None  # "5h" when estimates carry limit_pct
    limit_readings: int = 0  # calibration readings so far
    limit_now: Reading | None = None  # latest usage reading, if the window is still open
    # % of the 7-day limit for the requested option (low, median, high), once calibrated
    weekly_pct: tuple[float, float, float] | None = None
    weekly_readings: int = 0  # 7-day calibration readings so far
    # set when a % leans on a plan's starting guess (calibrate/plans.py): label it "assumed"
    limit_assumed_plan: str | None = None
    weekly_assumed_plan: str | None = None
    # the cheaper next move, ranked by predicted saving (predict/advice.py)
    advice: list[advice_mod.Advice] = field(default_factory=list)


def _pct(calibration: Calibration, r: Range) -> tuple[float, float, float] | None:
    """% of the limit for a range's low, median and high; None if it can't be computed."""
    low, median, high = (calibration.pct_of_limit(v) for v in (r.low, r.median, r.high))
    if low is None or median is None or high is None:
        return None
    return (low, median, high)


def _alternatives(
    estimate: Callable[..., Estimate],
    *,
    model: str,
    effort: str,
    tokens: float,
    fresh: float,
    first: bool,
) -> list[advice_mod.Alternative]:
    """The same turn with one input changed: what the advice is chosen from."""
    found = []
    if not first:  # a fresh or compacted context only helps a conversation already going
        found.append(
            advice_mod.Alternative(
                "new_chat",
                estimate(model, effort, tokens=fresh, first=True),
                "/clear",
                "Start a new chat",
                basis=f"same task with a fresh context (~{fresh / 1000:.0f}k tokens)",
            )
        )
        compacted = fresh + priors.COMPACT_SUMMARY_TOKENS
        if tokens > compacted:
            found.append(
                advice_mod.Alternative(
                    "compact",
                    estimate(model, effort, tokens=compacted, first=False),
                    "/compact",
                    "Compact the conversation first",
                    basis=(
                        f"assumed: a /compact summary of ~{priors.COMPACT_SUMMARY_TOKENS // 1000}k"
                        " tokens on top of the fresh context"
                    ),
                    assumed=True,
                )
            )
    for m, e in options_to_compare(model, effort)[1:]:  # the same turn, other settings
        if m == model:
            found.append(
                advice_mod.Alternative(
                    "effort",
                    estimate(m, e, tokens=tokens, first=first),
                    None,  # effort is set in Claude Code's model picker
                    f"Use {e} effort",
                    caveat=", if that's enough for this task",
                    basis=f"{e} vs {effort} effort multiplier",
                )
            )
        else:
            found.append(
                advice_mod.Alternative(
                    "model",
                    estimate(m, e, tokens=tokens, first=first),
                    f"/model {m}",
                    f"Use {m}",
                    caveat=", if it can do this task (cost only, not quality)",
                    basis=f"{m} at {e} effort vs {model} at {effort}",
                )
            )
    return found


def options_to_compare(model: str, effort: str) -> list[tuple[str, str]]:
    """The requested option plus a few useful alternatives."""
    efforts = list(priors.EFFORTS)
    lower = efforts[max(efforts.index(effort) - 1, 0)] if effort in efforts else "medium"
    other = "opus" if model == "sonnet" else "sonnet"
    options = [(model, effort), (model, lower), (other, effort), ("haiku", "medium")]
    return list(dict.fromkeys(options))  # keep order, drop duplicates


def forecast(
    turns: pd.DataFrame,
    prompt: str,
    *,
    model: str,
    effort: str,
    context_mode: str = "new chat",
    context_tokens: float | None = None,
    context_note: str = "",
    conversation: CurrentConversation | None = None,
    new_chat_tokens: float | None = None,
    compare: bool = True,
    predictor: Predictor | None = None,
    calibration: Calibration | None = None,
    reading: Reading | None = None,
    weekly: Calibration | None = None,
) -> Forecast:
    classification = classify(prompt)
    predictor = (predictor or BaselinePredictor()).fit(turns)
    fresh = new_chat_tokens or priors.NEW_CHAT_CONTEXT

    if context_mode == "continue" and conversation is not None:
        tokens, first_turn = float(conversation.context_tokens), False
    elif context_mode == "given" and context_tokens is not None:
        tokens, first_turn = float(context_tokens), False
    else:
        context_mode, tokens, first_turn = "new chat", float(fresh), True
    context = ContextInfo(context_mode, tokens, len(prompt) // CHARS_PER_TOKEN, context_note)

    def estimate(m: str, e: str, *, tokens: float, first: bool) -> Estimate:
        q = Query(
            classification.task_type,
            m,
            e,
            first,
            tokens + context.prompt_tokens,
            context.prompt_tokens,
        )
        return predictor.predict(q)

    options = options_to_compare(model, effort) if compare else [(model, effort)]
    estimates = [estimate(m, e, tokens=tokens, first=first_turn) for m, e in options]

    new_chat = None
    if not first_turn:  # would starting over be cheaper? (it isn't always: first turns explore)
        alt = estimate(model, effort, tokens=fresh, first=True)
        if alt.total.median < estimates[0].total.median * 0.8:
            new_chat = alt

    if calibration is not None and calibration.ready:  # new objects, not edits in place
        estimates = [replace(e, limit_pct=_pct(calibration, e.total)) for e in estimates]
        if new_chat is not None:
            new_chat = replace(new_chat, limit_pct=_pct(calibration, new_chat.total))

    weekly_pct = None
    if weekly is not None and weekly.ready:
        weekly_pct = _pct(weekly, estimates[0].total)

    alternatives = _alternatives(
        estimate, model=model, effort=effort, tokens=tokens, fresh=fresh, first=first_turn
    )
    advice = advice_mod.rank(estimates[0], alternatives, calibration)

    return Forecast(
        weekly_pct=weekly_pct,
        weekly_readings=len(weekly.points) if weekly is not None else 0,
        limit_assumed_plan=calibration.assumed_plan if calibration is not None else None,
        weekly_assumed_plan=weekly.assumed_plan if weekly is not None else None,
        limit_window=calibration.window if calibration is not None else None,
        limit_readings=len(calibration.points) if calibration is not None else 0,
        limit_now=reading,
        prompt_chars=len(prompt),
        classification=classification,
        context=context,
        estimates=estimates,
        history_turns=len(turns),
        similar=similar_turns(turns, prompt),
        new_chat=new_chat,
        advice=advice,
    )
