"""tokcast.models is the one list of model families and efforts; its copies must match."""

import re
from pathlib import Path

from tokcast import models
from tokcast.calibrate import plans
from tokcast.predict import priors

ARGS_TS = Path(__file__).parent.parent / "integrations" / "claude-code" / "hooks" / "args.ts"


def test_family_names():
    assert models.family("claude-opus-5-5") == "opus"
    assert models.family("Sonnet") == "sonnet"
    assert models.family("gpt-9") is None


def test_every_family_and_effort_has_priors():
    for table in (priors.MODEL_TOTAL, priors.MODEL_OUTPUT):
        assert tuple(table) == models.FAMILIES
    for table in (priors.EFFORT_TOTAL, priors.EFFORT_OUTPUT):
        assert tuple(table) == models.EFFORTS


def test_the_sql_views_use_the_same_families(con):
    families = con.execute(
        "SELECT regexp_extract(m, '({})', 1) FROM (VALUES {}) t(m)".format(
            models.FAMILY_PATTERN, ", ".join(f"('claude-{f}-1')" for f in models.FAMILIES)
        )
    ).fetchall()
    sql = Path(__file__).parent.parent / "src" / "tokcast" / "storage" / "sql" / "views.sql"
    assert "{model_families}" in sql.read_text()  # filled in from models.py, not a copy
    assert [f for (f,) in families] == list(models.FAMILIES)


def test_the_mods_copies_match():
    """The mod (TypeScript) can't import Python, so its lists are checked here."""
    text = ARGS_TS.read_text(encoding="utf-8")
    family = re.search(r"const MODEL_FAMILY = /(.+)/", text)[1]
    efforts = re.findall(r"'(\w+)'", re.search(r"const EFFORTS = new Set\(\[(.*?)\]\)", text)[1])
    plan_names = re.findall(r"'(\w+)'", re.search(r"const PLANS = new Set\(\[(.*?)\]\)", text)[1])

    assert family.split("|") == list(models.FAMILIES)
    assert efforts == list(models.EFFORTS)
    assert plan_names == list(plans.PLAN_MULTIPLE)
