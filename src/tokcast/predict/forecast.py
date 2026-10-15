"""Put it together: one prompt in, estimates for several model/effort options out.

This is the function front ends call (the CLI today, a browser extension later). It
needs only a table of past turns, so it works with an empty history too.
"""

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from tokcast.features.build import CurrentConversation
from tokcast.features.classify import Classification, classify
from tokcast.predict import priors
from tokcast.predict.baseline import BaselinePredictor, Estimate, Query
from tokcast.predict.similar import similar_turns

CHARS_PER_TOKEN = 4  # rough size of the prompt itself; good enough next to the context


class Predictor(Protocol):
    """Anything that can learn from past turns and estimate a new one."""

    def fit(self, turns: pd.DataFrame) -> "Predictor": ...

    def predict(self, q: Query) -> Estimate: ...


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

    return Forecast(
        prompt_chars=len(prompt),
        classification=classification,
        context=context,
        estimates=estimates,
        history_turns=len(turns),
        similar=similar_turns(turns, prompt),
        new_chat=new_chat,
    )
