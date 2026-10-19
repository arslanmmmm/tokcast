# Plan, progress and decisions

**Status (2026-10-15): v0.1 complete; milestone 9 (Claude Code mod) complete.** All
eight v0.1 milestones are done, plus one fix found while demoing on real data; 135 Python
tests pass and CI is green. Milestone 9 adds a mod for Claude Code (32 tests of its own).
This file records what was built, the decisions behind it, and what's next.

## Milestones

| # | milestone | status | main commits |
|---|---|---|---|
| 0 | Scaffold: uv, src layout, Typer, ruff, pytest, CI | ✅ | `e202d2c` |
| 1 | Ingest: tolerant parser, dedupe, turns, incremental DuckDB load | ✅ | `14fc8f0`..`3f797a0`, `b1cbb26` |
| — | Research on related projects ([related-work.md](related-work.md)) | ✅ | `36b3ba3` |
| — | Fix: append-only ingest (history survives rewritten logs) | ✅ | `6af75be` |
| 2 | Synthetic data generator + subagent support | ✅ | `1ca6a3b`, `6228b66`, `08f5f92` |
| 3 | `stats` + per-version data-quality check | ✅ | `8727b27`, `6c4b186` |
| 4 | `predict`: task classifier + explainable baseline | ✅ | `5df58db`, `0255f6b` |
| 5 | `eval`: walk-forward backtest | ✅ | `76e715e`, `03e7438` |
| 6 | Quantile regression challenger (baseline kept as default) | ✅ | `405a6e5`, `47ab3fc`, `380a102` |
| 7 | `calibrate` + `statusline`: tokens → % of usage limit | ✅ | `5922e08` |
| 8 | README, data model docs, demo tape | ✅ | `505ff6a` |
| — | Fix: strip `<pasted_content>` wrapper tags from prompts (found on real data) | ✅ | `a45b2b6` |
| 9a | Claude Code mod: a character above the prompt that predicts the draft on click | ✅ | `2215b65` |
| 9b | Mod passes the live context size, model and effort | ✅ | after `2215b65` |
| 9c | 5h and weekly %: live usage, readings collected by the mod, weekly calibration | ✅ | after `74621f1` |
| 9d | Mod docs: README section, privacy/limitations, calibration doc | ✅ | after `a7c6657` |
| 9e | Mod shares the band with Claude Code's boxes; hide/show | ✅ | `f82d119` |
| 9f | Mod installable (marketplace file); `/tokcast` removed | ✅ | after `f82d119` |
| 10 | Starting guess for % of limit per plan, refined by readings | ⏳ | |

## Key decisions

Each decision lists the choice, the reason, and the alternative that was rejected.

### Data and ingest

1. **The unit of prediction is a turn**, not an API call: one human prompt plus every call
   it sets off (tool loop, subagents). That's what a user decides to send. *Rejected:
   predicting single calls, which misses most of the cost.*
2. **Deduplicate by `requestId`, keeping the max of each count.** Claude Code writes one
   line per content block and repeats the usage on each, so summing overcounts 2–3×. The
   max is correct whether the lines are identical or show growing counts while streaming.
3. **Link replies to prompts through `parentUuid`**, with file order as the fallback. Order
   by line number, because timestamps go backwards between neighbouring lines.
4. **Append-only upserts; rows are never deleted** (fixed after a competitor's issue,
   Claude-Code-Usage-Monitor #226). Claude Code rewrites logs on resume and compact and
   deletes them after 30 days, so the database is the durable record. Token counts only
   grow (`greatest`). *Rejected: delete and reinsert per file, which lost history.*
5. **Re-read a changed file in full** instead of resuming from a line offset: a new line's
   parent can sit in the part read before. Simpler and always correct.
6. **Bulk-load via Arrow, one statement per table and file.** Row-by-row `executemany`
   took 76 s for 18k calls; Arrow takes 7 s. Batching across files was measured as the
   next step and deferred: it's a first-run-only cost.
7. **Subagent calls are linked to their turn in SQL with an `ASOF JOIN`** (latest prompt in
   the same session at or before the call), since their parent links point into another
   file. The file layout comes from community reports and isn't verified on real logs.
8. **Prompt text is refreshed on re-ingest** (`ingest --full`), so parser fixes reach old
   rows. Two such fixes so far, both for text the desktop app adds to the user's message:
   - `<system-reminder>` blocks are removed entirely: they're context for the model, not
     the user's words.
   - `<pasted_content id="...">` wrapper tags are removed, but the text inside is kept: it
     is the user's prompt. The closing tag repeats the id, so the pattern allows
     attributes on both tags.
9. **Explicit casts at type boundaries:** `SUM` → `BIGINT` (DuckDB returns int128) and
   weighted tokens → `DOUBLE` (DuckDB returns `DECIMAL`). Missing text from pandas is `NaN`,
   so the type is checked rather than tested for truthiness.

### Synthetic data

10. **A seeded, documented generator** writes logs in the real format and returns ground
    truth; a test checks that every turn total from ingest equals it exactly. It's used for
    tests, demos and pipeline checks, **not** as evidence of real-world accuracy: it shares
    the built-in assumptions.
11. **Synthetic logs can't enter the real database.** `ingest` refuses unless
    `TOKCAST_HOME` points elsewhere, and README examples use synthetic data only.

### Prediction

12. **Model total tokens as re-reads × context.** Cost is dominated by re-reading the
    conversation (98% cache reads in the author's logs).
13. **Work on a log scale; effort, model and first-turn are multipliers** estimated as the
    *mean* of log residuals and shrunk toward built-in assumptions (20 pseudo-turns).
    - *Bug found:* the median reported 1.04× for a known 1.35× effect, because call counts
      are lumpy whole numbers.
    - *Bug found:* splitting groups by first/later turn starved the first-turn groups of
      data. As a multiplier, the effect survives with two examples.
14. **Spread from the user's own turns of the same task type**, needing at least 8 turns;
    otherwise it falls back to all turns, then to a labelled prior. Every estimate states
    its basis.
15. **Keyword classifier: the most distinct matching words wins, and ties go to rule
    order.** It's crude but inspectable; the rules were checked against real prompts.

### Evaluation

16. **Walk-forward backtest** (5 folds over the newest half), plus a **paired** comparison
    with the baseline (mean difference in pinball loss, 95% interval). A test asserts that
    no fold trains on the future.
17. **No tuning on the 26 real test turns.** A distribution shift was diagnosed (Q&A
    project → agentic project) and documented. Recency weighting is deferred until there
    is more data.
18. **The baseline stays the default over linear quantile regression.** QR was 3% better on
    synthetic data (interval excludes zero), but that data favours its shape by
    construction, and QR can't be tested on small real histories. It ships as an optional
    extra (`tokcast[ml]`, `--method qreg`); boosted trees under-covered and were dropped.
    The decision rule was written down before seeing the results.

### Calibration and CLI

19. **Tokens are weighted by API price ratios** (cache read 0.1, output 5; an assumption).
    The calibration is the median of % ÷ weighted tokens over readings, and percentages
    appear after 3 readings. They err high, because other devices' usage isn't in the logs.
20. **The status-line capture is standard library only**, appends to a JSONL file, never
    opens DuckDB (one writer process at a time), and never fails. tokcast prints the
    `settings.json` snippet instead of editing the user's config.
21. **Lazy imports in the CLI:** status-line startup went from 1.1 s (pandas) to 0.09 s,
    guarded by a test.
22. **Escape all user text before Rich prints it.** `[/bold]` in a prompt crashed the
    output, and the `[ml]` in the install hint was silently dropped.

### Claude Code mod (`integrations/claude-code/`)

23. **A Claude Code mod rather than a separate app.** The mod draws in the band above the
    prompt box on both the terminal and the desktop app, reads the draft with
    `$.prompt.read()` and runs the CLI as a local process (draft on stdin, `--json` out).
    The CLI stays the one place predictions are made. *Rejected: an overlay app (it can't
    read the prompt box), and reimplementing the model in TypeScript (two models to keep
    in sync).* claude.ai on the web is out of reach for a mod; that's still the roadmap's
    browser extension.
24. **Predict on a click, not on each keystroke.** Each run starts Python and DuckDB (~1 s).
25. **Pass the session's live facts:** context tokens from `$.session.usage()`, the model
    from `$.session.model()`, effort from the last main-loop `turn.step` (subagent
    requests ignored: their effort isn't the session's). Anything unknown is left out so
    tokcast falls back to its labelled default. *Rejected: `--continue`, which reads the
    last conversation as of the last ingest and so lags the live one.*
26. **Pure modules for logic** (`args.ts`, `bubble.ts`) and engine test-kit tests for the
    band on both surfaces, with the prompt box, session and process stubbed. The mod's
    tests need the Claude Code binary, so they don't run in CI yet.
27. **"% used now" from Claude Code, "+x% for this turn" from tokcast.** The live 5h and
    7-day windows come from `$.session.usage().rateLimits`; no calibration needed. The
    turn's share still needs the learned tokens → % mapping, now fitted for `7d` too
    (`weekly_pct` in the forecast). Claude has no daily limit, so "daily" means the 5h
    window.
28. **The mod collects calibration readings itself** by passing the live windows to
    `tokcast statusline` after each turn (reusing its tested parsing, no new format),
    then running `tokcast ingest`, since a reading only counts once its tokens are in the
    database. Ingest is ~2 s incremental, runs on a timer outside the turn, and the mod
    queues its tokcast calls because DuckDB allows one writer. A separate `TOKCAST_HOME`
    is never auto-ingested (it would mix real logs into synthetic data); `autoIngest`
    turns it off.
29. **Share the band instead of yielding it.** Claude Code draws surveys and question
    boxes in the same band and sets `hasSurvey`; the mod first stepped aside, and the user
    saw the character "vanish" (a survey was one cause, confirmed from a screenshot; see 31
    for the other). Now
    it draws Claude Code's tree first, unchanged, and the character under it. *Rejected:
    drawing over it (it would hide the survey) and yielding (confusing).*
30. **The user controls visibility with one button:** full character or face only, kept
    across sessions in `$.store`. A `/tokcast` command (show / hide / off / estimate) was
    built and then removed at the user's request: they want the button, not commands.
31. **Install, don't hot-reload.** The character vanished again because the app had
    restarted the conversation as a new session, and a session's hot-reload mods folder
    is tied to that session id. A marketplace file at the repo root
    (`.claude-plugin/marketplace.json`, source `./integrations/claude-code`) makes it a
    one-time install: `/plugin install tokcast-buddy --marketplace arslanmmmm/tokcast`,
    or from a local clone, read from the folder itself so edits apply on
    `/reload-plugins`. tokcast prints the commands; it doesn't change Claude Code's
    settings itself.

## Findings from the author's real logs

As of 2026-10-15: 2 projects, 63 turns, 440 API calls, 120M tokens processed, all opus at
medium effort.
- 98% of tokens processed were cache reads; output was 0.4%.
- A call at 400k+ context costs about 6× one at 50–100k (the long tokcast-building
  conversation added the 400k+ bucket). First turns are the most expensive (median 1.9M
  tokens, 18 calls).
- No suspicious usage values for Claude Code 2.1.295. The undercount reported in ccusage
  #866 doesn't appear in this version.
- Real-data eval:
  - At Milestone 5 (26 test turns): too few to separate methods; a distribution shift was
    diagnosed, and the baseline under-predicted (bias ×0.50).
  - With 62 turns (31 test turns), without any model change: the baseline had the best
    pinball loss of all methods (0.276, against 0.299 for context × re-reads), no bias
    (×0.99) and 71% coverage (±16, so not clearly below the 80% target). This supports
    the decision not to tune on the first 26 turns. It's still a small sample.
- Real data found three things the synthetic data couldn't: injected `<system-reminder>`
  blocks, `<pasted_content>` wrapper tags, and conversations growing past 400k tokens.

### Milestone 10 plan: a starting guess for "% of limit" (agreed 2026-10-15)

Today a new user sees only "% used now" until 3 readings per window exist (the cold-start
problem). Token predictions don't have this problem: ingest learns from ~30 days of
existing logs, and the built-in priors cover users with none. Usage % can't be backfilled,
because past readings aren't in the logs.

Plan:
1. A mod/CLI option for the plan: Pro, Max 5x, Max 20x.
2. A shipped prior for the ratio (% per million weighted tokens) per window and plan,
   labelled "assumed": fitted on the author's real readings (**Pro plan**), scaled by the
   published plan multipliers (Max 5x ≈ 5×, Max 20x ≈ 20× Pro usage).
3. Replace the hard 3-reading switch with shrinkage toward that prior (pseudo-readings,
   like decision 13), so a percentage shows from the first prompt and becomes the user's
   own as readings come in.

Wait for a few days of real readings first. Decision rule, written down before looking:
adopt the blended estimate only if, on held-out later readings, its median absolute error
in % is lower than the current method's with a paired 95% interval excluding zero.
Caveat: the prior comes from one user, so it's labelled "assumed" everywhere.

**Readings so far (2026-10-19):** 31 readings, all collected by the mod. 17 usable for 5h
(3 windows), 12 for 7d (1 week). No Claude Code use on Oct 16–18.

**Finding: usage outside the logs is large and lumpy.** The user confirmed using Claude
elsewhere (claude.ai, apps) on Oct 16–18 and on the morning of Oct 19:
- 7d went 13% → 34% with zero local requests in between. The ratio jumped from ~1.0 to
  ~2.4 % per million weighted tokens, so the current weekly "+x%" is ~2× too high.
- 5h went 38% → 77% in three hours, while local tokens explain ~13 points of that. The
  ratio for those readings was ~14 against ~6–9 otherwise.

**Candidate estimator for milestone 10 (not adopted):** fit the ratio from *increments*
between consecutive readings of the same window (Δ% ÷ Δ weighted tokens) instead of
totals since the window started. Outside usage before a pair then cancels, and a pair
with outside usage between them shows up as an outlier (detectable, or downweighted).
It is tested under the same decision rule as the starting guess, against the current
totals method, on held-out later readings.

### First real check of the mod (2026-10-15)

The draft "go for next milestone" was estimated by 9a at ~2.9M tokens (364k–7.4M); the
turn used 3.6M. Inside the range, median 20% low. 9a assumed a new chat (63k context) while
the conversation was at 146k: the gap 9b closes. One turn is an anecdote, not evidence;
`tokcast eval` remains the test.

## Next steps

- [ ] Record the demo GIF (`vhs docs/demo.tape`) and add it to the README.
- [ ] Collect more real history; re-run `tokcast eval` at ~300 turns.
- [ ] Revisit quantile regression once real folds have 150+ training turns.
- [ ] Try recency weighting for distribution shift, adopted only if eval shows a gain.
- [ ] Verify the subagent layout on real subagent logs.
- [ ] Fit calibration weights per token type once there are many readings.
- [ ] Publish to PyPI so `uvx tokcast` works directly.
- [ ] Milestone 10: starting guess for % of limit (see the plan above), after a few days
  of readings.
- [ ] A demo GIF of the mod on synthetic data (`tokcastHome` pointing at the demo).
- [ ] Check the weekly calibration once real 7d readings exist: one reading per turn moves
  slowly, and readings under 2% are skipped.
- [ ] Run the mod's tests in CI once the Claude Code binary can be installed there.
- [ ] Roadmap:
  - v2: claude.ai browser extension using `predict --json`
  - v3: suggestions
  - more log sources (Codex CLI, Cursor) via `LogSource`
