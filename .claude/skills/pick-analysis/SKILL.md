---
name: pick-analysis
description: Analyze PickAParlay's collected season data (graded_props outcomes) and produce a findings report on model accuracy, factor calibration, market/side breakdown, ROI/edge vs. the market, and a recommended minimum value-score threshold. Use when asked to analyze picks data, review model/grading performance, check calibration, or report on hit rate / ROI / edge for the season.
---

# pick-analysis

Produces a findings report from PickAParlay's `graded_props` outcome data —
hit rate, ROI/edge vs. the market, per-factor calibration, per-market
breakdown, and a recommended minimum value-score threshold.

## Data source — check this before anything else

This reads `pickaparlay.db` (`config.DATABASE_PATH`), **not** this git
checkout. The database is git-ignored and in production lives on the Fly
volume at `/data/pickaparlay.db`, not inside a fresh clone of this repo. A
sandboxed session almost never has it already.

Before running the report, confirm a real database with graded outcomes is
actually reachable:

1. If `config.DATABASE_PATH` already points at a populated file (local dev
   run, or a copy the user placed in the working directory), use it directly.
2. Otherwise this session has no data to analyze. Ask the user for one of:
   - Download the live file so `report.py` can read it directly:
     `fly ssh sftp get /data/pickaparlay.db ./pickaparlay.db -a pickaparlay`
   - Have them hit `GET /api/analytics` themselves (any `min_score`) and
     paste the JSON back to analyze directly, skipping `report.py`.
   - Grant this session network access to `pickaparlay.fly.dev` so
     `/api/analytics` / `/api/status` can be queried live over HTTP.

   **Never fabricate numbers or write up an empty/missing database as if it
   were a real finding.** Say plainly there's no data to analyze yet and
   stop there.

## Running the report

```
python .claude/skills/pick-analysis/report.py --min-score 65
```

- `--db PATH` — override the database location (e.g. a downloaded copy of
  the production file, or a local `.db` after running the CLI's `refresh`).
- `--min-score N` — threshold used for the headline hit-rate/ROI/edge
  figures (default 65, matching the app's own recommended cutoff). The
  threshold-comparison table always covers 60/65/70/75/80 regardless.

The script reuses `src/database.py`'s `get_analytics()` — the exact same
query logic the `/api/analytics` endpoint serves — so the report always
matches what the live app would show for the same data and threshold.

## Writing up the findings

Structure the write-up as:

1. **Sample size** — total graded picks (regular + alt), split by market,
   and the date range covered. If total graded picks is small (rule of
   thumb: under ~30 per bucket being discussed), say explicitly that the
   sample is too small for that breakdown to be reliable — don't present
   noise as signal just because a number came out of a query.
2. **Headline accuracy** — hit rate, ROI%, edge vs. implied market
   probability, at the requested threshold.
3. **Is the value score actually calibrated?** — from `value_calibration`:
   does hit rate increase monotonically with the score bucket? Call out any
   bucket that breaks monotonicity (e.g. 70-75 hitting worse than 60-65) —
   on a large enough sample that's model mis-calibration, not just variance.
4. **Per-factor calibration** — from `factor_calibration`: which of the 8
   factors predicts outcomes well on its own vs. which barely move hit rate
   at all. Name candidates to reweight or cut in `config.FACTOR_WEIGHTS`,
   backed by the actual bucketed numbers, not a general impression.
5. **Best/worst markets and sides** — from `by_market` / `by_side`.
6. **Threshold recommendation** — from `threshold_table`: the lowest
   `min_score` where ROI is reliably positive, weighed against how many
   picks get excluded at that bar (a threshold that wins on 8 picks isn't
   a recommendation).
7. **Trend over the season** — from `daily_trend` / `daily_pnl`: is
   accuracy drifting (degrading as volume grows, or shifting after a
   specific factor fix landed)?
8. **Regular vs. alt lines** — `graded_props.is_alternate` scores alt lines
   separately (`report.py` prints both `regular` and `alt` sections). Don't
   blend them into one set of numbers; alt-line markets and liquidity are
   different enough that mixing them hides whichever one is actually broken.

Keep the final write-up in plain language a sports bettor would read, but
back every claim with the concrete number behind it — never summarize
without citing the figure that supports the summary.
