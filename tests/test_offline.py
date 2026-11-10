"""tokcast never uses the network. conftest.py blocks sockets in every test; these
check the parts that blocking can't see."""

import ast
from pathlib import Path

import tokcast
from tokcast.storage import db

SRC = Path(tokcast.__file__).parent
NETWORK_MODULES = {"socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp", "ftplib"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_no_module_imports_networking_code():
    offenders = {
        str(path.relative_to(SRC)): sorted(imported_modules(path) & NETWORK_MODULES)
        for path in SRC.rglob("*.py")
        if imported_modules(path) & NETWORK_MODULES
    }
    assert offenders == {}


def test_duckdb_never_downloads_extensions():
    # DuckDB fetches missing extensions from the internet on demand unless told not to.
    con = db.connect(":memory:")
    settings = dict(
        con.execute(
            "SELECT name, value FROM duckdb_settings() WHERE name IN "
            "('autoinstall_known_extensions', 'autoload_known_extensions')"
        ).fetchall()
    )
    con.close()
    assert settings == {
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
    }
