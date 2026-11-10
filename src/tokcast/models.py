"""The model families and effort levels tokcast knows: the one list.

Python imports it, views.sql gets the family pattern filled in when the views are
created (storage/db.py), and tests check that the priors and the Claude Code mod's
copies (integrations/claude-code/hooks/args.ts) match it. Adding a family: add it here,
give it priors in predict/priors.py, and update args.ts; the tests point at what's left.
"""

import re

FAMILIES = ("opus", "sonnet", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")

FAMILY_PATTERN = "|".join(FAMILIES)  # used in SQL and in regular expressions
_FAMILY = re.compile(FAMILY_PATTERN)


def family(model: str) -> str | None:
    """'claude-opus-5-5', 'Opus' or 'opus' -> 'opus'; None for an unknown model."""
    match = _FAMILY.search(model.lower())
    return match.group(0) if match else None
