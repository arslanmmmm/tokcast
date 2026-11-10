"""The `predict --json` contract (tokcast/predict/contract.py) can't drift unnoticed.

If this fails after an intended change: adding a field -> rerun with
TOKCAST_UPDATE_CONTRACT=1 to rewrite the contract file; removing, renaming or retyping a
field -> bump contract.SCHEMA_VERSION first (it's a new file name), then rewrite.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from tokcast import calibrate as cal
from tokcast.calibrate import plans
from tokcast.predict import contract, forecast

ROOT = Path(__file__).parent.parent
CONTRACT = Path(__file__).parent / "contracts" / f"forecast_v{contract.SCHEMA_VERSION}.json"
MOD_FIXTURE = ROOT / "integrations" / "claude-code" / "tests" / "fixtures" / "forecast.ts"


def calibrated(window, k):
    return cal.Calibration(
        window, points=[{}] * 3, k=k, k_low=k * 0.8, k_high=k * 1.2, turn_weight=0.12
    )


def samples(synthetic_turns):
    """Situations that between them set every optional field at least once."""
    fresh = forecast(pd.DataFrame(), "fix it", model="opus", effort="medium")
    rich = forecast(
        synthetic_turns,
        synthetic_turns.text.dropna().iloc[0],  # a past prompt: "similar" is filled
        model="opus",
        effort="high",
        context_mode="given",
        context_tokens=2_000_000,
        context_note="from --context",
        calibration=calibrated("5h", 7.0),
        weekly=calibrated("7d", 1.4),
        reading=cal.Reading(
            "5h", 23.0, datetime(2026, 11, 1, 14), datetime(2026, 11, 1, 12), "statusline"
        ),
    )
    assumed = forecast(
        pd.DataFrame(),
        "add a flag",
        model="sonnet",
        effort="medium",
        calibration=plans.with_plan_prior(cal.Calibration("5h"), "pro"),
        weekly=plans.with_plan_prior(cal.Calibration("7d"), "pro"),
    )
    return [contract.to_json(f) for f in (fresh, rich, assumed)]


def test_samples_set_every_optional_field(synthetic_turns):
    shape = contract.merge(*(contract.fields(s) for s in samples(synthetic_turns)))

    for path in (
        "new_chat",
        "limit_now",
        "estimates[].limit_pct",
        "weekly_pct",
        "limit_assumed_plan",
        "similar",
    ):
        assert shape[path] != ["null"], f"no sample sets {path}"
    assert "similar[]" in shape  # at least one similar past prompt


def test_output_matches_the_committed_contract(synthetic_turns):
    shape = contract.merge(*(contract.fields(s) for s in samples(synthetic_turns)))
    current = {"schema_version": contract.SCHEMA_VERSION, "fields": shape}
    if os.environ.get("TOKCAST_UPDATE_CONTRACT"):
        CONTRACT.parent.mkdir(exist_ok=True)
        lines = ",\n".join(f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in shape.items())
        version = contract.SCHEMA_VERSION
        text = f'{{\n  "schema_version": {version},\n  "fields": {{\n{lines}\n  }}\n}}\n'
        CONTRACT.write_text(text, encoding="utf-8")

    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert current == committed, __doc__


def test_every_output_says_its_version(synthetic_turns):
    assert all(s["schema_version"] == contract.SCHEMA_VERSION for s in samples(synthetic_turns))


def test_the_mod_fixture_follows_the_contract():
    """Cross-language check, run in Python CI: the mod's tests use this fixture, so a
    mod that reads a field tokcast no longer writes fails here."""
    text = MOD_FIXTURE.read_text(encoding="utf-8")
    literal = re.search(r"FORECAST_V1 = (\{.*\})\s*$", text, re.DOTALL)
    assert literal, "forecast.ts must export FORECAST_V1 as a JSON object literal"
    fixture = json.loads(literal.group(1))
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))["fields"]

    assert fixture["schema_version"] == contract.SCHEMA_VERSION
    for path, kinds in contract.fields(fixture).items():
        assert path in committed, f"the mod fixture has {path}, which tokcast doesn't write"
        assert kinds <= set(committed[path]), f"{path}: {kinds} not in {committed[path]}"
