"""Parse what people type on the command line. Pure functions: errors are ValueErrors with
a message that says what was expected, which the CLI prints."""

import re
from datetime import timedelta

_TOKENS = re.compile(r"\s*([\d.]+)\s*([km]?)\s*")
_DURATION = re.compile(r"\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*")
_SCALE = {"": 1, "k": 1e3, "m": 1e6}


def tokens(text: str) -> float:
    """'120k' -> 120000, '1.5M' -> 1500000, '50000' -> 50000."""
    match = _TOKENS.fullmatch(text.lower())
    if not match:
        raise ValueError(f"Can't read token count: {text} (try 120k or 1.5M)")
    try:
        number = float(match.group(1))
    except ValueError:  # e.g. "1.2.3"
        raise ValueError(f"Can't read token count: {text} (try 120k or 1.5M)") from None
    return number * _SCALE[match.group(2)]


def duration(text: str) -> timedelta:
    """'2h10m' -> 2 hours 10 minutes. Days, hours and minutes, in that order."""
    match = _DURATION.fullmatch(text.lower())
    if not match or not any(match.groups()):
        raise ValueError(f"Can't read duration: {text} (try 2h10m or 3d4h)")
    days, hours, minutes = (int(g or 0) for g in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)
