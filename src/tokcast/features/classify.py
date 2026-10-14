"""Classify a prompt into a task type with simple, explainable keyword rules.

Each rule is a list of keywords. The rule with the most *distinct* matching words wins;
ties go to the rule listed first. So "fix the failing tests" is a bugfix (2 bug words vs
1 test word) and "add unit tests for the error handler" is tests. Every result records
which words matched, so a prediction can show *why* a prompt landed in a group.
Deliberately no ML here: a wrong class is easy to spot and fix by editing a rule.
"""

import re
from dataclasses import dataclass

TASK_TYPES = (
    "shell",
    "bugfix",
    "tests",
    "refactor",
    "docs",
    "explain",
    "feature",
    "followup",
    "other",
)


@dataclass(frozen=True)
class Classification:
    task_type: str
    matched: tuple[str, ...]  # the words that triggered the rule


def _rule(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(rf"\b(?:{p})\b" for p in patterns), re.IGNORECASE)


# (task type, pattern), in tie-break order.
RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "bugfix",
        _rule(
            r"fix(?:es|ed|ing)?",
            r"bugs?",
            r"errors?",
            r"exceptions?",
            r"traceback",
            r"crash(?:es|ed|ing)?",
            r"broken",
            r"fail(?:s|ed|ing|ure)?",
            r"debug(?:ging)?",
            r"not working",
            r"doesn'?t work",
            r"\w+Error",
        ),
    ),
    (
        "tests",
        _rule(r"unit", r"tests?", r"pytest", r"coverage", r"test cases?", r"specs?"),
    ),
    (
        "refactor",
        _rule(
            r"refactor(?:ing)?",
            r"clean ?up",
            r"rename",
            r"simplif(?:y|ied)",
            r"extract",
            r"reorgani[sz]e",
            r"restructure",
            r"split",
            r"dedupe|deduplicate",
        ),
    ),
    (
        "docs",
        _rule(r"readme", r"docs?", r"documentation", r"document", r"docstrings?", r"changelog"),
    ),
    (
        "explain",  # explanations and questions
        _rule(
            r"explain",
            r"what(?:'?s| is| are| does| do| should| means?)",
            r"why",
            r"how (?:to|does|do|is|are|can)",
            r"where (?:is|are|do|can)",
            r"i (?:don'?t|do not|didn'?t|did not) (?:know|understand|get|see)",
            r"walk me through",
        ),
    ),
    (
        "feature",
        _rule(
            r"add",
            r"implement",
            r"build",
            r"create",
            r"support",
            r"endpoint",
            r"integrate",
            r"make",
            r"write",
        ),
    ),
    # Short follow-ups that tell Claude to carry on ("go", "continue", "yes do it").
    # They can be cheap (a thank-you) or very expensive (continue a whole milestone),
    # which is exactly what the user's own history decides.
    (
        "followup",
        _rule(
            r"go",
            r"continue",
            r"yes",
            r"ok(?:ay)?",
            r"next",
            r"proceed",
            r"do it",
            r"thanks?",
            r"thank you",
            r"looks good",
            r"commit",
            r"push",
        ),
    ),
]


def classify(text: str | None, kind: str = "text") -> Classification:
    """Return the task type of a prompt. ``kind`` comes from the parser."""
    if kind == "bash-input":
        return Classification("shell", ("<bash-input>",))
    if not text or not text.strip():
        return Classification("other", ())
    best = Classification("other", ())
    for task_type, pattern in RULES:
        matches = tuple(dict.fromkeys(m.group(0).lower() for m in pattern.finditer(text)))
        if len(matches) > len(best.matched):  # strictly more: earlier rules win ties
            best = Classification(task_type, matches)
    return best
