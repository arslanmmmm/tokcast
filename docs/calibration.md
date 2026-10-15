# Calibration: tokens → "% of your usage limit"

Claude's usage screen shows how much of your 5-hour and weekly limits you've used, as a
percentage. Anthropic doesn't publish how tokens turn into those percentages, so tokcast
**learns your own mapping** from readings and labels every percentage as an estimate.

## Recording readings

**Automatically (recommended).** For claude.ai Pro and Max subscribers, Claude Code passes
the current limits to its [status-line command](https://code.claude.com/docs/en/statusline)
(`rate_limits.five_hour.used_percentage` and `resets_at`, after the first reply of a
session). Run `tokcast statusline --setup` for the snippet to add to
`~/.claude/settings.json`; tokcast never edits that file itself.

The status line runs after every reply, so `tokcast statusline`:
- imports nothing heavy and starts in under 0.1 s (a regression test checks that pandas
  isn't loaded);
- only appends a line to a local file, and only when a reading changed. DuckDB allows one
  writing process at a time, so the database isn't touched there;
- never fails: bad input still prints a status line.

`tokcast ingest`, `calibrate` and `predict` load that file into the database.

**By hand.** Read the percentage on Claude's usage screen and run:

```bash
tokcast calibrate --used 23 --resets-in 2h10m
```

Without `--resets-in`, tokcast infers when the 5-hour window started from your logs. A
window starts with the first call after the previous one ended. Usage on other devices
can start a window earlier, so `--resets-in` is safer.

## How the mapping works

1. **Weight the tokens.** Each token type is weighted by its API price ratio:

   | input | cache write (5 min / 1 h) | cache read | output |
   |---|---|---|---|
   | 1 | 1.25 / 2 | 0.1 | 5 |

   This is an assumption: that limits weigh tokens the way prices do. A turn that re-reads a
   big context 20 times is mostly cheap cache reads.
2. **Sum the weighted tokens inside the window**, from `resets_at` minus 5 hours up to the
   moment of the reading.
3. **One ratio per reading:** % used ÷ million weighted tokens. The **median** over all
   readings is your calibration; the 10th and 90th percentiles show its spread.
4. **Predict:** % of limit ≈ ratio × (weighted / total tokens of a typical turn) × predicted
   tokens processed.

Predictions show "% of 5h limit" after **3 usable readings**. A reading is skipped if it is
under 2% (the rounding of the percentage dominates) or was taken after the last ingested
API call (its tokens aren't in the database yet; run `tokcast ingest`).

## Known biases

- **Usage outside this machine's Claude Code** (claude.ai chats, other computers) counts
  toward your limit but isn't in your local logs. That makes the ratio too large, so
  percentages **err on the high side**. That's the safer direction for planning.
- **The weights are an assumption.** With many readings, the weights themselves could be
  fitted (a non-negative regression on the token types); that's on the roadmap.
- **Limits change.** Anthropic adjusts plans and limits; old readings can mislead after a
  change. A future version should weight recent readings more.
