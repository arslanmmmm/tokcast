"""Simple reference methods to compare the baseline against.

A score only means something next to alternatives. Each method here implements the same
fit/predict interface as BaselinePredictor, so the backtest treats them identically.
"""

import numpy as np
import pandas as pd

from tokcast.predict import BaselinePredictor, Estimate, Query, Range
from tokcast.predict.baseline import MIN_CONTEXT, QUANTILES


def _range(values) -> Range:
    return Range(*(round(float(v)) for v in values))


def _estimate(q: Query, total, output, group: str, n: int) -> Estimate:
    return Estimate(q.model, q.effort, _range(total), _range(output), "all", group, n)


class GlobalMedian:
    """The same range for every turn: quantiles of all past totals. No features at all."""

    name = "global median"

    def fit(self, turns: pd.DataFrame) -> "GlobalMedian":
        self.total = np.quantile(turns["total_tokens"], QUANTILES)
        self.output = np.quantile(turns["output_tokens"], QUANTILES)
        self.n = len(turns)
        return self

    def predict(self, q: Query) -> Estimate:
        return _estimate(q, self.total, self.output, "all turns", self.n)


class ContextRereads:
    """Our core idea alone: typical re-reads x current context, nothing else."""

    name = "context x re-reads"

    def fit(self, turns: pd.DataFrame) -> "ContextRereads":
        context = turns["context_tokens_before"].clip(lower=MIN_CONTEXT)
        self.rereads = np.quantile(turns["total_tokens"] / context, QUANTILES)
        self.output = np.quantile(turns["output_tokens"], QUANTILES)
        self.n = len(turns)
        return self

    def predict(self, q: Query) -> Estimate:
        total = self.rereads * max(q.context_tokens, MIN_CONTEXT)
        return _estimate(q, total, self.output, "all turns", self.n)


# Output tokens per prompt token by task type, and the +-20% band, as in a published
# single-request estimator (ctok). Used to show what ignoring the tool loop costs.
_SINGLE_CALL_OUTPUT_RATIO = {
    "feature": 1.4,
    "refactor": 1.2,
    "bugfix": 0.8,
    "tests": 1.0,
    "explain": 1.0,
    "docs": 1.0,
}


class SingleCall:
    """A pre-send estimate for ONE request: context + prompt + output, no tool loop."""

    name = "single call (ctok-style)"

    def fit(self, turns: pd.DataFrame) -> "SingleCall":
        return self  # fixed rules; learns nothing

    def predict(self, q: Query) -> Estimate:
        ratio = _SINGLE_CALL_OUTPUT_RATIO.get(q.task_type, 1.0)
        output = min(max(q.prompt_tokens * ratio, 150), 8_000)  # floor and cap as in ctok
        total = q.context_tokens + output
        band = np.array([0.8, 1.0, 1.2])
        return _estimate(q, total * band, output * band, "fixed rules", 0)


class PriorsOnly:
    """What a brand-new user gets: the baseline with no history at all."""

    name = "assumptions only"

    def fit(self, turns: pd.DataFrame) -> "PriorsOnly":
        self.model = BaselinePredictor().fit(turns.iloc[0:0])
        return self

    def predict(self, q: Query) -> Estimate:
        return self.model.predict(q)


class Baseline(BaselinePredictor):
    name = "tokcast baseline"


def all_methods() -> list:
    return [GlobalMedian(), SingleCall(), ContextRereads(), PriorsOnly(), Baseline()]
