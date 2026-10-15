"""Walk-forward backtest: predict later turns using only the turns before them.

Turns are sorted by time. The newest ``test_fraction`` of them is the test set, cut into
``folds`` chunks; each chunk is predicted by a model trained on every turn *before* that
chunk, as if `tokcast predict` had been run at that moment. A random split would let the
model learn from the future (later turns of the same sessions, newer habits) and make
the scores look better than they would be in real use.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise

import numpy as np
import pandas as pd

from tokcast.evaluate.metrics import Scores, paired_difference, pinball_per_turn, score
from tokcast.evaluate.reference import all_methods
from tokcast.predict import Predictor, Query

MIN_TURNS = 30  # below this, a backtest says more about noise than about the model
BASELINE = "tokcast baseline"


@dataclass
class MethodResult:
    name: str
    total: Scores
    output: Scores
    # Pinball loss minus the baseline's on the same turns (tokens processed): mean and 95%
    # interval. Negative = better than the baseline. None for the baseline itself.
    vs_baseline: tuple[float, float, float] | None = None


@dataclass
class BacktestResult:
    data: str  # "real" or "synthetic"
    n_turns: int
    n_test: int
    folds: int
    first_ts: datetime
    test_from: datetime
    last_ts: datetime
    methods: list[MethodResult] = field(default_factory=list)

    def method(self, name: str) -> MethodResult:
        return next(m for m in self.methods if m.name == name)


def walk_forward_splits(
    turns: pd.DataFrame, folds: int, test_fraction: float
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """(train, test) pairs; every training turn is older than every test turn of its fold."""
    n = len(turns)
    n_test = max(folds, round(n * test_fraction))
    bounds = np.linspace(n - n_test, n, folds + 1).round().astype(int)
    return [
        (turns.iloc[:start], turns.iloc[start:end])
        for start, end in pairwise(bounds)
        if end > start
    ]


def queries_for(test: pd.DataFrame) -> list[Query]:
    """What we would have known before each turn: its prompt, settings and context."""
    return [
        Query(
            task_type=row.task_type,
            model=row.model,
            effort=row.effort,
            first_turn=bool(row.first_turn),
            context_tokens=float(row.context_tokens_before),
            prompt_tokens=int(row.text_chars) // 4,
        )
        for row in test.itertuples(index=False)
    ]


def backtest(
    turns: pd.DataFrame,
    *,
    data: str,
    folds: int = 5,
    test_fraction: float = 0.5,
    methods: list[Callable[[], Predictor]] | None = None,
) -> BacktestResult:
    """Score every method on the same walk-forward splits."""
    turns = turns[turns["ts"].notna()].sort_values(["ts", "turn_id"]).reset_index(drop=True)
    if len(turns) < MIN_TURNS:
        raise ValueError(f"only {len(turns)} usable turns; a backtest needs at least {MIN_TURNS}")
    factories = methods or all_methods()
    splits = walk_forward_splits(turns, folds, test_fraction)
    test = pd.concat([t for _, t in splits])

    results: list[MethodResult] = []
    losses: dict[str, np.ndarray] = {}
    for make in factories:
        total, output = [], []
        for train, chunk in splits:
            model = make().fit(train)  # a fresh model per fold: no state leaks across folds
            queries = queries_for(chunk)
            many = getattr(model, "predict_many", None)  # optional faster batch path
            for est in many(queries) if many else map(model.predict, queries):
                total.append((est.total.low, est.total.median, est.total.high))
                output.append((est.output.low, est.output.median, est.output.high))
        t, o = np.array(total), np.array(output)
        losses[make.name] = pinball_per_turn(test["total_tokens"], t)
        results.append(
            MethodResult(
                name=make.name,
                total=score(test["total_tokens"], t[:, 0], t[:, 1], t[:, 2]),
                output=score(test["output_tokens"], o[:, 0], o[:, 1], o[:, 2]),
            )
        )
    if BASELINE in losses:
        for r in results:
            if r.name != BASELINE:
                r.vs_baseline = paired_difference(losses[r.name], losses[BASELINE])
    return BacktestResult(
        data=data,
        n_turns=len(turns),
        n_test=len(test),
        folds=len(splits),
        first_ts=turns["ts"].iloc[0],
        test_from=test["ts"].iloc[0],
        last_ts=turns["ts"].iloc[-1],
        methods=results,
    )
