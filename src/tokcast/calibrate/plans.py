"""A starting guess for "% of usage limit" per plan, used only before 3 own readings.

Milestone 10b (docs/plan.md, decision 32). Readings can't be backfilled, so a new user
would otherwise see no percentage for hours. Below MIN_POINTS readings, k blends the
plan's guess (worth PSEUDO_READINGS readings) with the user's own; from MIN_POINTS on,
the user's own calibration is used unchanged, so the validated path is untouched.

**Assumed, from one user.** The Pro values were fitted on 2026-11-10 with the totals
method on the author's readings (110 for 5h, 54 for 7d; Pro plan). They include the
author's claude.ai usage, so they err high. Max plans divide k by Anthropic's stated
usage multiple, assumed to hold for the weekly window too.
"""

from dataclasses import replace

from tokcast.calibrate.mapping import MIN_POINTS, Calibration

PLAN_MULTIPLE = {"pro": 1.0, "max5x": 5.0, "max20x": 20.0}  # usage relative to Pro
PRO_K = {  # % of the limit per million weighted tokens: P10, median, P90
    "5h": (6.2, 7.21, 13.8),
    "7d": (1.05, 1.43, 2.99),
}
PRO_TURN_WEIGHT = 0.12  # median weighted / total tokens of the author's turns
PSEUDO_READINGS = 3  # the guess counts as this many readings while blending


def _blend(own: float | None, guess: float, n: int) -> float:
    if own is None or n == 0:
        return guess
    return (n * own + PSEUDO_READINGS * guess) / (n + PSEUDO_READINGS)


def with_plan_prior(cal: Calibration, plan: str) -> Calibration:
    """``cal`` leaning on ``plan``'s guess while it has fewer than MIN_POINTS readings."""
    if plan not in PLAN_MULTIPLE:
        raise ValueError(f"Unknown plan {plan!r}: use one of {', '.join(PLAN_MULTIPLE)}")
    n = len(cal.points)
    if n >= MIN_POINTS and cal.k is not None:
        return cal
    low, k, high = (v / PLAN_MULTIPLE[plan] for v in PRO_K[cal.window])
    return replace(
        cal,
        k_low=_blend(cal.k_low, low, n),
        k=_blend(cal.k, k, n),
        k_high=_blend(cal.k_high, high, n),
        turn_weight=cal.turn_weight or PRO_TURN_WEIGHT,
        assumed_plan=plan,
    )
