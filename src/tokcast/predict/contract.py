"""The `predict --json` data contract: what other programs (the Claude Code mod, a future
browser extension) may rely on.

The output carries ``schema_version``. Its shape (every field path with its JSON types)
is committed in tests/contracts/ and checked by a test, so a change can't slip through:

- **adding** a field: update the contract file; same version (readers ignore unknown
  fields);
- **removing, renaming or changing the type** of a field: bump SCHEMA_VERSION, because
  existing readers would misread the output.
"""

import json
from dataclasses import asdict
from typing import Any

from tokcast.predict.forecast import Forecast

SCHEMA_VERSION = 1

_JSON_TYPES = {str: "string", bool: "boolean", int: "number", float: "number", type(None): "null"}


def to_json(forecast: Forecast) -> dict[str, Any]:
    """The forecast as plain JSON values, versioned. Times become ISO strings."""
    body = json.loads(json.dumps(asdict(forecast), default=str))
    return {"schema_version": SCHEMA_VERSION, **body}


def fields(value: Any, path: str = "") -> dict[str, set[str]]:
    """Every field path in a JSON value with its types, e.g. {"estimates[].n": {"number"}}.

    List items share one path (``[]``); an empty list contributes no item paths.
    """
    found: dict[str, set[str]] = {}

    def add(key: str, kind: str) -> None:
        found.setdefault(key, set()).add(kind)

    def walk(node: Any, key: str) -> None:
        if isinstance(node, dict):
            add(key or "$", "object")
            for name, child in node.items():
                walk(child, f"{key}.{name}" if key else name)
        elif isinstance(node, list):
            add(key, "array")
            for item in node:
                walk(item, f"{key}[]")
        else:
            add(key, _JSON_TYPES[type(node)])

    walk(value, path)
    return found


def merge(*shapes: dict[str, set[str]]) -> dict[str, list[str]]:
    """Union of several samples' fields: a field null in one and a number in another is
    "number|null". Sorted, so the committed file diffs cleanly."""
    merged: dict[str, set[str]] = {}
    for shape in shapes:
        for key, kinds in shape.items():
            merged.setdefault(key, set()).update(kinds)
    return {key: sorted(kinds) for key, kinds in sorted(merged.items())}
