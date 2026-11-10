"""The cheaper next move (milestone 11a): what-if estimates from tokcast's own model, ranked.

Each alternative re-asks the predictor the same question with one input changed (a fresh
context, a compacted one, a lower effort, another model), so a saving is the *model's*
counterfactual for the same task, never a measured one: every message says "predicted".
Advice about prompt wording (e.g. "name the files") is deliberately absent: from one user's
observational history it would be confounded by task difficulty (docs/plan.md, decision 37).
"""

from dataclasses import dataclass

from tokcast.calibrate.mapping import Calibration
from tokcast.predict.baseline import Estimate

MIN_SAVING = 0.2  # below a 20% saving, a tip isn't worth the interruption
MAX_ITEMS = 3


@dataclass(frozen=True)
class Alternative:
    """One input changed, and what the model predicts for it."""

    kind: str  # "new_chat", "compact", "effort" or "model"
    estimate: Estimate
    action: str | None  # what to type in Claude Code; None when there's no command for it
    label: str  # e.g. "Start a new chat"
    caveat: str = ""  # e.g. ", if it can do this task"
    basis: str = ""
    assumed: bool = False


@dataclass(frozen=True)
class Advice:
    kind: str
    action: str | None
    message: str  # one line, the same in the CLI and the Claude Code mod
    saving_share: float  # predicted share of the turn's tokens saved (median), 0..1
    tokens_saved: int  # predicted, median
    limit_pct_saved: float | None  # points of the usage-limit window saved, once calibrated
    basis: str
    assumed: bool


def _limit_points(calibration: Calibration | None, tokens: float) -> float | None:
    if calibration is None or not calibration.ready:
        return None
    return calibration.pct_of_limit(tokens)


def rank(
    current: Estimate,
    alternatives: list[Alternative],
    calibration: Calibration | None = None,
) -> list[Advice]:
    """Alternatives that save at least MIN_SAVING of the predicted median, biggest first."""
    now = current.total.median
    found = []
    for alt in alternatives:
        saved = now - alt.estimate.total.median
        share = saved / now if now else 0.0
        if share < MIN_SAVING:
            continue
        points = _limit_points(calibration, saved)
        window = calibration.window if calibration is not None else "5h"
        limit = f" (≈{points:.1f} points of your {window} limit)" if points else ""
        command = f" ({alt.action})" if alt.action else ""
        message = f"{alt.label}{command}: ~{share:.0%} fewer tokens predicted{limit}{alt.caveat}"
        found.append(
            Advice(
                kind=alt.kind,
                action=alt.action,
                message=message,
                saving_share=round(share, 4),
                tokens_saved=int(saved),
                limit_pct_saved=round(points, 3) if points else None,
                basis=alt.basis,
                assumed=alt.assumed,
            )
        )
    found.sort(key=lambda a: a.saving_share, reverse=True)
    return found[:MAX_ITEMS]
