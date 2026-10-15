"""Quantile regression: a challenger to the baseline (needs `pip install tokcast[ml]`).

Same targets and inputs as the baseline, so `tokcast eval` compares like with like:
- targets: log re-reads (total / context) and log output tokens
- features: task type, model and effort (one-hot), first turn, log context, log prompt size

One model per quantile (P10, P50, P90), each trained to minimise the pinball loss for its
quantile. Two flavours:
- linear: one coefficient per feature, easy to read ("high effort: +0.27 on log scale")
- boosted: gradient-boosted trees, which can learn interactions between features

Guardrails, because a regression can't know what it hasn't seen:
- with fewer than MIN_TRAIN turns it hands over to the baseline;
- for a model or effort level absent from training it also hands over, since the
  baseline has (labelled) assumptions for those and the regression has nothing.
"""

import numpy as np
import pandas as pd

from tokcast.features.classify import TASK_TYPES
from tokcast.predict import priors
from tokcast.predict.baseline import (
    MIN_CONTEXT,
    QUANTILES,
    BaselinePredictor,
    Estimate,
    Query,
    Range,
)

MIN_TRAIN = 150  # below this, a regression with ~20 features is mostly noise

# One-hot columns; the first level of each list is the reference and gets no column.
_CATEGORIES = {
    "task_type": ("other", *(t for t in TASK_TYPES if t != "other")),
    "model": ("sonnet", *(m for m in priors.MODELS if m != "sonnet"), "other"),
    "effort": ("medium", *(e for e in priors.EFFORTS if e != "medium"), "unknown"),
}
FEATURES = [f"{col}={level}" for col, levels in _CATEGORIES.items() for level in levels[1:]] + [
    "first_turn",
    "log_context",
    "log_prompt",
]


def feature_matrix(df: pd.DataFrame) -> np.ndarray:
    """Columns as in FEATURES. ``df`` needs task_type, model, effort, first_turn,
    context (tokens) and prompt_tokens."""
    columns = [
        (df[col] == level).astype(float).to_numpy()
        for col, levels in _CATEGORIES.items()
        for level in levels[1:]
    ]
    columns += [
        df["first_turn"].astype(float).to_numpy(),
        np.log(df["context"].clip(lower=MIN_CONTEXT)).to_numpy(),
        np.log1p(df["prompt_tokens"]).to_numpy(),
    ]
    return np.column_stack(columns)


def _make_estimator(kind: str, quantile: float):
    if kind == "linear":
        from sklearn.linear_model import QuantileRegressor

        # alpha: a small L1 penalty keeps rarely-seen one-hot columns from blowing up.
        return QuantileRegressor(quantile=quantile, alpha=1e-4, solver="highs")
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        max_iter=150,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=20,
        random_state=0,
    )


class QuantileRegressionPredictor:
    """Fit/predict like BaselinePredictor; falls back to it where regression can't help."""

    def __init__(self, kind: str = "linear"):
        self.kind = kind
        self.name = f"quantile regression ({kind})"
        self.fallback = BaselinePredictor()
        self.models: dict[str, list] | None = None
        self.seen: dict[str, set[str]] = {}
        self.n = 0

    def fit(self, turns: pd.DataFrame) -> "QuantileRegressionPredictor":
        self.fallback.fit(turns)
        self.n = len(turns)
        if self.n < MIN_TRAIN:
            self.models = None
            return self
        df = turns.assign(
            context=turns["context_tokens_before"],
            prompt_tokens=turns["text_chars"].fillna(0) // 4,
        )
        X = feature_matrix(df)
        targets = {
            "total": np.log(df["total_tokens"] / df["context"].clip(lower=MIN_CONTEXT)),
            "output": np.log1p(df["output_tokens"]),
        }
        self.models = {
            name: [_make_estimator(self.kind, q).fit(X, y) for q in QUANTILES]
            for name, y in targets.items()
        }
        self.seen = {col: set(df[col].astype(str)) for col in ("model", "effort")}
        return self

    def predict(self, q: Query) -> Estimate:
        return self.predict_many([q])[0]

    def predict_many(self, queries: list[Query]) -> list[Estimate]:
        """Batch prediction: one sklearn call per model for all queries (much faster)."""
        if self.models is None:
            return [self.fallback.predict(q) for q in queries]
        usable = [
            q.model in self.seen["model"] and q.effort in self.seen["effort"] for q in queries
        ]
        rows = pd.DataFrame(
            {
                "task_type": [q.task_type for q in queries],
                "model": [q.model for q in queries],
                "effort": [q.effort for q in queries],
                "first_turn": [q.first_turn for q in queries],
                "context": [q.context_tokens for q in queries],
                "prompt_tokens": [q.prompt_tokens for q in queries],
            }
        )
        X = feature_matrix(rows)
        # Separately fitted quantile models can cross (P10 above P50); sorting fixes that.
        t_logs = np.sort(np.column_stack([m.predict(X) for m in self.models["total"]]), axis=1)
        o_logs = np.sort(np.column_stack([m.predict(X) for m in self.models["output"]]), axis=1)
        context = np.maximum(rows["context"].to_numpy(), MIN_CONTEXT)
        totals = np.exp(t_logs) * context[:, None]
        outputs = np.expm1(o_logs)
        return [
            Estimate(
                model=q.model,
                effort=q.effort,
                total=Range(*(round(v) for v in totals[i])),
                output=Range(*(round(v) for v in outputs[i])),
                level="regression",
                group=self.name,
                n=self.n,
            )
            if usable[i]
            else self.fallback.predict(q)  # unseen model/effort: the baseline's assumptions
            for i, q in enumerate(queries)
        ]
