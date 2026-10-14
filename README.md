# tokcast

> A forecast for your tokens: predict how much a Claude Code prompt will cost **before** you send it.

🚧 Work in progress. The full README (install, usage, accuracy results) arrives with v0.1.

Everything runs locally. No network calls, no telemetry.

## Related projects

tokcast builds on excellent existing tools: [ccusage](https://github.com/ccusage/ccusage)
for reports of past usage, [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)
for live monitoring and burn rate, and [claumon](https://github.com/fabioconcina/claumon)
for a dashboard with calibrated forecasts of your usage window.

Those tools tell you what you've spent, or where your current 5-hour or weekly window is
heading. tokcast answers a different question: **what will this one prompt cost, before
you send it?** It predicts a range for the whole turn (every tool call the prompt sets
off) from your own history, compares models and effort levels side by side, and
publishes how often its ranges are right via `tokcast eval`.

A detailed comparison, including what users of these tools ask for, is in
[docs/related-work.md](docs/related-work.md).

## Development

```bash
uv sync
uv run tokcast --help
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

### Try it without your own logs

`tokcast synth` writes realistic **synthetic** Claude Code logs (clearly marked, never
mixed into your real database), so you can try every command right away:

```bash
uv run tokcast synth --out tokcast-demo
TOKCAST_HOME=tokcast-demo/db uv run tokcast ingest --path tokcast-demo/logs
```
