# 4-Agent Dynamic PDF Pipeline — v2

Generates executive-quality PDF reports from raw infrastructure alert data,
inspired by NotebookLM's editorial slide quality. Every slide is bespoke —
the LLM decides the story, visual, and layout from scratch based on your data.

## Architecture

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
│  → Score ≥ 7.5: export PDF             │
│  → Score < 7.5: patch broken slides    │
│    (Agent 2 re-renders only those)      │
└──────────────────┬──────────────────────┘
                   │  passed
                   ▼
               report.pdf
```

## What's Different from v1

| v1 (Fixed Template) | v2 (Dynamic — This Version) |
|---|---|
| 12 fixed slide slots with pre-defined purpose | LLM decides every slide's story and angle |
| Python renders from component menu | LLM writes full HTML+SVG per slide |
| Generic titles like "Alert Volume Over Time" | Specific titles like "The Kafka Backlog: 785K Messages" |
| Same chart types every run | Custom visual chosen for each specific story |
| "area_chart" component for Kafka | Bottle-neck SVG with actual consumer group name |
| Fixed CSS, pre-defined icons | LLM picks colors, layout, visual treatment freely |

## Quick Start

### 1. Install

```bash
pip install rich pandas playwright pdfplumber
playwright install chromium
```

### 2. Configure

Edit `config.py`:
```python
OPENROUTER_API_KEY = "sk-or-v1-your-key-here"
VISUAL_STYLE       = "notebooklm"   # or "modern"
```

### 3. Run

```bash
python orchestrator.py --input alerts.txt
python orchestrator.py --input alerts.txt --output output/my_report.pdf
python orchestrator.py --input alerts.txt --html-only
python orchestrator.py --input alerts.txt --iterations 5 --threshold 8.0 --style notebooklm
```

## Visual Styles

### `notebooklm` (default)
- Warm beige/cream background (#F5F0E8)
- Bold dark headings in Playfair Display (serif)
- Editorial, information-dense
- Matches the reference NotebookLM report style

### `modern`
- Clean white/light gray background
- Sora/Inter sans-serif headings
- Tech-forward, dashboard-like

## Visual Types (LLM picks the best one per slide)

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

## Input Format

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

## Configuration

| Setting | Default | Description |
|---|---|---|
| `VISUAL_STYLE` | `"notebooklm"` | `"notebooklm"` or `"modern"` |
| `MAX_ITERATIONS` | `3` | Max Designer→Critic loops |
| `PASS_THRESHOLD` | `7.5` | Min score to accept (0-10) |
| `SVG_RETRY_LIMIT` | `3` | Per-slide retry attempts |
| `N_SLIDES` | `12` | Target slide count |
| `MODEL_PLANNER` | `gemini-2.5-flash` | Agent 1 model |
| `MODEL_DESIGNER` | `gemini-2.5-flash` | Agent 2 model |
| `MODEL_CRITIC` | `gemini-2.5-flash` | Agent 4 model |

## Output Files

```
output/
├── report_plan.json          ← Slide plan from Agent 1
├── report_iter1.html         ← HTML after iteration 1
├── report_iter1_critic.json  ← Critic scores for iter 1
├── report_iter2.html         ← (if needed)
├── report.html               ← Final best HTML
└── report.pdf                ← Final PDF
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `No alerts parsed` | Check file uses `========== ALERT ==========` separators |
| Score stuck < 7.5 | Increase `MAX_ITERATIONS = 5` or lower `PASS_THRESHOLD = 7.0` |
| Slides look generic | The LLM may have returned placeholder text — check `report_iter1_critic.json` for specifics |
| PDF blank | Make sure `playwright install chromium` was run |
| Fonts not loading | The HTML requires internet access for Google Fonts. Open in Chrome directly to preview. |
