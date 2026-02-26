# PickAParlay

A local NBA player prop analysis tool that grades tonight's betting props using an 8-factor model, builds optimised parlays, and tracks prediction accuracy over time.

Available as both a **CLI tool** and a **full-stack web app** (FastAPI + Next.js). Both interfaces share the same analysis engine — changing one improves both.

---

## What it does

1. **Fetches** tonight's NBA games and player prop lines from [The Odds API](https://the-odds-api.com)
2. **Grades** each prop across 8 weighted factors using historical NBA stats (via `nba_api`)
3. **Builds** optimised parlays targeting a specified combined odds (e.g. 4/1), balancing value score and correlation risk
4. **Saves** chosen slips to SQLite and lets you **record actual outcomes** (WIN / LOSS / VOID + per-leg HIT / MISS)
5. **Analyses** prediction accuracy over time — hit rate by market, factor calibration, P&L

### Factor model

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| Consistency | 38% | Recency-weighted hit rate over last 10 games + floor analysis |
| Injury | 13% | Player health status + opponent injury advantage |
| vs Opponent | 20% | Head-to-head performance vs tonight's specific opponent |
| Home / Away | 12% | Home/away split matched to tonight's venue |
| Team Context | 7% | Team pace, recent form, rest days |
| Season Average | 6% | Season averages vs the prop line |
| Blowout Risk | 3% | Spread + H2H margin — risk of garbage time / early DNP |
| Line Value | 1% | How generous the line is vs the player's floor |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Prop data | [The Odds API](https://the-odds-api.com) (free tier: 500 req/month) |
| NBA stats | [`nba_api`](https://github.com/swar/nba_api) — official NBA stats endpoints |
| Analysis engine | Python — `pandas`, custom factor modules in `src/analysis/` |
| Cache | File-based JSON cache (`.cache/`) with per-resource TTLs |
| Database | SQLite (`pickaparlay.db`) — slips, legs, factor scores, outcomes |
| Backend API | FastAPI + Uvicorn |
| Frontend | Next.js 16 (App Router), React 19, Tailwind CSS 4, Recharts |
| CLI | Click |

---

## Project structure

```
PickAParlay/
├── main.py                  # CLI entry point
├── config.py                # All weights, thresholds, market mappings
├── requirements.txt
├── .env.example
│
├── src/
│   ├── api/
│   │   └── nba_stats.py     # NBA stats fetchers (game logs, H2H, injuries, etc.)
│   ├── analysis/
│   │   ├── prop_grader.py   # Orchestrates all 8 factors → ValuedProp
│   │   ├── bet_builder.py   # Combination search → optimised BetSlips
│   │   ├── context_filter.py
│   │   └── factors/         # One module per factor
│   ├── models.py            # Dataclasses: NBAGame, PlayerProp, ValuedProp, BetSlip, …
│   ├── cache.py             # JSON cache with TTLs + scored_props serialisation
│   └── database.py          # SQLite layer: grading_runs, saved_slips, slip_legs
│
├── backend/
│   └── app.py               # FastAPI app — 11 REST endpoints
│
└── frontend/                # Next.js app
    ├── app/
    │   ├── page.tsx         # Tonight's Props dashboard
    │   ├── slips/page.tsx   # Bet slip builder
    │   ├── history/page.tsx # Saved slips + outcome recording
    │   └── analytics/page.tsx # Accuracy charts
    ├── components/
    │   ├── FactorBar.tsx
    │   └── Badge.tsx
    └── lib/api.ts           # Typed API client
```

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm (for the web UI only)
- An **Odds API key** — free tier at [the-odds-api.com](https://the-odds-api.com) (500 requests/month)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/NjokuM/PickAParlay.git
cd PickAParlay
```

### 2. Create and activate a virtual environment

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**
```bash
python -m venv .venv
.venv\Scripts\activate
```

You should see `(.venv)` in your terminal prompt. Run all subsequent commands with the venv active.

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Set your Odds API key

```bash
cp .env.example .env
# Edit .env and set your key:
# ODDS_API_KEY=your_key_here
```

### 5. (Web UI only) Install frontend dependencies

```bash
cd frontend && npm install && cd ..
```

> **Every new terminal session:** run `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows) before running any `python` or `uvicorn` commands.

---

## Running the CLI

The CLI has three subcommands. Run `refresh` once per day to fetch and grade props; then use `slips` as many times as you like at zero cost (no API calls).

### `refresh` — Fetch and grade tonight's props

Fetches live odds, pulls NBA stats, runs all 8 factors, and caches the graded props. Also auto-saves the top-5 slips at 4/1 to the database.

```bash
python main.py refresh
```

| Flag | Default | Description |
|------|---------|-------------|
| `--season` | auto-detected | NBA season string, e.g. `2025-26` |
| `--verbose` | off | Print per-player factor breakdown during grading |

```bash
python main.py refresh --verbose
python main.py refresh --season 2025-26
```

---

### `slips` — Build parlays from cached props (instant, no API cost)

Loads the cached graded props and finds optimal parlay combinations targeting your specified odds. No API credits used.

```bash
python main.py slips --odds 4/1
```

| Flag | Default | Description |
|------|---------|-------------|
| `--odds` | required | Target combined odds. Accepts fractional (`4/1`), decimal (`5.0`), or American (`+400`) |
| `--legs` | auto | Force a specific leg count (2–6). Omit to let the builder search all sizes |
| `--min-score` | 50 | Minimum value score (0–100) a prop must have to be included |
| `--bookmaker` | all | Filter to a specific sportsbook. Use `paddypower` for Paddy Power, or any bookmaker key returned by `refresh` |
| `--save` | off | Save the returned slips to the database |
| `--verbose` | off | Print full factor breakdown for each leg |

```bash
# 4/1 accumulator, any leg count, all books
python main.py slips --odds 4/1

# 3-leg treble at 7/1 minimum score 65, Paddy Power only
python main.py slips --odds 7/1 --legs 3 --min-score 65 --bookmaker paddypower

# American odds, save results to database
python main.py slips --odds +400 --save

# Decimal odds with verbose factor output
python main.py slips --odds 5.0 --verbose
```

---

### `history` — View saved slips and accuracy stats

Displays all slips saved to the database, their outcomes (if recorded), and overall accuracy metrics.

```bash
python main.py history
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | 20 | Number of most recent slips to show |

```bash
python main.py history --limit 50
```

---

## Running the Web UI

The web UI provides the same functionality with a dark-themed dashboard. Run both servers simultaneously.

> **Note:** The venv lives at the project root (not inside `backend/`) because both the CLI and the web server import from `src/` and must be run from the project root. One venv activation covers everything.

### Terminal 1 — FastAPI backend (port 8000)

```bash
python -m uvicorn backend.app:app --reload --port 8000
```

> **Use `python -m uvicorn`, not bare `uvicorn`.** If you have conda or another Python environment active alongside `.venv`, the bare `uvicorn` command may resolve to the wrong interpreter and fail with `ModuleNotFoundError`. Prefixing with `python -m` forces it through the currently active venv.

### Terminal 2 — Next.js frontend (port 3000)

```bash
cd frontend && npm run dev
```

Then open **[http://localhost:3000](http://localhost:3000)**.

---

## Web UI pages

| Page | URL | Description |
|------|-----|-------------|
| **Tonight** | `/` | Scored props table with filters (game, sportsbook, market, player, min score). Click any row to expand the full 8-factor breakdown. Refresh button triggers a live re-grade. |
| **Slips** | `/slips` | Enter target odds and click Build — slips load instantly from cache. Select sportsbook, leg count, and min score. Save slips to the database with one click. |
| **History** | `/history` | All saved slips. Expand to mark each leg HIT or MISS, enter stake, and record the overall result (WIN / LOSS / VOID). Shows factor scores stored at prediction time. |
| **Analytics** | `/analytics` | KPI cards (win rate, P&L), hit rate by market, and a factor calibration chart (predicted vs actual hit rate). Populated after recording outcomes in History. |

---

## API endpoints

The FastAPI backend exposes the following REST endpoints (all at `http://localhost:8000`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tonight` | Tonight's NBA games |
| `GET` | `/api/props` | Graded props — filterable by `min_score`, `game`, `player`, `bookmaker`, `market` |
| `GET` | `/api/bookmakers` | Distinct bookmakers present in today's cached props |
| `POST` | `/api/refresh` | Start background fetch + grade pipeline |
| `GET` | `/api/refresh/status` | Poll refresh progress (`running`, `props_graded`, `props_total`) |
| `GET` | `/api/slips` | Build slips — params: `odds`, `legs`, `min_score`, `bookmaker` |
| `POST` | `/api/slips/save` | Save a slip to SQLite |
| `GET` | `/api/history` | Saved slips with nested legs (newest first) |
| `PATCH` | `/api/history/{id}/outcome` | Record WIN / LOSS / VOID + per-leg HIT / MISS |
| `GET` | `/api/analytics` | Aggregated accuracy stats and calibration buckets |
| `GET` | `/api/credits` | Odds API usage (`used`, `remaining`, `total`) |

---

## Odds API credit usage

The free tier provides **500 requests/month**. Credit consumption:

| Operation | Credits used |
|-----------|-------------|
| `refresh` (fetch props for all games) | ~280 requests |
| `slips` (CLI or web, from cache) | **0** |
| `history`, `analytics` | **0** |

Running `refresh` once per day uses roughly 280 credits. The remaining budget covers approximately 1 full refresh per day across the month. The sidebar credit bar tracks usage in real time.

---

## Caching

All NBA stats and odds data are cached in `.cache/` to avoid redundant API calls:

| Data | TTL |
|------|-----|
| Games / odds | 12 hours |
| Player game logs | 24 hours |
| Injuries | 45 minutes |
| Team stats / H2H | 24 hours |
| Graded props (`scored_props_YYYY-MM-DD`) | 36 hours |

The `.cache/` directory is git-ignored. Delete it to force a full re-fetch.

---

## Database

Outcomes are stored in `pickaparlay.db` (SQLite, git-ignored). Schema:

- **`grading_runs`** — one row per `refresh` run
- **`saved_slips`** — saved parlays with outcome (WIN / LOSS / VOID / pending), stake, P&L
- **`slip_legs`** — individual legs with all 8 factor scores at prediction time + HIT / MISS result

This enables factor calibration analysis: *"do props where Consistency ≥ 80 actually hit 80% of the time?"*
