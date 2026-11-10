"""Milestone 10b: a per-plan starting guess for % of limit, used only before 3 readings."""

import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from tokcast import calibrate as cal
from tokcast.calibrate import plans
from tokcast.cli import app
from tokcast.predict import forecast

PRO_5H_LOW, PRO_5H_K, PRO_5H_HIGH = plans.PRO_K["5h"]


def readings(window, ratios):
    return [{"pct_per_million": r} for r in ratios]


def test_no_readings_uses_the_plan_guess_and_says_so():
    c = plans.with_plan_prior(cal.Calibration("5h"), "pro")

    assert c.ready
    assert c.k == pytest.approx(PRO_5H_K)
    assert c.assumed_plan == "pro"
    assert c.turn_weight == plans.PRO_TURN_WEIGHT  # no history yet either


def test_max_plans_have_proportionally_more_room():
    pro = plans.with_plan_prior(cal.Calibration("5h"), "pro")
    max5 = plans.with_plan_prior(cal.Calibration("5h"), "max5x")
    max20 = plans.with_plan_prior(cal.Calibration("5h"), "max20x")

    assert max5.k == pytest.approx(pro.k / 5)
    assert max20.k == pytest.approx(pro.k / 20)


def test_own_readings_take_over_gradually():
    # 1 reading of the user's own, at k = 20: the guess counts as 3 pretend readings.
    mine = cal.Calibration(
        "5h", points=readings("5h", [20.0]), k=20.0, k_low=20.0, k_high=20.0, turn_weight=0.2
    )

    c = plans.with_plan_prior(mine, "pro")

    assert c.k == pytest.approx((1 * 20.0 + 3 * PRO_5H_K) / 4)
    assert c.turn_weight == 0.2  # the user's own history wins
    assert c.assumed_plan == "pro"


def test_from_3_readings_the_users_own_calibration_is_untouched():
    mine = cal.Calibration(
        "5h", points=readings("5h", [9, 10, 11]), k=10.0, k_low=9.2, k_high=10.8, turn_weight=0.2
    )

    assert plans.with_plan_prior(mine, "pro") == mine  # same values, no "assumed" label


def test_unknown_plan_is_rejected():
    with pytest.raises(ValueError, match="pro, max5x, max20x"):
        plans.with_plan_prior(cal.Calibration("5h"), "team")


def test_forecast_shows_assumed_percent_from_the_first_prompt():
    five = plans.with_plan_prior(cal.Calibration("5h"), "pro")
    week = plans.with_plan_prior(cal.Calibration("7d"), "pro")

    f = forecast(
        pd.DataFrame(), "fix it", model="opus", effort="medium", calibration=five, weekly=week
    )

    assert f.estimates[0].limit_pct is not None and f.weekly_pct is not None
    assert (f.limit_assumed_plan, f.weekly_assumed_plan) == ("pro", "pro")


def test_cli_predict_with_a_plan_on_a_fresh_install(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TOKCAST_LOGS", str(tmp_path / "no-logs"))
    runner = CliRunner()

    out = json.loads(
        runner.invoke(app, ["predict", "fix the bug", "--plan", "pro", "--json"]).output
    )
    text = runner.invoke(app, ["predict", "fix the bug", "--plan", "pro"], env={"COLUMNS": "160"})
    bad = runner.invoke(app, ["predict", "fix the bug", "--plan", "team"])

    assert out["estimates"][0]["limit_pct"] is not None and out["weekly_pct"] is not None
    assert out["limit_assumed_plan"] == "pro"
    assert "assumed" in text.output
    assert bad.exit_code == 1 and "max20x" in bad.output
