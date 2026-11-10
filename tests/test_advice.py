"""Milestone 11a: "the cheaper next move", ranked from the model's own what-if estimates."""

import pandas as pd
import pytest

from tokcast import calibrate as cal
from tokcast.predict import advice, forecast, priors


def long_chat(**kwargs):
    """A follow-up in a 2M-token conversation at high effort: several cheaper moves exist."""
    defaults = dict(
        model="opus",
        effort="high",
        context_mode="given",
        context_tokens=2_000_000,
        context_note="from --context",
        compare=False,  # advice doesn't depend on the comparison table
    )
    return forecast(pd.DataFrame(), "now fix the failing test", **(defaults | kwargs))


def test_a_long_chat_gets_ranked_advice():
    f = long_chat()

    kinds = [a.kind for a in f.advice]
    shares = [a.saving_share for a in f.advice]

    # Re-reading 2M tokens per call dominates: a compacted or fresh context comes first.
    # (/compact can beat a new chat: a first turn explores the project again, x2.5.)
    assert set(kinds[:2]) == {"compact", "new_chat"}
    assert "effort" in kinds
    assert shares == sorted(shares, reverse=True)
    assert all(s >= advice.MIN_SAVING for s in shares)
    assert len(f.advice) <= advice.MAX_ITEMS


def test_savings_are_the_models_what_if_numbers():
    f = long_chat()
    now = f.estimates[0].total.median
    top = f.advice[0]

    assert top.tokens_saved == pytest.approx(now * top.saving_share, rel=0.01)
    assert {a.action for a in f.advice} >= {"/clear", "/compact"}
    assert all("predicted" in a.message for a in f.advice)


def test_assumptions_are_labelled():
    compact = next(a for a in long_chat().advice if a.kind == "compact")

    assert compact.assumed
    assert f"{priors.COMPACT_SUMMARY_TOKENS // 1000}k" in compact.basis


def test_a_new_chat_gets_no_new_chat_or_compact_advice():
    f = forecast(pd.DataFrame(), "add a flag", model="opus", effort="high", compare=False)

    assert not {"new_chat", "compact"} & {a.kind for a in f.advice}


def test_nothing_cheaper_means_no_advice():
    f = forecast(pd.DataFrame(), "add a flag", model="opus", effort="low", compare=False)

    assert f.advice == []  # lowest effort already, a fresh chat, opus is the leanest family


def test_limit_points_saved_once_calibrated():
    calibrated = cal.Calibration(
        "5h", points=[{}] * 3, k=7.0, k_low=6.0, k_high=13.0, turn_weight=0.12
    )

    f = long_chat(calibration=calibrated)
    top = f.advice[0]

    now_pct = f.estimates[0].limit_pct[1]
    assert top.limit_pct_saved == pytest.approx(now_pct * top.saving_share, rel=0.01)
    assert "of your 5h limit" in top.message
