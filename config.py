# # config.py
# # ══════════════════════════════════════════════════════════════════
# #  Universal PDF Pipeline (NotebookLM-style)
# #  Agent 0: Analyzer           (LLM understands ANY input content)
# #  Agent 1: Narrative Planner  (LLM designs N slide stories)
# #  Agent 2: Visual Designer    (LLM writes full HTML+SVG per slide)
# #  Agent 3: HTML Assembler     (merges slides into one print-ready HTML)
# #  Agent 4: Critic             (scores + loops until quality gate passes)
# # ══════════════════════════════════════════════════════════════════

# # ── Provider ───────────────────────────────────────────────────────
# PROVIDER = "openrouter"   # "openrouter" | "gemini"

# # ── OpenRouter ─────────────────────────────────────────────────────
# # OPENROUTER_API_KEY   = "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"
# # OPENROUTER_API_KEY   = "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"
# # OPENROUTER_API_KEY   = "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"
# # OPENROUTER_API_KEY   = "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"
# # OPENROUTER_API_KEY   = "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"
# # OPENROUTER_API_KEY   = "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"
# # OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_SITE_URL  = ""
# OPENROUTER_SITE_NAME = "Dynamic PDF Report Generator"

# # Model for each agent — can use different models
# MODEL_ANALYZER  = "google/gemini-2.5-flash"   # Agent 0: content analysis
# MODEL_PLANNER   = "google/gemini-2.5-flash"   # Agent 1: narrative + slide plan
# MODEL_DESIGNER  = "google/gemini-2.5-flash"   # Agent 2: SVG/HTML visual per slide
# MODEL_ASSEMBLER = "google/gemini-2.5-flash"   # Agent 3: final HTML assembly
# MODEL_CRITIC    = "google/gemini-2.5-flash"   # Agent 4: quality review

# # ── Gemini direct (only if PROVIDER = "gemini") ────────────────────
# GEMINI_KEY_1  = "YOUR_GEMINI_KEY_1_HERE"
# GEMINI_KEY_2  = "YOUR_GEMINI_KEY_2_HERE"
# GEMINI_MODEL  = "gemini-2.5-flash-preview-04-17"

# # ── Pipeline settings ──────────────────────────────────────────────
# MAX_ITERATIONS    = 3      # Max critic→redesign loops
# PASS_THRESHOLD    = 8    # Score 0-10 to accept output
# MAX_DATA_CHARS    = 500000 # Input truncation limit
# SVG_RETRY_LIMIT   = 3      # Per-slide retry attempts if SVG is broken
# N_SLIDES          = 12     # Target slide count (LLM can choose 10-14)

# # ── Visual style ───────────────────────────────────────────────────
# # "notebooklm" = beige/cream bg, bold dark headings, info-dense, editorial
# # "modern"     = white/light gray, clean, tech-forward
# # "auto"       = LLM chooses based on data severity
# VISUAL_STYLE = "notebooklm"



# config.py
# ══════════════════════════════════════════════════════════════════
#  NotebookLM-style PDF Pipeline
#
#  Agent 0: Analyzer    — LLM understands ANY input content
#  Agent 1: Planner     — LLM designs N slide narratives
#  Agent 2: Designer    — LLM writes full HTML+CSS per slide
#  Agent 3: Assembler   — Merges slides into one print-ready HTML
#  Agent 4: Critic      — Scores + loops until quality gate passes
#
#  Key design principles:
#   • Every run produces a DIFFERENT visual layout (randomized design seeds)
#   • Icons rendered via inline SVG paths — NEVER font-based or CDN icons
#   • Chart.js for data plots, pure CSS/SVG for infographics
#   • Playwright-ready: animation:false, chart sentinel, networkidle wait
# ══════════════════════════════════════════════════════════════════

import random

# ── Provider ───────────────────────────────────────────────────────
PROVIDER = "openrouter"   # "openrouter" | "gemini" | "nvidia"

# ── NVIDIA API Key ─────────────────────────────────────────────────────
NVIDIA_API_KEY = "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"

# ── OpenRouter ─────────────────────────────────────────────────────
# Primary key (required). Additional keys in OPENROUTER_API_KEYS are tried in order
# when the primary hits quota (402), auth errors (401/403), or persistent rate limits (429).
# Optional: set env OPENROUTER_API_KEYS to comma-separated keys (appended as extra fallbacks).
OPENROUTER_API_KEY   = "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"
OPENROUTER_API_KEYS: list[str] = [
   "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",
   "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"
]
OPENROUTER_SITE_URL  = ""
OPENROUTER_SITE_NAME = "NotebookLM PDF Generator"

# ── Models per agent ───────────────────────────────────────────────
MODEL_ANALYZER  = "google/gemini-3.1-flash-lite-preview"
MODEL_PLANNER   = "google/gemini-3.1-flash-lite-preview"
MODEL_DESIGNER  = "google/gemini-3.1-flash-lite-preview"
MODEL_ASSEMBLER = "google/gemini-3.1-flash-lite-preview"
MODEL_CRITIC    = "google/gemini-3.1-flash-lite-preview"

# MODEL_ANALYZER = "meta/llama3-70b-instruct"
# MODEL_PLANNER = "meta/llama3-70b-instruct"
# MODEL_DESIGNER = "meta/llama3-70b-instruct"
# MODEL_ASSEMBLER = "meta/llama3-70b-instruct"
# MODEL_CRITIC = "meta/llama3-70b-instruct"

# ── Gemini direct (only if PROVIDER = "gemini") ────────────────────
GEMINI_KEY_1  = "YOUR_GEMINI_KEY_1_HERE"
GEMINI_KEY_2  = "YOUR_GEMINI_KEY_2_HERE"
GEMINI_MODEL  = "gemini-2.5-flash-preview-04-17"

# ── Pipeline settings ──────────────────────────────────────────────
MAX_ITERATIONS  = 3       # Max critic→redesign loops
PASS_THRESHOLD  = 7.5     # Score 0-10 to accept output
MAX_DATA_CHARS  = 500_000 # Input truncation limit (orchestrator trims raw input)

# Planner: chunking + analyzer/planner sample limits (see agents/planner.py)
# CHUNK_MAX_CHARS splits the document; each chunk is sent in full to per-chunk summarization.
CHUNK_MAX_CHARS = 8000
CHUNK_SUMMARY_MAX_TOKENS = 2500  # output budget per chunk summary JSON
ANALYZER_JOIN_MAX_CHARS = 48_000  # small-input path: max stitched sample (e.g. 4×8k chunks)
ANALYZER_FIRST_CHUNK_CHARS = 6000  # large-input path: head of first chunk in analyzer sample
ANALYZER_LAST_CHUNK_CHARS = 4000   # large-input path: tail window of last chunk
ANALYZER_CHUNK_SUMMARIES_JSON_MAX_CHARS = 12_000  # cap on aggregated chunk-summary JSON
PLANNER_RAW_EXCERPT_CHARS = 5000   # raw_excerpt passed to slide planner prompt
PLANNER_RAW_SAMPLE_STORE_CHARS = 4000  # plan['_raw_sample'] for downstream
PLANNER_ANALYSIS_JSON_MAX_CHARS = 8000  # analysis JSON in planner prompt

SVG_RETRY_LIMIT = 3       # Per-slide retry attempts
N_SLIDES        = 12      # Target slide count (LLM may choose 10–14)

# ── Design variety seed ────────────────────────────────────────────
# This changes every run so the same data produces different layouts.
# The seed is embedded in prompts so LLMs make different aesthetic choices.
DESIGN_SEED = random.randint(1000, 9999)

# ── Visual style ───────────────────────────────────────────────────
# "notebooklm" = warm cream/beige, editorial, dense, journalistic
# "modern"     = clean white/slate, tech-forward, airy
# "dark"       = dark mode, high contrast, dramatic
# "auto"       = LLM picks based on content tone (recommended)
VISUAL_STYLE = "auto"
