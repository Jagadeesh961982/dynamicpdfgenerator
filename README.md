# 4-Agent Dynamic PDF Pipeline — v2

Generates executive-quality PDF reports from raw infrastructure alert data,
inspired by NotebookLM’s editorial slide quality. Every slide is bespoke — the LLM
decides the story, visual, and layout from scratch based on your data.

This repository includes:

- **CLI pipeline** — run `orchestrator.py` locally and write HTML/PDF under `output/`.
- **HTTP API** — FastAPI app under [`fastapi-app/`](fastapi-app/) (`/v1` routes: auth, jobs, preferences, LLM keys, chat).
- **Web UI** — Notebook-style React + Vite app under [`frontend/`](frontend/) that talks to the API.

For API-only setup, env vars, and CORS, see [`fastapi-app/README.md`](fastapi-app/README.md).

## Repository layout

```
├── orchestrator.py      # CLI entrypoint (agents + PDF export)
├── config.py            # Pipeline defaults and API keys (copy from .env.example patterns)
├── agents/              # Planner, designer, assembler, critic
├── fastapi-app/         # FastAPI service (uvicorn app.main:app)
├── frontend/            # React + Vite SPA (npm install && npm run dev)
├── output/              # CLI run artifacts (gitignored)
└── data/                # API SQLite + job storage when using FastAPI (gitignored)
```

## Architecture (CLI pipeline)

```
Raw alert data (.txt / .csv / .pdf)
         │
         ▼
┌─────────────────────────────────────────┐
│  AGENT 1: Narrative Planner             │
│  ① Python parser (exact counts, series) │
│  ② LLM designs 12 slide STORIES         │
│     - Unique title per slide            │
│     - Visual type chosen per story      │
│     - Exact data values embedded        │
│  → slide_plan.json                      │
└──────────────────┬──────────────────────┘
                   │  slide_plan
                   ▼
┌─────────────────────────────────────────┐
│  AGENT 2: Visual Designer               │
│  For each slide:                        │
│    LLM generates full HTML + inline SVG │
│    • Real data values in the visual     │
│    • Custom chart/diagram per story     │
│    • NotebookLM-quality styling         │
│  Retries broken slides up to 3×         │
│  → list of HTML slide bodies            │
└──────────────────┬──────────────────────┘
                   │  slide HTML list
                   ▼
┌─────────────────────────────────────────┐
│  AGENT 3: HTML Assembler                │
│  Wraps slides into one print-ready HTML │
│  • Global CSS (fonts, print media)      │
│  • Slide nav overlay (browser)          │
│  • Print button                         │
│  → report.html                          │
└──────────────────┬──────────────────────┘
                   │  report.html
                   ▼
┌─────────────────────────────────────────┐
│  AGENT 4: Critic                        │
│  Scores 5 dimensions (0-10):            │
│    data_accuracy  30%                   │
│    visual_quality 25%                   │
│    insight_depth  25%                   │
│    completeness   10%                   │
│    layout_design  10%                   │
│  Flags specific slides to fix           │
│  → Score ≥ threshold: export PDF       │
│  → Score < threshold: patch slides     │
│    (Agent 2 re-renders only those)      │
└──────────────────┬──────────────────────┘
                   │  passed
                   ▼
               report.pdf
```

## What’s different from v1

| v1 (Fixed Template) | v2 (Dynamic — This Version) |
|---|---|
| 12 fixed slide slots with pre-defined purpose | LLM decides every slide’s story and angle |
| Python renders from component menu | LLM writes full HTML+SVG per slide |
| Generic titles like "Alert Volume Over Time" | Specific titles like "The Kafka Backlog: 785K Messages" |
| Same chart types every run | Custom visual chosen for each specific story |
| "area_chart" component for Kafka | Bottle-neck SVG with actual consumer group name |
| Fixed CSS, pre-defined icons | LLM picks colors, layout, visual treatment freely |

## Quick start

### 1. Install (recommended: full environment)

From the **repository root**:

```bash
pip install -r requirements.txt
playwright install chromium
```

This installs the pipeline stack (Rich, pandas, pdfplumber, Playwright), PDF export, and the **FastAPI** stack (FastAPI, Uvicorn, SQLAlchemy, bcrypt, etc.). For PDF generation, **Playwright + Chromium** is recommended; see `requirements.txt` for optional `pdfkit`.

### 2. Configure

Edit `config.py` (or use per-user defaults via the API / UI after login):

```python
OPENROUTER_API_KEY = "sk-or-v1-your-key-here"
VISUAL_STYLE       = "notebooklm"   # or "modern", "dark", "auto"
```

Copy [`.env.example`](.env.example) for pipeline env hints. For the API, copy [`fastapi-app/.env.example`](fastapi-app/.env.example) to `fastapi-app/.env` — see [`fastapi-app/README.md`](fastapi-app/README.md).

### 3. Run the CLI

```bash
python orchestrator.py --input alerts.txt
python orchestrator.py --input alerts.txt --output output/my_report.pdf
python orchestrator.py --input alerts.txt --html-only
python orchestrator.py --input alerts.txt --iterations 5 --threshold 8.0 --style notebooklm
```

### 4. Run the HTTP API + web UI (optional)

**Terminal A — API** (from `fastapi-app/`):

```bash
cd fastapi-app
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

**Terminal B — frontend** (from `frontend/`):

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (e.g. `http://localhost:5173`). With the default `frontend/.env`, requests are proxied to the API on port 8000. Set `CORS_ORIGINS` on the server if you point the UI at another API URL — see [`fastapi-app/README.md`](fastapi-app/README.md).

The UI supports registration/login, **new report** (upload or paste text / JSON), **job history**, **settings** (defaults and LLM API keys), and **chat** threads backed by the API.

## Visual styles

### `notebooklm` (default)

- Warm beige/cream background (#F5F0E8)
- Bold dark headings in Playfair Display (serif)
- Editorial, information-dense
- Matches the reference NotebookLM report style

### `modern`

- Clean white/light gray background
- Sora/Inter sans-serif headings
- Tech-forward, dashboard-like

## Visual types (LLM picks the best one per slide)

| Type | Best for |
|---|---|
| `cover_hero` | Slide 1 — large title + 3 preview cards |
| `big_number_hero` | Single shocking stat (785,744 messages) |
| `bar_chart_annotated` | Comparisons with threshold lines |
| `area_chart_gradient` | Trends over time |
| `funnel_diagram` | Alert storm → categories → root causes |
| `topology_map` | System architecture with severity dots |
| `matrix_table` | Teams × impact grid |
| `flap_chart` | Metric hovering at threshold — firing/resolved cycles |
| `domino_chain` | Cascading failure sequence |
| `comparison_panel` | Two side-by-side system comparisons |
| `priority_table` | Action table with system, fix, tune columns |
| `scatter_quadrant` | Risk vs frequency matrix |
| `stat_cards_row` | 4 key metrics at a glance |
| `timeline_events` | Horizontal timeline of events |

## Input format

The same alert block format as v1:

```
========== ALERT ==========
Subject  : [FIRING:1] Kafka_Consumer_Lag - PFSC_JMD_CardHolder
Status   : Firing
Date     : 2024-01-15
Time     : 14:23:11
Agent    : hcppdkafka1.ril.com
Description : Consumer group PFSC_JMD_CardHolder_Consumer current lag count 785432
```

Also accepts `.csv` files with Subject, Status, Date, Time, Agent, Description columns, and `.pdf` files (text-extractable).

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `VISUAL_STYLE` | `"notebooklm"` | `"notebooklm"`, `"modern"`, `"dark"`, or `"auto"` |
| `MAX_ITERATIONS` | `3` | Max Designer→Critic loops |
| `PASS_THRESHOLD` | `7.5` | Min score to accept (0-10) |
| `SVG_RETRY_LIMIT` | `3` | Per-slide retry attempts |
| `N_SLIDES` | `12` | Target slide count |
| `MODEL_PLANNER` | `gemini-2.5-flash` | Agent 1 model |
| `MODEL_DESIGNER` | `gemini-2.5-flash` | Agent 2 model |
| `MODEL_CRITIC` | `gemini-2.5-flash` | Agent 4 model |

## Output files (CLI)

```
output/
├── report_plan.json          ← Slide plan from Agent 1
├── report_iter1.html         ← HTML after iteration 1
├── report_iter1_critic.json  ← Critic scores for iter 1
├── report_iter2.html         ← (if needed)
├── report.html               ← Final best HTML
└── report.pdf                ← Final PDF
```

API-rendered jobs write under `data/storage/` (see `fastapi-app` config).

## Troubleshooting

| Problem | Fix |
|---|---|
| `No alerts parsed` | Check file uses `========== ALERT ==========` separators |
| Score stuck < 7.5 | Increase `MAX_ITERATIONS = 5` or lower `PASS_THRESHOLD = 7.0` |
| Slides look generic | The LLM may have returned placeholder text — check `report_iter1_critic.json` for specifics |
| PDF blank / no PDF | Run `playwright install chromium`. For **HTML-only** runs, use `--html-only` or the API `html_only` flag |
| Playwright errors under the API | Ensure Chromium is installed; PDF export runs Playwright in a worker thread compatible with Uvicorn |
| Fonts not loading | The HTML requires internet access for Google Fonts. Open in Chrome directly to preview. |
| Auth / register errors | Use `bcrypt` (see `requirements.txt`); avoid mixing old `passlib` installs in the same venv |
| CORS from the SPA | Set `CORS_ORIGINS` in `fastapi-app/.env` to your UI origin, or use the Vite dev proxy with an empty `VITE_API_BASE_URL` |
