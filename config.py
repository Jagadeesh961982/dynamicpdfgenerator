# config.py
# ══════════════════════════════════════════════════════════════════
#  Universal PDF Pipeline (NotebookLM-style)
#  Agent 0: Analyzer           (LLM understands ANY input content)
#  Agent 1: Narrative Planner  (LLM designs N slide stories)
#  Agent 2: Visual Designer    (LLM writes full HTML+SVG per slide)
#  Agent 3: HTML Assembler     (merges slides into one print-ready HTML)
#  Agent 4: Critic             (scores + loops until quality gate passes)
# ══════════════════════════════════════════════════════════════════

# ── Provider ───────────────────────────────────────────────────────
PROVIDER = "openrouter"   # "openrouter" | "gemini"

# ── OpenRouter ─────────────────────────────────────────────────────
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
# OPENROUTER_API_KEY   = "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"
OPENROUTER_API_KEY   = "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"

OPENROUTER_SITE_URL  = ""
OPENROUTER_SITE_NAME = "Dynamic PDF Report Generator"

# Model for each agent — can use different models
MODEL_ANALYZER  = "google/gemini-2.5-flash"   # Agent 0: content analysis
MODEL_PLANNER   = "google/gemini-2.5-flash"   # Agent 1: narrative + slide plan
MODEL_DESIGNER  = "google/gemini-2.5-flash"   # Agent 2: SVG/HTML visual per slide
MODEL_ASSEMBLER = "google/gemini-2.5-flash"   # Agent 3: final HTML assembly
MODEL_CRITIC    = "google/gemini-2.5-flash"   # Agent 4: quality review

# ── Gemini direct (only if PROVIDER = "gemini") ────────────────────
GEMINI_KEY_1  = "YOUR_GEMINI_KEY_1_HERE"
GEMINI_KEY_2  = "YOUR_GEMINI_KEY_2_HERE"
GEMINI_MODEL  = "gemini-2.5-flash-preview-04-17"

# ── Pipeline settings ──────────────────────────────────────────────
MAX_ITERATIONS    = 3      # Max critic→redesign loops
PASS_THRESHOLD    = 8    # Score 0-10 to accept output
MAX_DATA_CHARS    = 500000 # Input truncation limit
SVG_RETRY_LIMIT   = 3      # Per-slide retry attempts if SVG is broken
N_SLIDES          = 12     # Target slide count (LLM can choose 10-14)

# ── Visual style ───────────────────────────────────────────────────
# "notebooklm" = beige/cream bg, bold dark headings, info-dense, editorial
# "modern"     = white/light gray, clean, tech-forward
# "auto"       = LLM chooses based on data severity
VISUAL_STYLE = "notebooklm"
