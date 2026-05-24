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
#  All secrets (API keys) are loaded from environment variables.
#  For CLI use: create a .env file at the repo root (see .env.example).
#  For FastAPI: set them in fastapi-app/.env (loaded by pydantic-settings).
# ══════════════════════════════════════════════════════════════════

import os
import random
from pathlib import Path

# Load .env from repo root for CLI usage (optional — falls back silently)
try:
    from dotenv import load_dotenv as _load_dotenv
    _root = Path(__file__).parent
    _load_dotenv(_root / ".env", override=False)
    _load_dotenv(_root / ".env.local", override=False)
except ImportError:
    pass

# ── Provider ───────────────────────────────────────────────────────
# "ollama"      → Local Gemma 4 via Ollama (no API key, fully private)
# "openrouter"  → Gemma 4 or any model via OpenRouter API
# "gemini"      → Gemma 4 / Gemini direct via Google AI Studio
# "nvidia"      → Models via NVIDIA NIM API
PROVIDER = os.getenv("PROVIDER", "openrouter")

# ── Ollama (local Gemma 4, no API key required) ────────────────────
# Setup: https://ollama.ai  →  ollama pull gemma4:27b
# Context windows: gemma4:27b=256K, gemma4:12b=128K, gemma4:4b=128K
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "gemma4:27b")

# Long-context mode (Gemma 4 only):
# When PROVIDER=ollama, skip chunking entirely for docs that fit in the context window.
# Gemma 4's 256K window processes entire large PDFs/CSVs in one shot — dramatically
# better fact recall vs. the old chunk-and-summarize approach.
USE_LONG_CONTEXT          = os.getenv("USE_LONG_CONTEXT", "true").lower() == "true"
GEMMA4_LONG_CONTEXT_CHARS = int(os.getenv("GEMMA4_LONG_CONTEXT_CHARS", "200000"))

# ── NVIDIA API Key ─────────────────────────────────────────────────
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")

# ── OpenRouter ─────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
_extra = os.getenv("OPENROUTER_API_KEYS", "")
OPENROUTER_API_KEYS: list[str] = [k.strip() for k in _extra.split(",") if k.strip()] if _extra else []
OPENROUTER_SITE_URL  = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "NotebookLM PDF Generator")

# ── Models per agent ───────────────────────────────────────────────
# Defaults target Gemma 4 via OpenRouter free tier.
# When PROVIDER=ollama, _resolve_model() substitutes OLLAMA_MODEL automatically.
# Override individually or use MODEL_ALL env var to set all agents at once.
MODEL_ANALYZER  = os.getenv("MODEL_ANALYZER",  "google/gemma-4-27b-it")
MODEL_PLANNER   = os.getenv("MODEL_PLANNER",   "google/gemma-4-27b-it")
MODEL_DESIGNER  = os.getenv("MODEL_DESIGNER",  "google/gemma-4-27b-it")
MODEL_ASSEMBLER = os.getenv("MODEL_ASSEMBLER", "google/gemma-4-27b-it")
MODEL_CRITIC    = os.getenv("MODEL_CRITIC",    "google/gemma-4-27b-it")

# ── Gemini direct (only if PROVIDER = "gemini") ────────────────────
GEMINI_KEY_1 = os.getenv("GEMINI_KEY_1", "")
GEMINI_KEY_2 = os.getenv("GEMINI_KEY_2", "")
GEMINI_KEY_3 = os.getenv("GEMINI_KEY_3", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-04-17")
print(f"Using Gemini model: {GEMINI_MODEL}")

# ── Pipeline settings ──────────────────────────────────────────────
MAX_ITERATIONS  = 3       # Max critic→redesign loops
PASS_THRESHOLD  = 7.5     # Score 0-10 to accept output
MAX_DATA_CHARS  = 500_000 # Input truncation limit (orchestrator trims raw input)

# Planner: chunking + analyzer/planner sample limits (see agents/planner.py)
CHUNK_MAX_CHARS = 8000
CHUNK_SUMMARY_MAX_TOKENS = 2500
ANALYZER_JOIN_MAX_CHARS = 48_000
ANALYZER_FIRST_CHUNK_CHARS = 6000
ANALYZER_LAST_CHUNK_CHARS = 4000
ANALYZER_CHUNK_SUMMARIES_JSON_MAX_CHARS = 12_000
PLANNER_RAW_EXCERPT_CHARS = 5000
PLANNER_RAW_SAMPLE_STORE_CHARS = 4000
PLANNER_ANALYSIS_JSON_MAX_CHARS = 8000

# Designer: JSON snippet of slide["data"] injected into DESIGNER_PROMPT
DESIGNER_SLIDE_DATA_JSON_MAX_CHARS = 6000
DESIGNER_RISK_MATRIX_DATA_JSON_MAX_CHARS = 12_000
RISK_MATRIX_QUADRANT_MAX_ITEMS = 6

SVG_RETRY_LIMIT = 3       # Per-slide retry attempts
N_SLIDES        = 12      # Target slide count (LLM may choose 10–14)

# ── Design variety seed ────────────────────────────────────────────
DESIGN_SEED = random.randint(1000, 9999)

# ── Visual style ───────────────────────────────────────────────────
# "notebooklm" = warm cream/beige, editorial, dense, journalistic
# "modern"     = clean white/slate, tech-forward, airy
# "dark"       = dark mode, high contrast, dramatic
# "auto"       = LLM picks based on content tone (recommended)
VISUAL_STYLE = os.getenv("VISUAL_STYLE", "auto")

# ── Browser / Web Research Agent ───────────────────────────────────
# Enriches short topic inputs with web-scraped facts before the analyzer runs.
# Requires: pip install duckduckgo-search requests beautifulsoup4 lxml
BROWSER_ENABLED           = os.getenv("BROWSER_ENABLED", "false").lower() == "true"
BROWSER_MAX_PAGES         = int(os.getenv("BROWSER_MAX_PAGES", "5"))
BROWSER_MAX_CHARS_PER_PAGE= int(os.getenv("BROWSER_MAX_CHARS_PER_PAGE", "8000"))
BROWSER_TOPIC_MAX_CHARS   = int(os.getenv("BROWSER_TOPIC_MAX_CHARS", "3000"))
