# tokcast

> A forecast for your tokens: predict how much a Claude Code prompt will cost **before** you send it.

🚧 Work in progress. The full README (install, usage, accuracy results) arrives with v0.1.

Everything runs locally. No network calls, no telemetry.

## Development

```bash
uv sync
uv run tokcast --help
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
