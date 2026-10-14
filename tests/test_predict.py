import json
import math

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from tokcast.cli import app
from tokcast.features.build import CurrentConversation, load_turns
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.predict import BaselinePredictor, Query, forecast, priors
from tokcast.predict.baseline import MIN_GROUP, Z90
from tokcast.predict.forecast import options_to_compare
from tokcast.predict.similar import similar_turns
from tokcast.synth import generate

runner = CliRunner()


def history(groups, seed=0):
    """Build a turns table. Each group: (n, task, effort, model, first_turn, rereads)."""
    rng = np.random.default_rng(seed)
    rows = []
    for n, task, effort, model, first, rereads in groups:
        noise = rng.lognormal(0, 0.3, n)
        for i in range(n):
            rows.append(
                {
                    "task_type": task,
                    "effort": effort,
                    "model": model,
                    "first_turn": first,
                    "context_tokens_before": 100_000,
                    "total_tokens": 100_000 * rereads * noise[i],
                    "output_tokens": 500 * rereads * noise[i],
                    "text": f"{task} prompt {i}",
                    "ts": pd.Timestamp("2026-10-01") + pd.Timedelta(minutes=i),
                }
            )
    return pd.DataFrame(rows)


def q(task="bugfix", model="sonnet", effort="medium", first=False, context=100_000):
    return Query(task, model, effort, first, context)


def test_empty_history_uses_the_built_in_assumption():
    e = BaselinePredictor().fit(history([])).predict(q())
    assert (e.level, e.n) == ("prior", 0)
    assert e.total.median == round(priors.CALLS["bugfix"] * 100_000)
    spread = math.exp(Z90 * priors.SPREAD_TOTAL)
    assert e.total.high == pytest.approx(e.total.median * spread, rel=1e-3)
    assert e.total.low <= e.total.median <= e.total.high


def test_total_scales_with_context_but_output_does_not():
    p = BaselinePredictor().fit(history([(40, "bugfix", "medium", "sonnet", False, 5)]))
    small, big = p.predict(q(context=100_000)), p.predict(q(context=300_000))
    assert big.total.median == pytest.approx(3 * small.total.median, rel=1e-6)
    assert big.output == small.output


def test_learns_the_users_own_task_size():
    p = BaselinePredictor().fit(history([(60, "bugfix", "medium", "sonnet", False, 10)]))
    e = p.predict(q())
    assert (e.level, e.group, e.n) == ("task", "bugfix turns", 60)
    assert e.total.median == pytest.approx(10 * 100_000, rel=0.15)


def test_small_groups_fall_back_to_all_turns():
    p = BaselinePredictor().fit(
        history(
            [
                (30, "bugfix", "medium", "sonnet", False, 4),
                (3, "docs", "medium", "sonnet", False, 2),
            ]
        )
    )
    assert p.predict(q(task="docs")).level == "all"  # 3 < MIN_GROUP
    assert p.predict(q(task="feature")).level == "all"  # never seen
    assert MIN_GROUP > 3


def test_effects_are_learned_and_shrunk_toward_the_assumption():
    p = BaselinePredictor().fit(
        history(
            [
                (100, "bugfix", "medium", "sonnet", False, 4),
                (100, "bugfix", "high", "sonnet", False, 8),
            ]
        )
    )
    ratio = p.predict(q(effort="high")).total.median / p.predict(q()).total.median
    # Data says 2x, the assumption 1.35x; with 100 turns vs 20 pseudo-turns, data dominates.
    assert 1.7 < ratio < 2.0


def test_a_few_turns_barely_move_the_assumption():
    p = BaselinePredictor().fit(
        history(
            [
                (100, "bugfix", "medium", "sonnet", False, 4),
                (2, "bugfix", "high", "sonnet", False, 40),
            ]
        )
    )
    ratio = p.predict(q(effort="high")).total.median / p.predict(q()).total.median
    assert ratio < 2.0  # 2 extreme turns (10x) can't override the 1.35x assumption


def test_unseen_models_use_the_assumed_multiplier_and_say_so():
    p = BaselinePredictor().fit(history([(50, "bugfix", "medium", "sonnet", False, 4)]))
    haiku = p.predict(q(model="haiku"))
    ratio = haiku.total.median / p.predict(q()).total.median
    expected = priors.MODEL_TOTAL["haiku"] / priors.MODEL_TOTAL["sonnet"]
    assert ratio == pytest.approx(expected, rel=0.01)
    assert haiku.adjustments == ["haiku x1.10 vs sonnet (assumed)"]


def test_first_turn_effect_survives_with_few_first_turns():
    p = BaselinePredictor().fit(
        history(
            [(60, "bugfix", "medium", "opus", False, 4), (2, "bugfix", "medium", "opus", True, 20)]
        )
    )
    first = p.predict(q(model="opus", first=True))
    later = p.predict(q(model="opus"))
    assert first.level == "task"  # still the bugfix group, not a tiny first-turn group
    assert first.total.median > 2 * later.total.median
    assert "first turn" in first.adjustments[0]


def test_effort_effect_recovered_from_synthetic_data(tmp_path):
    # Regression test: calls per turn are whole numbers, and a *median* of the residuals
    # found high effort = 1.04x where the generator uses 1.35x. The mean of logs works.
    from tokcast.storage import db

    generate(tmp_path / "logs", sessions=120, seed=11)
    con = db.connect(":memory:")
    pipeline.ingest(con, ClaudeCodeSource(), tmp_path / "logs")
    p = BaselinePredictor().fit(load_turns(con))
    ratio = p.predict(q(effort="high")).total.median / p.predict(q()).total.median
    assert 1.2 < ratio < 1.7
    con.close()


# -- forecast -----------------------------------------------------------------------------


def test_options_to_compare():
    assert options_to_compare("opus", "high") == [
        ("opus", "high"),
        ("opus", "medium"),
        ("sonnet", "high"),
        ("haiku", "medium"),
    ]
    assert options_to_compare("haiku", "low") == [
        ("haiku", "low"),
        ("sonnet", "low"),
        ("haiku", "medium"),
    ]


def test_context_modes():
    turns = history([(30, "bugfix", "medium", "opus", False, 4)])
    conv = CurrentConversation("s", pd.Timestamp("2026-10-14"), 250_000, "opus", "medium")
    new = forecast(turns, "fix it", model="opus", effort="medium", new_chat_tokens=50_000)
    assert (new.context.mode, new.context.tokens) == ("new chat", 50_000)
    cont = forecast(
        turns, "fix it", model="opus", effort="medium", context_mode="continue", conversation=conv
    )
    assert (cont.context.mode, cont.context.tokens) == ("continue", 250_000)
    given = forecast(
        turns, "fix it", model="opus", effort="medium", context_mode="given", context_tokens=7e4
    )
    assert given.context.tokens == 70_000
    assert cont.estimates[0].total.median > given.estimates[0].total.median


def test_new_chat_tip_only_when_cheaper():
    turns = history([(30, "bugfix", "medium", "opus", False, 4)])
    big = forecast(
        turns,
        "fix it",
        model="opus",
        effort="medium",
        context_mode="given",
        context_tokens=900_000,
        new_chat_tokens=40_000,
    )
    assert big.new_chat is not None
    assert big.new_chat.total.median < big.estimates[0].total.median
    small = forecast(
        turns,
        "fix it",
        model="opus",
        effort="medium",
        context_mode="given",
        context_tokens=40_000,
        new_chat_tokens=40_000,
    )
    assert small.new_chat is None  # a first turn costs more, so no tip


def test_similar_turns():
    turns = pd.DataFrame(
        {
            "text": ["fix the login bug in auth.py", "write docs for the api", None],
            "ts": pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-03"]),
            "model": "opus",
            "effort": "medium",
            "total_tokens": [300_000, 50_000, 10],
            "output_tokens": [900, 200, 1],
        }
    )
    [hit] = similar_turns(turns, "fix the signup bug in auth.py")
    assert (hit["text"], hit["total_tokens"]) == ("fix the login bug in auth.py", 300_000)
    assert similar_turns(turns, "something unrelated entirely") == []


# -- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_cli_without_history_uses_assumptions(home):
    result = runner.invoke(app, ["predict", "fix the login bug"], env={"COLUMNS": "120"})
    assert result.exit_code == 0, result.output
    assert "No history yet" in result.output
    assert "built-in assumption" in result.output


def test_cli_json_with_history(home, logs_dir):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    data = json.loads(runner.invoke(app, ["predict", "fix the bug", "--json"]).output)
    assert data["classification"]["task_type"] == "bugfix"
    assert data["context"]["mode"] == "new chat"
    assert len(data["estimates"]) == 4
    assert data["history_turns"] == 3
    first = data["estimates"][0]
    assert first["total"]["low"] <= first["total"]["median"] <= first["total"]["high"]

    one = json.loads(runner.invoke(app, ["predict", "x", "--no-compare", "--json"]).output)
    assert len(one["estimates"]) == 1


def test_cli_options(home, logs_dir):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    args = ["predict", "fix it", "--json", "--model", "claude-opus-5-5", "--effort", "HIGH"]
    data = json.loads(runner.invoke(app, [*args, "--context", "120k"]).output)
    assert (data["estimates"][0]["model"], data["estimates"][0]["effort"]) == ("opus", "high")
    assert data["context"] == {
        "mode": "given",
        "tokens": 120_000.0,
        "prompt_tokens": 1,
        "note": "from --context",
    }
    cont = json.loads(runner.invoke(app, ["predict", "go", "--json", "--continue"]).output)
    assert cont["context"]["mode"] == "continue"
    piped = runner.invoke(app, ["predict", "-", "--json"], input="explain the parser")
    assert json.loads(piped.output)["classification"]["task_type"] == "explain"


@pytest.mark.parametrize(
    "args",
    [
        ["--model", "gpt-9"],
        ["--effort", "ultra"],
        ["--context", "lots"],
        ["--context", "10k", "--continue"],
    ],
)
def test_cli_rejects_bad_options(home, args):
    result = runner.invoke(app, ["predict", "fix it", *args])
    assert result.exit_code == 1


def test_cli_continue_needs_history(home):
    assert runner.invoke(app, ["predict", "go", "--continue"]).exit_code == 1


def test_cli_with_no_text_history(home, logs_dir):
    # Prompts ingested with --no-text have no text: similar-prompt search must cope.
    runner.invoke(app, ["ingest", "--path", str(logs_dir), "--no-text"])
    result = runner.invoke(app, ["predict", "fix the login bug", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["similar"] == []
