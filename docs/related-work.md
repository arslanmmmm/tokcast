# Related work

How tokcast relates to existing Claude Code usage tools, what they do well, and what
their users ask for. Researched on 2026-10-14 from each project's README, issue
tracker and (where needed) source. Star counts are from that date.

**Short version:** existing tools look *backward* (what did I spend?) or forecast at the
*window* level (where will my 5-hour or weekly usage land?). tokcast forecasts a
*single prompt* before you send it, as a range covering the whole agentic turn (every
tool call that follows), learned from your own logs, with backtested accuracy.

## Comparison

| Project | Per-prompt prediction | Model / effort comparison | Published accuracy | Local-only | Log parsing | Live monitor |
|---|---|---|---|---|---|---|
| [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) (8.7k★) | ❌ window-level burn rate and depletion time | ❌ | ❌ | ✅ by default (official limits via opt-in API flag or status-line capture) | ✅ | ✅ terminal UI |
| [ccusage](https://github.com/ccusage/ccusage) (19k★) | ❌ linear projection for the active 5-hour block | Past usage per model, not predictive | ➖ (reports, no forecasting model) | ⚠️ logs stay local; pricing is fetched online unless `--offline` | ✅ Claude Code + ~18 other tools | Status line (beta) |
| [claumon](https://github.com/fabioconcina/claumon) (16★) | ❌ window-level: utilization at reset with 80% interval | Per-model quota gauges (measured) | ✅ model spec published, `claumon bench` (pinball/CRPS, coverage, bias) | ❌ polls Anthropic's OAuth usage API by design | ✅ | ✅ browser dashboard + VS Code |
| [ctok](https://github.com/ctok-cli/ctok) (2★) | ⚠️ single request, fixed heuristics, no history | ✅ recommends model + effort | Claimed (±20% for 85%+ of prompts), no reproducible eval | ✅ | ❌ | ❌ |
| **tokcast** | ✅ whole turn, range, from your own history | ✅ side-by-side ranges | ✅ planned: `tokcast eval` backtest | ✅ enforced by a test | ✅ | ❌ by design (v2: browser extension) |

Forks: [contiamo/cc-usage-monitor](https://github.com/contiamo/cc-usage-monitor) and
[0xKirin/claude-code-usage-monitor](https://github.com/0xKirin/claude-code-usage-monitor)
are forks of Claude-Code-Usage-Monitor from July 2025. The first adds only tooling
(a Taskfile, running via uv); the second has no changes of its own. Neither has been
updated since, so they share the upstream's v3-era features.

## Project notes

### Claude-Code-Usage-Monitor (Maciek-roboblog)

**What it does:** a real-time terminal monitor for Claude Code usage, now a broader
"usage ops" companion (v4) with JSON output, state files and an opt-in local history
warehouse.

**How it forecasts:**
- *P90 limit detection:* the default "custom" plan estimates your token limit as the
  90th percentile of your past session totals (last 8 days).
- *Burn rate:* tokens per minute over the last hour, extrapolated to predict when the
  current 5-hour session runs out.

Both are session-level pace, not per-prompt. The README labels this "machine learning"
and mentions a 95% confidence threshold, but publishes no evaluation. Its plan limits
also show how uncertain this area is: the README gives two different numbers for the
Pro plan (~44,000 and ~19,000 tokens).

**What users report (134 issues, 26 open):**
- Numbers that don't match the official usage screen ([#48](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/48), [#77](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/77), [#119](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/119)).
- Session reset time and timezone logic ([#52](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/52), [#220](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/220), [#243](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/243)).
- Terminal display problems: blank screen on macOS, unreadable light mode ([#75](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/75), [#55](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/55)).
- New model IDs priced wrongly: Claude 5 models charged at old rates ([#241](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/241)).
- **Log files are rewritten on resume/compact, so history silently drifts** ([#226](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/226)); subagent fields missing ([#229](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/229)); resumed sessions double-costed ([#158](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/158)).
- Requests: Homebrew install ([#31](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/31)), weekly limits ([#234](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/234)), date filters ([#223](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/223)).

**Worth learning from:**
- **Provenance labels** on every number (`official`, `local_estimate`, `experimental`, `unknown`). tokcast should label predictions the same way.
- A **machine-readable mode** (`--once --output json`) with automation exit codes, so other tools consume it without scraping the terminal UI. That's exactly what tokcast's v2 extension needs.
- A **persistent local history** that outlives Claude Code's 30-day log cleanup.

### ccusage

**What it does:** the de-facto CLI for reporting past token usage and cost from local
logs, by day, week, month, session or 5-hour block, across Claude Code and about 18
other AI coding tools.

**How it forecasts:** only in the `blocks` report. For the active 5-hour block it shows
a burn rate (tokens/min) and a straight-line "Projected" total. Nothing per prompt.

**What users report (500 issues, nearly all closed):**
- Live block limits and gauges not matching reality ([#483](https://github.com/ccusage/ccusage/issues/483), [#145](https://github.com/ccusage/ccusage/issues/145), [#288](https://github.com/ccusage/ccusage/issues/288), [#331](https://github.com/ccusage/ccusage/issues/331)).
- Counting accuracy, the hardest recurring problem:
  - one response counted 2–3× when `requestId` is missing ([#1837](https://github.com/ccusage/ccusage/issues/1837))
  - branched conversations counted twice ([#19](https://github.com/ccusage/ccusage/issues/19))
  - subagent tokens missed ([#313](https://github.com/ccusage/ccusage/issues/313))
  - logged usage values incomplete in some Claude Code versions ([#705](https://github.com/ccusage/ccusage/issues/705), [#866](https://github.com/ccusage/ccusage/issues/866))
- CPU and memory use of live and status-line modes ([#459](https://github.com/ccusage/ccusage/issues/459), [#262](https://github.com/ccusage/ccusage/issues/262), [#455](https://github.com/ccusage/ccusage/issues/455)).
- Broken releases ([#536](https://github.com/ccusage/ccusage/issues/536), [#861](https://github.com/ccusage/ccusage/issues/861)), plus a steady stream of "support tool X" requests.

**Worth learning from:**
- A **one-line quick start** (`npx ccusage@latest`). tokcast's equivalent is `uvx tokcast`.
- `--json` on every report.
- **Automatic compact tables in narrow terminals.** tokcast hit exactly that problem in Milestone 1.
- **One subcommand per source**, the same idea as tokcast's `LogSource` interface.
- `--offline` as an explicit privacy switch.

### claumon

**What it does:** a single-binary local dashboard for Claude Code. It shows live
rate-limit gauges from Anthropic's OAuth usage API, session costs, history, and a
browser for memory files.

**How it forecasts:**
- projected utilization at the window reset, with an **80% credible interval** and the
  time until a threshold is reached
- an empirical-Bayes model refit daily on your own past windows
- the model is published (MODEL.pdf) and benchmarked out-of-sample via `claumon bench`
  using proper scoring rules (CRPS/pinball loss, coverage, bias)

This is the most rigorous forecasting in this group, but it's window-level, not per prompt.

**What users report:** no issues filed yet (young project).

**Worth learning from:**
- **Publishing the model and a benchmark command.** tokcast's `eval` should report the same kind of metrics (pinball loss, interval coverage, bias), so results can be compared.
- A respectful **"How it compares"** section in the README.
- Measured limits beat estimated ones. tokcast can get official usage locally from Claude Code's status-line data instead of calling an API (see plan changes).

### ctok

**What it does:** a toolkit that runs before you send. It estimates a prompt's tokens,
cost and share of the 5-hour quota, recommends a model and effort level, and trims
the prompt.

**How it predicts** (from its estimation docs):
- input tokens: fixed characters-per-token ratios by content type (prose, code, JSON, …)
  plus about 350 tokens of overhead
- output tokens: input × a fixed ratio per task type (e.g. feature 1.4×, bug fix 0.8×),
  capped at 8,000

It doesn't read logs or learn from history, and it doesn't model the tool loop, cache
reads or current context size. On real Claude Code turns those dominate: in the
author's own logs, one prompt led to 55 API calls and 11.2M tokens processed.

**Worth learning from:** the content-type ratios are a cheap improvement for estimating
the prompt's own size, and the model + effort recommendation is a good UX precedent for
tokcast's v3 suggestions.

### Other small projects

[token-jar](https://github.com/lio-cs/token-jar) (reports past usage; pre-send *input*
count via the `count_tokens` API or chars/4),
[qrion](https://github.com/bhalla1993/qrion) (local heuristics for a query's risk and
scope; says it isn't trying to predict an agent exactly), and
[claude-cost-optimizer](https://github.com/Merkuryo/claude-cost-optimizer) (input-only
cost across model tiers with tiktoken). None of them predict the full agentic turn.

## Claude Code feature request #32436

[anthropics/claude-code#32436](https://github.com/anthropics/claude-code/issues/32436),
"Show estimated token count before sending prompt" (March 2026), asked Claude Code to
call the token-counting API (`/v1/messages/count_tokens`) and show the **input** token
count while you type. It was closed as "not planned" by an automated inactivity bot after
about a month, with no maintainer comment. So it's an unmet request, not a rejected
design.

Even if built, that feature would count input only. It wouldn't predict output, the
number of tool calls, or cache reads, which make up most of a turn's cost. tokcast
covers that part, offline and without an API key.

## Lessons applied to tokcast

These are confirmed by both the issue trackers and tokcast's own Milestone 1 findings:

1. **Deduplicate by request ID globally**, with `message.id` as fallback (ccusage #1837, #19). Already done.
2. **Never trust "re-read the file" to preserve history.** Claude Code rewrites logs on resume and compact (Monitor #226), and deletes them after 30 days by default.
3. **Subagent transcripts live in nested folders** and belong to the turn that launched them (ccusage #313, Monitor #229).
4. **Logged usage can be incomplete in some Claude Code versions** (ccusage #866). On tokcast's test data (v2.1.295), output includes thinking and looks complete, but this needs checking per version.
5. **Label estimates honestly and publish accuracy.** The projects people trust most separate measured numbers from estimates.
