"""Find past prompts that look like a new one (word overlap), to show what they cost."""

import re

import pandas as pd

_WORD = re.compile(r"[a-z][a-z0-9_]+")
# Common words that say nothing about the task.
_STOP_WORDS = (
    "the a an to of in on for and or with is are be it this that my me i you can please "
    "do does what how why use using into from at by as"
)
_STOP = frozenset(_STOP_WORDS.split())


def _words(text: object) -> frozenset[str]:
    # Missing text arrives from pandas as NaN, a float that is truthy: check the type.
    if not isinstance(text, str):
        return frozenset()
    return frozenset(_WORD.findall(text.lower())) - _STOP


def similar_turns(
    turns: pd.DataFrame, prompt: str, *, k: int = 3, min_score: float = 0.25
) -> list[dict]:
    """Up to ``k`` past turns whose words overlap most with ``prompt`` (Jaccard index:
    shared words / all words). Simple and explainable; good enough to jog memory."""
    query = _words(prompt)
    if not query or turns.empty:
        return []
    scored = []
    for row in turns.itertuples(index=False):
        words = _words(row.text)
        if words:
            score = len(query & words) / len(query | words)
            if score >= min_score:
                scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].ts.timestamp()))
    return [
        {
            "text": " ".join(row.text.split())[:80],
            "score": round(score, 2),
            "ts": row.ts,
            "model": row.model,
            "effort": row.effort,
            "total_tokens": int(row.total_tokens),
            "output_tokens": int(row.output_tokens),
        }
        for score, row in scored[:k]
    ]
