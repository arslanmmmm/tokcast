"""Built-in assumptions, used only where the user's own history has no answer.

They describe a "typical" Claude Code turn and were set by hand from the author's own
logs (one model, one effort level) plus common sense about effort and model size. They
are the same assumptions the synthetic generator uses, so judging them on synthetic data
would be circular: only real data can say how good they are. Every prediction that
relies on them labels the number "assumed".
"""

# Median API calls in a turn that isn't the first of a session. A turn re-reads its
# context about once per call, so this is also the median "re-reads" of the context.
CALLS = {
    "bugfix": 4.0,
    "feature": 8.0,
    "refactor": 6.0,
    "tests": 5.0,
    "explain": 1.5,
    "docs": 2.0,
    "shell": 1.2,
    "followup": 2.0,
    "other": 1.5,
}
FIRST_TURN = 2.5  # first turns explore the project first (author's data: ~18 calls)
OUTPUT_PER_CALL = 450  # median output tokens per API call
SPREAD_TOTAL = 0.9  # lognormal sigma: turns of the same kind vary a lot
SPREAD_OUTPUT = 1.0
NEW_CHAT_CONTEXT = 40_000  # system prompt + tools before the first message

# Relative to sonnet at medium effort. "total" scales tokens processed (mostly more
# calls); "output" scales tokens written (more calls *and* more thinking per call).
EFFORT_TOTAL = {"low": 0.6, "medium": 1.0, "high": 1.35, "xhigh": 1.6, "max": 1.9}
EFFORT_OUTPUT = {"low": 0.45, "medium": 1.0, "high": 1.7, "xhigh": 2.2, "max": 3.0}
MODEL_TOTAL = {"opus": 0.9, "sonnet": 1.0, "haiku": 1.1, "fable": 0.9}
MODEL_OUTPUT = {"opus": 1.0, "sonnet": 1.0, "haiku": 0.9, "fable": 1.0}

MODELS = tuple(MODEL_TOTAL)
EFFORTS = tuple(EFFORT_TOTAL)


def rereads(task_type: str, first_turn: bool) -> float:
    """Median re-reads of the context for a turn (sonnet, medium effort)."""
    return CALLS.get(task_type, CALLS["other"]) * (FIRST_TURN if first_turn else 1.0)


def output_tokens(task_type: str, first_turn: bool) -> float:
    """Median output tokens for a turn (sonnet, medium effort)."""
    return rereads(task_type, first_turn) * OUTPUT_PER_CALL
