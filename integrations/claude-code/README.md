# tokcast-buddy: a Claude Code mod

A small character in the band above Claude Code's prompt box (terminal and desktop app).
Type a prompt, click **How much will this cost?**, and it shows what `tokcast predict`
estimates before you send it:

```
(•o•) [ How much will this cost? ] [ × ]
  ~552k tokens (183k–2.5M) for a bugfix turn
  5h limit: 24% used now → this turn ≈ +3% (1%–9%)
  weekly limit: 41% used now → this turn: learning your limit (1/3 readings)
  basis: 518 of your bugfix turns · new chat: median of your 200 first turns
```

(Synthetic demo data.) Like the CLI, the bubble always states its basis.

## How it works

- `hooks/register.tsx` draws the band (`ui.render` on `AbovePrompt`). A click reads the
  draft with `$.prompt.read()` and runs `tokcast predict - --json --no-compare` with the
  draft on stdin. Everything stays on your machine: one local process, no network.
- `hooks/bubble.ts` turns the JSON into the bubble's lines. It's pure, so it's easy to test.
- The prediction runs only on a click, not on every keystroke: each run starts Python and
  DuckDB (about a second).
- Sending a prompt clears the bubble, because the estimate was for that draft.
- **It shares the band with Claude Code.** Claude Code draws its own boxes there (a
  survey, a question) and tells hooks with `hasSurvey`. The mod keeps that drawing whole
  and first, and draws the character under it. (The first version stepped aside, and the
  character seemed to vanish after every turn that ended with such a box.)
- **You choose how much of it shows:** the **hide** button shrinks it to its face, and
  clicking the face opens it again. The choice is kept across sessions (`$.store`).
- `hooks/args.ts` passes what the session knows, so follow-ups aren't priced as new chats:

  | flag | from | when unknown |
  |---|---|---|
  | `--context` | `$.session.usage()`: the live context window | fresh session: tokcast's "new chat" |
  | `--model` | `$.session.model()`, reduced to opus/sonnet/haiku/fable | tokcast's default |
  | `--effort` | the last main-loop `turn.step` (the only event that carries it) | before the first turn: tokcast's default |

  When a new chat would be clearly cheaper, the bubble adds a tip with that estimate.
- **Usage limits.** "% used now" comes straight from Claude Code (`rateLimits`: the 5-hour
  and 7-day windows; there is no daily limit). What *this turn* would add needs tokcast's
  calibration (tokens → % of limit), learned from readings. The mod collects them itself:
  after every turn it passes the live windows to `tokcast statusline` (the same code the
  status line uses), then runs `tokcast ingest` so the turn's tokens are in the database.
  After 3 usable readings per window the "+x%" appears. A reading is usable once it's at
  least 2% and its logs are ingested.
- tokcast calls run one at a time (DuckDB allows one writer), and the after-turn work runs
  on a timer so it never delays the turn.

## Install

1. Put `tokcast` on your PATH: `uv tool install --editable .` from the repo root.
2. Install the mod once, in a terminal (Claude Code 2.1.275 or later):

   ```
   /plugin install tokcast-buddy --marketplace arslanmmmm/tokcast
   ```

   Answer `y` to add the marketplace, then pick the user scope. It then loads in every
   session, the desktop app's included.

   **From your own clone** (edits apply after `/reload-plugins`, no reinstall):

   ```bash
   claude plugin marketplace add /path/to/tokcast
   claude plugin install tokcast-buddy@tokcast
   ```

For one session only, while developing: `claude --plugin-dir integrations/claude-code`.
(A session's hot-reload mods folder is tied to that session; when the app restarts the
conversation as a new session, a mod loaded that way is gone. Installing avoids that.)

The mod has three options (`/config`, or `pluginConfigs` in settings):

| option | default | use |
|---|---|---|
| `command` | `tokcast` | how to run tokcast, e.g. `uv run --project /path/to/tokcast tokcast` |
| `tokcastHome` | empty | a separate database, e.g. the synthetic demo's `tokcast-demo/db` (never auto-ingested) |
| `autoIngest` | on | after each turn, save the usage reading and run `tokcast ingest` |

## Develop

```bash
claude plugin validate integrations/claude-code
claude plugin test integrations/claude-code     # 32 tests, terminal and desktop surfaces
npx -p typescript tsc -p integrations/claude-code
```

`tsc` needs the API types that Claude Code writes into `.claude-plugin/types/` the first
time it loads the mod (gitignored). The tests use the engine's test kit: the prompt box, the
session and `$.process.run` are stubbed, so they never start tokcast.
