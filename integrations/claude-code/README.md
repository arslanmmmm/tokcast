# tokcast-buddy: a Claude Code mod

A small character in the band above Claude Code's prompt box (terminal and desktop app).
Type a prompt, click **How much will this cost?**, and it shows what `tokcast predict`
estimates before you send it:

```
(•o•) [ How much will this cost? ] [ × ]
  ~552k tokens (183k–2.5M) for a bugfix turn
  % of 5h limit: not calibrated yet (0/3 status-line readings)
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
- `hooks/args.ts` passes what the session knows, so follow-ups aren't priced as new chats:

  | flag | from | when unknown |
  |---|---|---|
  | `--context` | `$.session.usage()`: the live context window | fresh session: tokcast's "new chat" |
  | `--model` | `$.session.model()`, reduced to opus/sonnet/haiku/fable | tokcast's default |
  | `--effort` | the last main-loop `turn.step` (the only event that carries it) | before the first turn: tokcast's default |

  When a new chat would be clearly cheaper, the bubble adds a tip with that estimate.

## Try it

1. Put `tokcast` on your PATH: `uv tool install --editable .` from the repo root.
2. Load the mod for one session: `claude --plugin-dir integrations/claude-code`.

The mod has two options (`/config`, or `pluginConfigs` in settings):

| option | default | use |
|---|---|---|
| `command` | `tokcast` | how to run tokcast, e.g. `uv run --project /path/to/tokcast tokcast` |
| `tokcastHome` | empty | a separate database, e.g. the synthetic demo's `tokcast-demo/db` |

## Develop

```bash
claude plugin validate integrations/claude-code
claude plugin test integrations/claude-code     # 18 tests, terminal and desktop surfaces
npx -p typescript tsc -p integrations/claude-code
```

`tsc` needs the API types that Claude Code writes into `.claude-plugin/types/` the first
time it loads the mod (gitignored). The tests use the engine's test kit: the prompt box, the
session and `$.process.run` are stubbed, so they never start tokcast.
