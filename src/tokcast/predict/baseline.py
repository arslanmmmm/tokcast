"""The baseline predictor: explainable quantiles on a log scale.

What it predicts for one turn, as an 80% range (P10-P90) plus a median:
- total tokens processed: what fills usage limits; dominated by re-reading the context
- output tokens: what the model writes (including thinking)

How (each step is something you can say out loud):
1. Cost is mostly "calls x context", so for the total it learns *re-reads* =
   total / context_before, and multiplies by the context you are about to send.
   The same prompt costs far more in a 300k-token chat than in a fresh one.
2. Work in logs: token counts are heavy-tailed, and on a log scale a multiplier
   ("high effort costs 1.3x") becomes a simple shift.
3. Three *effects* are multipliers: phase (first turn of a session or later), effort
   and model. Each is estimated from history as an average shift, then *shrunk*
   toward a built-in assumption: with 2 turns of data the assumption dominates, with
   200 the data does (each level's n turns are weighed against SHRINK pseudo-turns).
4. What remains is the spread within a task type, taken from the user's own turns of
   that type. With fewer than MIN_GROUP of them it falls back to all turns, and with
   no usable history to a built-in prior. Every estimate reports the level it used.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tokcast.predict import priors

QUANTILES = (0.1, 0.5, 0.9)
Z90 = 1.2816  # standard normal quantile: median +- Z90 * sigma covers 80%
MIN_GROUP = 8  # turns needed before a group's own quantiles are trusted
SHRINK = 20  # pseudo-turns given to the built-in assumption for an effect
MIN_CONTEXT = 1_000  # guards the re-reads ratio against near-zero contexts

FIRST, LATER = "first turn", "later turn"


@dataclass(frozen=True)
class Query:
    task_type: str
    model: str  # family: opus, sonnet, haiku, fable
    effort: str
    first_turn: bool
    context_tokens: float  # context the turn starts with, including the prompt
    prompt_tokens: int = 0  # size of the prompt itself (part of context_tokens)


@dataclass(frozen=True)
class Range:
    low: int
    median: int
    high: int


@dataclass
class Estimate:
    model: str
    effort: str
    total: Range
    output: Range
    level: str  # "task", "all" or "prior"
    group: str  # human-readable group, e.g. "bugfix turns"
    n: int  # history turns behind the spread (0 for the prior)
    adjustments: list[str] = field(default_factory=list)  # e.g. "high effort x1.31 (assumed)"


@dataclass(frozen=True)
class _Effect:
    log: float  # shift on the log scale
    n: int  # turns at this level in the history


class _Dimension:
    """One multiplicative effect (phase, effort or model) with its built-in assumption."""

    def __init__(self, column: str, prior: dict[str, float], default_ref: str):
        self.column = column
        self.prior = {k: math.log(v) for k, v in prior.items()}
        self.ref = default_ref  # most common level in the history, once fitted
        self.effects: dict[str, _Effect] = {}

    def fit(self, levels: pd.Series, residual: pd.Series) -> None:
        """Shift per level, anchored at the most common level and shrunk to the prior.

        The data only says how levels differ *from each other*, so the most common level
        is pinned to its assumed value and the others are measured relative to it.

        Uses the *mean* of log residuals, not the median: calls per turn are small whole
        numbers, and a median of such lumpy data barely moves (on synthetic data with a
        known 1.35x effect for high effort, the median found 1.04x, the mean 1.45x).
        """
        counts = levels.value_counts()
        self.ref = str(counts.idxmax())
        means = residual.groupby(levels).mean()
        anchor = self.prior.get(self.ref, 0.0)
        for level in set(self.prior) | set(counts.index):
            p = self.prior.get(level, 0.0)
            n = int(counts.get(level, 0))
            if n == 0:
                self.effects[level] = _Effect(p, 0)
            else:
                from_data = means[level] - means[self.ref] + anchor
                self.effects[level] = _Effect((n * from_data + SHRINK * p) / (n + SHRINK), n)

    def effect(self, level: str) -> _Effect:
        return self.effects.get(level) or _Effect(self.prior.get(level, 0.0), 0)

    def shift(self, levels: pd.Series) -> pd.Series:
        return levels.map(lambda level: self.effect(level).log)


class _LogTarget:
    """Quantiles of one log-scale target after removing the phase, effort and model effects."""

    def __init__(self, first_turn: float, effort: dict[str, float], model: dict[str, float]):
        self.dims = [
            _Dimension("phase", {FIRST: first_turn, LATER: 1.0}, LATER),
            _Dimension("effort", effort, "medium"),
            _Dimension("model", model, "sonnet"),
        ]
        # task type (or "*" for all) -> (log quantiles, number of turns), computed at fit
        self.groups: dict[str, tuple[np.ndarray, int]] = {}

    def fit(self, df: pd.DataFrame, y: pd.Series) -> None:
        if df.empty:
            return
        # Measure each effect on what the task type and earlier effects don't explain,
        # so e.g. "high effort is mostly used for big features" isn't read as an effort
        # effect. One pass each, in a fixed order: simple and explainable.
        residual = y - self._task_median(df, y)
        for dim in self.dims:
            dim.fit(df[dim.column], residual)
            residual = residual - dim.shift(df[dim.column])
        adjusted = y - sum(dim.shift(df[dim.column]) for dim in self.dims)
        for task, part in adjusted.groupby(df["task_type"]):
            self.groups[str(task)] = (np.quantile(part, QUANTILES), len(part))
        self.groups["*"] = (np.quantile(adjusted, QUANTILES), len(adjusted))

    @staticmethod
    def _task_median(df: pd.DataFrame, y: pd.Series) -> pd.Series:
        by_task = y.groupby(df["task_type"])
        return by_task.transform("median").where(by_task.transform("size") >= MIN_GROUP, y.median())

    def quantiles(self, task_type: str) -> tuple[np.ndarray, str, int] | None:
        """Adjusted-log quantiles of the narrowest group with enough turns."""
        for key, level in ((task_type, "task"), ("*", "all")):
            found = self.groups.get(key)
            if found is not None and found[1] >= MIN_GROUP:
                return found[0], level, found[1]
        return None

    def shift_for(self, q: Query) -> float:
        levels = {"phase": FIRST if q.first_turn else LATER, "effort": q.effort, "model": q.model}
        return sum(dim.effect(levels[dim.column]).log for dim in self.dims)


class BaselinePredictor:
    """Fit on a table of past turns, then estimate ranges for new prompts."""

    def __init__(self) -> None:
        self.total = _LogTarget(priors.FIRST_TURN, priors.EFFORT_TOTAL, priors.MODEL_TOTAL)
        self.output = _LogTarget(priors.FIRST_TURN, priors.EFFORT_OUTPUT, priors.MODEL_OUTPUT)
        self.n_turns = 0

    def fit(self, turns: pd.DataFrame) -> "BaselinePredictor":
        """``turns`` needs: task_type, first_turn, model, effort, context_tokens_before,
        output_tokens, total_tokens (see features.build.load_turns)."""
        if turns.empty:  # no history yet: every estimate uses the built-in assumptions
            return self
        df = turns.assign(phase=np.where(turns["first_turn"], FIRST, LATER))
        self.n_turns = len(df)
        context = df["context_tokens_before"].clip(lower=MIN_CONTEXT)
        self.total.fit(df, np.log(df["total_tokens"] / context))
        self.output.fit(df, np.log1p(df["output_tokens"]))
        return self

    def predict(self, q: Query) -> Estimate:
        total_q = self.total.quantiles(q.task_type)
        output_q = self.output.quantiles(q.task_type)
        if total_q is None or output_q is None:
            # Not enough history: lognormal around the built-in assumption. Priors are for
            # a later turn at sonnet/medium; the effects below scale them like real data.
            spread = np.array([-Z90, 0.0, Z90])
            t_median = math.log(priors.rereads(q.task_type, first_turn=False))
            o_median = math.log1p(priors.output_tokens(q.task_type, first_turn=False))
            total_q = (t_median + spread * priors.SPREAD_TOTAL, "prior", 0)
            output_q = (o_median + spread * priors.SPREAD_OUTPUT, "prior", 0)
        (t_logs, level, n), (o_logs, _, _) = total_q, output_q

        total = np.exp(t_logs + self.total.shift_for(q)) * max(q.context_tokens, MIN_CONTEXT)
        output = np.expm1(o_logs + self.output.shift_for(q))
        group = {
            "task": f"{q.task_type} turns",
            "all": "all turns",
            "prior": f"{q.task_type} (built-in assumption)",
        }[level]
        return Estimate(
            model=q.model,
            effort=q.effort,
            total=Range(*(round(v) for v in total)),  # tokens are whole numbers
            output=Range(*(round(v) for v in output)),
            level=level,
            group=group,
            n=n,
            adjustments=self._explain(q),
        )

    def _explain(self, q: Query) -> list[str]:
        """Multipliers on tokens processed, relative to the most-used setting, with source."""
        asked = {"phase": FIRST if q.first_turn else LATER, "effort": q.effort, "model": q.model}
        notes = []
        for dim in self.total.dims:
            level = asked[dim.column]
            if level == dim.ref:
                continue
            effect = dim.effect(level)
            factor = math.exp(effect.log - dim.effect(dim.ref).log)
            source = f"{effect.n} turns + assumption" if effect.n else "assumed"
            label = f"{level} effort" if dim.column == "effort" else level
            notes.append(f"{label} x{factor:.2f} vs {dim.ref} ({source})")
        return notes
