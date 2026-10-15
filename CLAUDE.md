# tokcast

A local-only CLI that predicts Claude Code token usage for a prompt before it is sent,
learned from the user's own session logs. A portfolio project for a Junior Data Engineer
role: code quality, tests and clear docs matter as much as features.

Progress, every key decision and its reason, and next steps are in
[docs/plan.md](docs/plan.md). Read it before changing behaviour.

## Commands

```bash
uv sync                                   # Python 3.12 + dev tools + the ml extra
uv run pytest                             # ~133 tests, ~30 s
uv run ruff check . && uv run ruff format --check .
uv run tokcast synth --out tokcast-demo   # synthetic data for trying things
TOKCAST_HOME=tokcast-demo/db uv run tokcast ingest --path tokcast-demo/logs
```

Run commands from the repo root: `uv run` outside it silently uses Anaconda's Python.

## Conventions

- **Privacy first:**
  - no network calls (a test enforces it)
  - never commit real logs or databases
  - README and docs examples use synthetic data only
  - never edit the user's `~/.claude/settings.json`; print snippets instead
- **Synthetic data never goes into the real database.** Use `TOKCAST_HOME` for a separate
  one.
- **SQL lives in `src/tokcast/storage/sql/**/*.sql`**, loaded with `db.load_sql`. Cast sums
  to `BIGINT` and decimal arithmetic to `DOUBLE`.
- **Ingest is append-only:** upsert by id, never delete rows; token counts only grow.
- **`cli.py` stays thin**, and heavy imports (pandas, duckdb, pyarrow) go inside commands.
  `capture.py` (the status line) is standard library only.
- **Escape user text** (prompts, project names) with `rich.markup.escape` before printing.
- **Every estimate states its basis.** Assumptions are labelled "assumed".
- **Model changes are adopted only if `tokcast eval` shows a gain** beyond the paired 95%
  interval, with the decision rule written down first. Never tune on the real test turns.
- **Tests:** handwritten fixture logs in `tests/fixtures/`, ground-truth checks on synthetic
  data, and for each bug fixed, a test confirmed to fail without the fix.

## Working with the user

- The user is a student learning from this project. Explain decisions in plain words and
  name the concepts (they will discuss them in interviews).
- Work in small milestones. After each: run the tests, show a demo command, explain what
  was built, commit, and wait for "go".
- Commits: small, conventional (`feat(...)`, `fix(...)`, `docs:`), with a body explaining
  why. Push to `origin main`; CI must stay green.
