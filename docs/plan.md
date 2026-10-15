# Plan, progress and decisions

**Status (2026-10-15): v0.1 complete.** All eight milestones are done, plus one fix found
while demoing on real data; 134 tests pass and CI is green. This file records what was
built, the decisions behind it, and what's next.

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

## Next steps

- [ ] Record the demo GIF (`vhs docs/demo.tape`) and add it to the README.
- [ ] Collect more real history; re-run `tokcast eval` at ~300 turns.
- [ ] Revisit quantile regression once real folds have 150+ training turns.
- [ ] Try recency weighting for distribution shift, adopted only if eval shows a gain.
- [ ] Verify the subagent layout on real subagent logs.
- [ ] Fit calibration weights per token type once there are many readings.
- [ ] Publish to PyPI so `uvx tokcast` works directly.
- [ ] Roadmap:
  - v2: claude.ai browser extension using `predict --json`
  - v3: suggestions
  - more log sources (Codex CLI, Cursor) via `LogSource`
