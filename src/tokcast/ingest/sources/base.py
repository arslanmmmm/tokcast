"""The interface every log source implements.

A ``Protocol`` describes the *shape* a class must have (structural typing), without
forcing it to inherit from a base class. Any object with these attributes and methods
counts as a ``LogSource``.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from tokcast.ingest.records import ParsedFile


class LogSource(Protocol):
    name: str

    def discover(self, root: Path) -> Iterable[Path]:
        """Yield every log file under ``root`` this source knows how to read."""
        ...

    def parse_file(self, path: Path, *, store_text: bool = True) -> ParsedFile:
        """Parse one file. Must never raise on bad content; report it in ``errors``."""
        ...
