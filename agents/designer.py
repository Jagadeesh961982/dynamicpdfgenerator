# # agents/designer.py
# #
# # AGENT 2 — VISUAL DESIGNER
# # ══════════════════════════
# # Generates one complete HTML slide per call.
# #
# # KEY DESIGN DECISIONS:
# #   1. Icons via [[icon:NAME:SIZE:COLOR]] placeholders.
# #      Python substitutes these AFTER the LLM returns HTML, using
# #      utils/icons.py which has REAL brand SVG paths (kubernetes wheel,
# #      docker whale, aws logo, etc.) — zero CDN dependency.
# #
# #   2. Topic-specific icons injected into every prompt.
# #      For a Kubernetes slide, the icon list starts: kubernetes, docker,
# #      container, network… so the LLM naturally picks the right ones.
# #
# #   3. DESIGN_SEED varies layout and aesthetic every run.
# #      Same data → different visual story each time.
# #
# #   4. max_tokens=16000 with split output: complex slides get more room.
# #      The original 8192 limit caused truncation → fallback table renders.
# #
# #   5. Fallback slide never shows raw dict/JSON — always styled HTML.

# import json, re, sys, html as html_lib
# from pathlib import Path
# from typing import Optional
# sys.path.insert(0, str(Path(__file__).parent.parent))
# from utils.llm import call
# from utils.icons import (
#     icon,
#     get_all_icon_names,
#     ICON_PATHS,
#     BRAND_ICONS,
#     ICON_ALIASES,
#     substitute_icon_placeholders,
#     suggest_icons_for_topic,
# )
# import config


# # ══════════════════════════════════════════════════════════════════
# #  PALETTE / STYLE SYSTEM
# # ══════════════════════════════════════════════════════════════════

# _PALETTES = {
#     "urgent": {
#         "bg": "#0F1117", "card": "#1A1D2E", "border": "#2D3148",
#         "text": "#F0F0F8", "muted": "#8888AA",
#         "red": "#EF4444", "amber": "#F59E0B", "blue": "#60A5FA", "green": "#34D399",
#         "family": "dark", "_severity": "critical",
#     },
#     "analytical": {
#         "bg": "#F7F3EC", "card": "#FFFFFF", "border": "#E0D8C8",
#         "text": "#1C1A17", "muted": "#6B6455",
#         "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
#         "family": "warm", "_severity": "balanced",
#     },
#     "educational": {
#         "bg": "#EFF6FF", "card": "#FFFFFF", "border": "#BFDBFE",
#         "text": "#1E3A5F", "muted": "#64748B",
#         "red": "#DC2626", "amber": "#D97706", "blue": "#1D4ED8", "green": "#15803D",
#         "family": "cool", "_severity": "calm",
#     },
#     "executive_summary": {
#         "bg": "#FDFAF5", "card": "#FFFFFF", "border": "#E8D5B0",
#         "text": "#1A1205", "muted": "#8A6C3A",
#         "red": "#C05621", "amber": "#B7791F", "blue": "#2B6CB0", "green": "#276749",
#         "family": "warm", "_severity": "warning",
#     },
#     "informational": {
#         "bg": "#F8FAFC", "card": "#FFFFFF", "border": "#E2E8F0",
#         "text": "#0F172A", "muted": "#64748B",
#         "red": "#DC2626", "amber": "#D97706", "blue": "#2563EB", "green": "#16A34A",
#         "family": "cool", "_severity": "balanced",
#     },
# }

# _STYLE_NOTEBOOKLM = {
#     "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
#     "text": "#1C1A17", "muted": "#6B6455",
#     "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
#     "family": "warm", "_severity": "balanced",
# }
# _STYLE_MODERN = {
#     "bg": "#F8F9FA", "card": "#FFFFFF", "border": "#DEE2E6",
#     "text": "#212529", "muted": "#6C757D",
#     "red": "#DC3545", "amber": "#FD7E14", "blue": "#0D6EFD", "green": "#198754",
#     "family": "cool", "_severity": "balanced",
# }
# _STYLE_DARK = {
#     "bg": "#0D1117", "card": "#161B22", "border": "#30363D",
#     "text": "#F0F6FC", "muted": "#8B949E",
#     "red": "#F85149", "amber": "#E3B341", "blue": "#58A6FF", "green": "#3FB950",
#     "family": "dark", "_severity": "critical",
# }


# def _get_style(plan: dict) -> dict:
#     vs   = getattr(config, 'VISUAL_STYLE', 'auto')
#     seed = plan.get('_design_seed', getattr(config, 'DESIGN_SEED', 5000))

#     if vs == 'notebooklm': return _STYLE_NOTEBOOKLM.copy()
#     if vs == 'modern':     return _STYLE_MODERN.copy()
#     if vs == 'dark':       return _STYLE_DARK.copy()

#     tone    = plan.get('_analysis', {}).get('tone', 'informational')
#     palette = _PALETTES.get(tone, _PALETTES['informational']).copy()

#     # Minor seed-based accent shift for variety
#     if seed > 7000:
#         palette['red']  = _shift_color(palette['red'],  -15)
#         palette['blue'] = _shift_color(palette['blue'], -15)
#     elif seed < 2500:
#         palette['amber'] = _shift_color(palette['amber'], +20)

#     return palette


# def _shift_color(hex_color: str, delta: int) -> str:
#     try:
#         h = hex_color.lstrip('#')
#         r, g, b = [int(h[i:i+2], 16) for i in (0, 2, 4)]
#         r = max(0, min(255, r + delta))
#         g = max(0, min(255, g + delta))
#         b = max(0, min(255, b + delta))
#         return f'#{r:02x}{g:02x}{b:02x}'
#     except Exception:
#         return hex_color


# # ══════════════════════════════════════════════════════════════════
# #  CHART.JS PADDING FIX
# #  Add layout.padding to every Chart.js config to prevent axis labels
# #  from being clipped by the canvas boundary (causes numbers cut off at bottom)
# # ══════════════════════════════════════════════════════════════════

# def _fix_chartjs_padding(html_text: str) -> str:
#     """
#     Inject layout.padding into Chart.js options if not already present.
#     This prevents axis tick labels from being clipped at canvas edges.
#     """
#     # Find all Chart.js new Chart() calls and inject padding if missing
#     def inject_padding(m: re.Match) -> str:
#         block = m.group(0)
#         if 'layout' in block and 'padding' in block:
#             return block  # Already has padding
#         # Inject after 'options: {' or before closing of options
#         return block.replace(
#             'animation: {duration: 0}',
#             'animation: {duration: 0}, layout: {padding: {bottom: 24, left: 8, right: 24, top: 8}}'
#         )
#     # Apply to script blocks containing Chart.js
#     result = re.sub(
#         r'new Chart\([^;]+\);',
#         inject_padding,
#         html_text,
#         flags=re.DOTALL,
#     )
#     return result


# # ══════════════════════════════════════════════════════════════════
# #  ICON LIST BUILDER
# #  Topic-specific brand icons come FIRST in the list so the LLM
# #  naturally picks kubernetes/docker/aws before generic server/network.
# # ══════════════════════════════════════════════════════════════════

# def _build_icon_list_for_slide(slide: dict, plan: dict = None) -> str:
#     analysis = (plan or {}).get('_analysis', {})
#     context  = " ".join([
#         analysis.get('subject', ''),
#         analysis.get('content_type', ''),
#         " ".join(analysis.get('key_entities', [])[:10]),
#         slide.get('title', ''),
#         slide.get('story_angle', ''),
#         slide.get('visual_description', ''),
#     ])

#     topic_icons = suggest_icons_for_topic(context)
#     brand_icons = sorted(BRAND_ICONS.keys())
#     generic     = sorted(ICON_PATHS.keys())

#     seen   = set()
#     result = []
#     for name in (topic_icons + brand_icons + generic):
#         if name not in seen:
#             seen.add(name)
#             result.append(name)

#     return ", ".join(result[:80])


# # ══════════════════════════════════════════════════════════════════
# #  DESIGNER PROMPT
# # ══════════════════════════════════════════════════════════════════

# DESIGNER_PROMPT = """⚠ OUTPUT FORMAT — READ FIRST:
# Output ONLY raw HTML. No JSON. No markdown. No ```html. No \\n escapes.
# Start directly with: <div class="h-full w-full" ...>
# End with closing </div> and any <script> tags.

# You are an expert Frontend Developer building one 1280×720px slide for a NotebookLM-quality PDF.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   SLIDE SPEC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Slot:           {slot}
#   Title:          {title}
#   Subtitle:       {subtitle}
#   Story angle:    {story_angle}
#   Key insight:    {key_insight}
#   Visual type:    {visual_type}
#   Visual desc:    {visual_description}
#   Color mood:     {color_mood}
#   Accent:         {accent_color}
#   Design seed:    {design_seed}

# SLIDE DATA (use EXACT values — never substitute):
# {slide_data}

# PREVIOUS CRITIC FEEDBACK (fix these):
# {feedback}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   PALETTE (use these exact hex values via Tailwind arbitrary syntax)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   bg={bg}  card={card}  text={text}  muted={muted}
#   border={border}  red={red}  amber={amber}  blue={blue}  green={green}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ICON SYSTEM — CRITICAL — READ CAREFULLY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⛔ ABSOLUTE BAN: NEVER write <svg> tags yourself. NEVER draw icons from memory.
#    The Kubernetes logo, Docker logo, or any other icon you know will look WRONG
#    if you attempt to draw it. Use ONLY the placeholder system below.

# ⛔ ABSOLUTE BAN: NEVER use <i data-lucide="..."> or any CDN icon library.

# ✅ THE ONLY CORRECT WAY to add any icon:
#    [[icon:NAME:SIZE:COLOR]]

#    Python replaces this placeholder with the correct professionally-drawn SVG.
#    This is the ONLY way icons render correctly in the PDF.

# Examples:
#   [[icon:kubernetes:64:{blue}]]        ← real Kubernetes wheel (not a blob)
#   [[icon:docker:48:{red}]]             ← real Docker whale
#   [[icon:server:32:{muted}]]           ← generic server icon
#   [[icon:alert-triangle:24:{amber}]]   ← warning icon

# Syntax: [[icon:NAME:SIZE:COLOR]]
#   NAME  = one of the names in AVAILABLE ICONS below (exact spelling)
#   SIZE  = integer pixels: 16 24 32 40 48 56 64 80 96
#   COLOR = exact hex like {blue} or {red}

# AVAILABLE ICONS (topic-specific ones listed FIRST — prefer these):
# {icon_list}

# Use [[icon:]] placeholders everywhere: every card header, every section title, every stat.
# Minimum 5 icons per slide. At least one large (64px+) in the hero area.
# If you write <svg> yourself, it will look like a random blob. Use [[icon:]] instead.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   TAILWIND CSS (CDN runtime — all classes work)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Use Tailwind for layout, spacing, typography:
#   bg-[{card}]  text-[{text}]  border-[{border}]  text-[{muted}]
#   h-[380px]  w-[45%]  border-l-4 border-[{red}]
#   font-bold font-black font-mono text-8xl rounded-xl shadow-lg p-6

# Typography scale:
#   Hero numbers: text-8xl or text-9xl font-black in accent color
#   Slide title:  text-4xl–text-5xl font-bold
#   Subtitles:    text-lg–text-2xl font-medium
#   Body:         text-sm–text-base leading-relaxed
#   Mono labels:  font-mono text-xs (for hostnames, IDs, versions, paths)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   CHART.JS (animation already disabled globally)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Use ONLY for true numeric data plots (bar, line, area, doughnut).
# NOT for metaphors, flows, or diagrams — use CSS/Tailwind for those.

# Rules:
#   1. Canvas wrapper: <div style="height:320px;position:relative;">
#   2. Canvas ID: chart_{slot}  (must be unique per slide)
#   3. Options: responsive:true, maintainAspectRatio:false, animation:{{duration:0}}
#   4. ALL <script> tags go at the VERY END of your output
#   5. After chart init: window.__chartsReady = (window.__chartsReady||0) + 1;
#   6. Use hex colors directly — no CSS vars inside Chart.js config

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ⚠ STRICT HEIGHT BUDGET — 720px TOTAL — NEVER OVERFLOW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The slide is EXACTLY 1280×720px with overflow:hidden. Content that goes
# below 720px is INVISIBLY CLIPPED — it will not show in the PDF.

# ALWAYS use this layout pattern as the outer wrapper:
#   <div class="h-full w-full flex flex-col" style="background:{bg}; max-height:720px; overflow:hidden;">

# HEIGHT BUDGET — every pixel of vertical space must add up to ≤ 720px:
#   • Outer padding top+bottom: 40-48px each (use pt-10 pb-10 = 80px)
#   • Title block (title + subtitle): ~90px
#   • Main visual area: 720 - 80padding - 90title - 60footer = ~490px MAX
#   • Bottom insight/footer strip: ≤ 60px

# RULES TO PREVENT OVERFLOW:
#   1. Use flex-1 min-h-0 on the main visual area so it flexibly fills remaining space
#   2. NEVER stack: title + subtitle + large content + insight box + padding without measuring
#   3. For bottom insight strips: keep them max 60px tall (py-3 max, single line text)
#   4. Cards in a grid: use gap-4 not gap-6, and limit card padding to p-4 not p-8
#   5. Cover slides: preview cards at bottom must use fixed h-[140px] max and pb-6 (not pb-12)
#   6. If a visual type has title + 4 cards + insight box: reduce card padding to p-3
#   7. NEVER use py-12 or p-12 inside the slide — maximum outer padding is p-10

# SAFE VERTICAL STACKING PATTERN:
#   <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}">
#     <!-- Header: fixed height ~80px -->
#     <div class="px-10 pt-8 pb-2 flex-shrink-0"> title + subtitle </div>
#     <!-- Main: fills remaining space, flex-1 prevents overflow -->  
#     <div class="flex-1 min-h-0 px-10 pb-4 overflow-hidden"> main visual </div>
#     <!-- Footer: fixed height max 56px -->
#     <div class="px-10 pb-4 flex-shrink-0"> insight strip </div>
#   </div>

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   NOTEBOOKLM VISUAL STYLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# • Cards: rounded-xl shadow-md, p-5–p-8, border-l-4 accent
# • Hero stat: text-8xl font-black in accent color as focal point
# • Backgrounds: subtle pattern or gradient OK (CSS only, no img URLs)
# • Design seed {design_seed}: >6000=bold/asymmetric, <3000=refined/symmetric
# • NO raw markdown (**bold** → use <strong>)
# • NO placeholder text — all content from slide data
# • NO JSON or dict text visible on any slide

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   VISUAL TYPE GUIDE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# cover_hero:
#   Full-bleed cover. CSS geometric bg (repeating-linear-gradient or radial-gradient).
#   CRITICAL: Use this EXACT structure to prevent bottom card clipping:
#   <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}; background-image:...">
#     <!-- Top: logo badge + title block — ~200px -->
#     <div class="px-12 pt-8 flex-shrink-0">
#       small badge pill (audience/version) + giant title text-5xl–text-6xl + subtitle text-xl
#     </div>
#     <!-- Middle: decorative element — flex-1 fills remaining -->
#     <div class="flex-1 min-h-0 flex items-center justify-center px-12">
#       optional large [[icon:NAME:96:COLOR]] or CSS decoration
#     </div>
#     <!-- Bottom: 3 preview cards — FIXED height, NO overflow -->
#     <div class="px-10 pb-6 flex-shrink-0 grid grid-cols-3 gap-4" style="height:160px">
#       3 cards each: [[icon:NAME:36:COLOR]] + bold title text-base + 1-line desc text-sm
#       Cards: rounded-xl bg-[{card}]/20 backdrop-blur p-4 border border-white/10
#     </div>
#   </div>
#   The bottom cards MUST use flex-shrink-0 + fixed height so they never get clipped.

# big_number_hero:
#   Left 55%: giant number text-[140px] or text-9xl font-black in accent.
#   Label text-2xl below. 2-3 supporting stat badges. Context sentence text-lg.
#   Right 45%: large [[icon:NAME:96:COLOR]] centered. Optional mini doughnut chart.

# stat_cards_row:
#   Title row with [[icon:NAME:32:COLOR]] right side.
#   4-card grid: each card has [[icon:NAME:40:COLOR]] top-right, big number text-4xl,
#   label, sub-label, colored top border (border-t-4).

# bar_chart_annotated:
#   Left 40%: headline + 3 key bullets each with [[icon:NAME:20:COLOR]] + text + metric badge.
#   Right 60%: Chart.js bar chart. Below: 2 insight callout boxes (border-l-4).

# area_chart_gradient:
#   Title + 3 stat pills top. Full-width Chart.js area/line with gradient fill.
#   Real timestamps on x-axis. Annotation at peak value.

# timeline_events:
#   Horizontal timeline: dots on a line, each event has [[icon:NAME:24:COLOR]],
#   date label, short description. Color dots by event type/severity.

# topology_map:
#   Title + legend. CSS grid of node cards (no SVG arrows needed).
#   Each card: [[icon:NAME:32:COLOR]] + node name in font-mono + status badge pill.
#   Group cards into labeled zones with subtle bg color.

# matrix_table:
#   Dark header row. Alternating row backgrounds. First column bold with [[icon:NAME:20:COLOR]].
#   Colored badge cells. Uppercase tracking-widest column headers.

# domino_chain:
#   Horizontal: 4-6 cards with chevron-right between them.
#   Each card: colored top border, [[icon:NAME:32:COLOR]], bold title, 2-line body.
#   Summary strip below spanning full width.

# comparison_panel:
#   Two equal panels side by side. Each: colored header + [[icon:NAME:40:COLOR]] + label.
#   Content inside: Chart.js mini bar OR 3-4 stat rows.

# priority_table:
#   Styled HTML table. Columns: Item | Priority | Action.
#   First col: [[icon:NAME:20:COLOR]] + bold name. Priority: colored pill.
#   Alternating row backgrounds.

# scatter_quadrant:
#   2×2 CSS grid (Impact/Effort, Risk/Value axes).
#   Each quadrant: colored bg-opacity-10, label top-left, item pills inside.
#   Axis labels on edges. Center point.

# funnel_diagram:
#   CSS trapezoid stages (clip-path:polygon). Each stage narrower than previous.
#   Stage label + count/% inside. Right side: stat callouts per stage.

# info_cards_grid:
#   Title. 2×2 or 3×2 card grid. Each: [[icon:NAME:32:COLOR]] top-left,
#   title font-semibold, 2-3 line desc. Alternating left-border accent colors.

# concept_diagram:
#   3-6 step horizontal flow. Each step: circle/box + [[icon:NAME:32:COLOR]] + number,
#   bold title, 2-line desc. Arrows between steps (CSS or → character styled).

# two_column_bullets:
#   Left 40%: large [[icon:NAME:64:COLOR]], title, key insight paragraph, metric badge.
#   Right 60%: 4-6 bullet items each with [[icon:NAME:20:COLOR]] + bold label + text.

# callout_hero:
#   Large pull-quote center (text-3xl font-italic). Attribution below.
#   3 supporting stats row below. Subtle gradient background.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Start with exactly: <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}; max-height:720px;">
# Generate complete, specific HTML now. Use [[icon:NAME:SIZE:COLOR]] for ALL icons.
# Remember: flex-1 min-h-0 on main content, flex-shrink-0 on header/footer."""


# # ══════════════════════════════════════════════════════════════════
# #  HTML EXTRACTION — handles all LLM output patterns
# # ══════════════════════════════════════════════════════════════════

# def _extract_html(raw: str) -> str:
#     s = raw.strip()

#     # JSON-wrapped {"html": "..."}
#     if s.startswith('{') or s.startswith('['):
#         try:
#             import json as _json
#             s_clean = re.sub(r'^```(?:json)?\s*', '', s)
#             s_clean = re.sub(r'\s*```$', '', s_clean)
#             obj = _json.loads(s_clean)
#             if isinstance(obj, list) and obj:
#                 obj = obj[0]
#             for key in ('html', 'content', 'slide', 'result', 'output', 'code'):
#                 if isinstance(obj, dict) and key in obj:
#                     candidate = obj[key]
#                     if isinstance(candidate, str) and len(candidate.strip()) > 50:
#                         return candidate.replace('\\n', '\n').replace('\\"', '"').strip()
#             if '<div' not in s[:3000].lower():
#                 return ""
#         except Exception:
#             pass

#         # Regex fallback for malformed JSON
#         m = re.search(r'"html"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.DOTALL)
#         if m:
#             candidate = m.group(1).replace('\\n', '\n').replace('\\"', '"')
#             if len(candidate.strip()) > 50:
#                 return candidate.strip()
#         if '<div' not in s[:3000].lower():
#             return ""

#     # Markdown fences
#     s = re.sub(r'^```(?:html)?\s*\n?', '', s)
#     s = re.sub(r'\n?```\s*$', '', s)

#     # Escaped newlines (LLM returned them as literals)
#     if s.count('\\n') > 15:
#         s = s.replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')

#     # Strip outer document wrapper tags
#     s = re.sub(r'<!DOCTYPE[^>]+>', '', s, flags=re.I)
#     s = re.sub(r'<html[^>]*>|</html>', '', s, flags=re.I)
#     s = re.sub(r'<head>.*?</head>', '', s, flags=re.DOTALL | re.I)
#     s = re.sub(r'<body[^>]*>|</body>', '', s, flags=re.I)

#     return s.strip()


# # ══════════════════════════════════════════════════════════════════
# #  VALIDATION
# # ══════════════════════════════════════════════════════════════════

# def _validate(html_text: str, slot: int) -> tuple[bool, str]:
#     if not html_text or len(html_text.strip()) < 300:
#         return False, f"Too short ({len(html_text)} chars)"

#     probe = html_text.strip()[:2500].lower()

#     if '<div' not in probe and '<section' not in probe:
#         return False, "No <div> or <section> found"
#     if html_text.strip().startswith('{"') or html_text.strip().startswith('[{"'):
#         return False, "Still JSON-wrapped"
#     if '```' in html_text:
#         return False, "Contains markdown fences"
#     if re.search(r'\*\*[^<]{1,60}\*\*', html_text):
#         return False, "Contains raw **markdown**"
#     if html_text.count('\\n') > 15:
#         return False, "Excessive literal \\n sequences"
#     if len(re.sub(r'<[^>]+>', '', html_text).strip()) < 60:
#         return False, "No meaningful text content"
#     if 'font-awesome' in html_text.lower():
#         return False, "Uses Font Awesome (not allowed)"
#     if 'data-lucide=' in html_text:
#         return False, "Uses Lucide CDN (use [[icon:...]] instead)"
#     # Warn if LLM drew raw SVG bypassing our [[icon:]] system
#     # We allow our substituted SVGs (they have viewBox) but catch LLM-drawn ones
#     # by looking for SVGs with circle/path combos that look like hand-drawn logos
#     raw_svg_count = html_text.lower().count('<svg ')
#     if raw_svg_count > 15:
#         # More than 15 raw SVGs = LLM drew its own icons, which look like blobs
#         return False, f"LLM drew {raw_svg_count} raw SVGs instead of using [[icon:]] placeholders"
#     return True, "ok"


# # ══════════════════════════════════════════════════════════════════
# #  CANVAS HEIGHT SAFETY PASS
# # ══════════════════════════════════════════════════════════════════

# def _ensure_canvas_heights(html_text: str) -> str:
#     lines  = html_text.split('\n')
#     result = []
#     for line in lines:
#         if '<canvas ' in line and 'id="chart_' in line:
#             prev = ' '.join(result[-3:]).lower()
#             if 'height' not in prev and 'h-[' not in prev:
#                 result.append('<div style="position:relative;height:320px">')
#                 result.append(line)
#                 result.append('</div>')
#                 continue
#         result.append(line)
#     return '\n'.join(result)


# # ══════════════════════════════════════════════════════════════════
# #  FALLBACK SLIDE — clean HTML, never shows raw dicts/JSON
# # ══════════════════════════════════════════════════════════════════

# def _safe_str(v) -> str:
#     if v is None:             return ""
#     if isinstance(v, bool):   return "Yes" if v else "No"
#     if isinstance(v, (int, float)): return str(v)
#     if isinstance(v, str):    return v[:200]
#     if isinstance(v, list):
#         if not v: return "—"
#         if all(isinstance(x, dict) for x in v):
#             parts = [str(x.get('title') or x.get('label') or x.get('fact') or '')[:60]
#                      for x in v[:5]]
#             return " · ".join(p for p in parts if p) or "—"
#         return ", ".join(str(x)[:40] for x in v[:10])
#     if isinstance(v, dict):
#         return "; ".join(f"{k}: {_safe_str(vv)}" for k, vv in list(v.items())[:5])
#     return str(v)[:200]


# def _fallback_slide(slide: dict, style: dict, plan: dict = None) -> str:
#     title   = html_lib.escape(slide.get('title', 'Slide'))
#     insight = html_lib.escape(slide.get('key_insight', ''))
#     data    = slide.get('data', {})
#     bg      = style.get('bg',     '#F5F0E8')
#     card    = style.get('card',   '#FFFFFF')
#     text_c  = style.get('text',   '#1A1A1A')
#     muted   = style.get('muted',  '#666666')
#     border  = style.get('border', '#D0CEC8')
#     blue    = style.get('blue',   '#2471A3')

#     # Use Python-rendered icon — guaranteed to show
#     info_icon = icon('info', 32, blue)

#     rows = "".join(
#         f'<tr>'
#         f'<td style="padding:9px 14px;color:{muted};font-size:12px;'
#         f'border-bottom:1px solid {border}">'
#         f'{html_lib.escape(str(k).replace("_"," ").title())}</td>'
#         f'<td style="padding:9px 14px;font-weight:600;color:{text_c};'
#         f'border-bottom:1px solid {border}">'
#         f'{html_lib.escape(_safe_str(v))}</td>'
#         f'</tr>'
#         for k, v in list(data.items())[:8]
#         if not str(k).startswith('_')
#     )
#     subtitle = (plan or {}).get('report_subtitle', 'Report')[:40]

#     return f"""<div class="h-full w-full" style="background:{bg}">
# <div style="padding:48px 64px;height:100%;box-sizing:border-box;
#             display:flex;flex-direction:column;justify-content:center;">
#   <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">
#     {info_icon}
#     <span style="font-size:10px;font-family:monospace;color:{blue};
#                  letter-spacing:3px;text-transform:uppercase">
#       {html_lib.escape(subtitle)}
#     </span>
#   </div>
#   <h2 style="font-size:38px;font-weight:900;color:{text_c};
#              margin:0 0 10px;line-height:1.2">{title}</h2>
#   <p style="font-size:16px;color:{muted};margin:0 0 22px;
#             max-width:700px;line-height:1.6">{insight}</p>
#   <div style="background:{card};border:1px solid {border};
#               border-radius:10px;overflow:hidden;max-width:800px">
#     <table style="width:100%;border-collapse:collapse">{rows}</table>
#   </div>
# </div>
# </div>"""


# # ══════════════════════════════════════════════════════════════════
# #  SINGLE SLIDE GENERATOR
# # ══════════════════════════════════════════════════════════════════

# def _generate_slide(slide: dict, style: dict,
#                     feedback: str = "", plan: dict = None) -> str:
#     slot = slide.get('slot', 0)
#     mood = slide.get('color_mood', 'info_blue')
#     seed = (plan.get('_design_seed', config.DESIGN_SEED)
#             if plan else config.DESIGN_SEED)

#     mood_to_accent = {
#         "critical_red":  style.get('red',   '#C0392B'),
#         "warning_amber": style.get('amber',  '#D4880E'),
#         "info_blue":     style.get('blue',   '#2471A3'),
#         "success_green": style.get('green',  '#1E8449'),
#         "neutral_slate": style.get('muted',  '#4A5568'),
#         "deep_purple":   '#6B46C1',
#         "teal_focus":    '#0D9488',
#     }
#     accent = mood_to_accent.get(mood, style.get('blue', '#2471A3'))

#     # Build the prompt
#     prompt = DESIGNER_PROMPT.format(
#         slot               = slot,
#         title              = slide.get('title', ''),
#         subtitle           = slide.get('subtitle', ''),
#         story_angle        = slide.get('story_angle', ''),
#         key_insight        = slide.get('key_insight', ''),
#         visual_type        = slide.get('visual_type', 'stat_cards_row'),
#         visual_description = slide.get('visual_description', ''),
#         color_mood         = mood,
#         accent_color       = accent,
#         design_seed        = seed,
#         slide_data         = json.dumps(
#                                  slide.get('data', {}), indent=2, default=str
#                              )[:2500],
#         feedback           = feedback or "None — produce your best first attempt.",
#         bg                 = style.get('bg',     '#F5F0E8'),
#         card               = style.get('card',   '#FFFFFF'),
#         text               = style.get('text',   '#1A1A1A'),
#         muted              = style.get('muted',  '#666666'),
#         border             = style.get('border', '#D0CEC8'),
#         red                = style.get('red',    '#C0392B'),
#         amber              = style.get('amber',  '#D4880E'),
#         blue               = style.get('blue',   '#2471A3'),
#         green              = style.get('green',  '#1E8449'),
#         icon_list          = _build_icon_list_for_slide(slide, plan),
#     )

#     for attempt in range(config.SVG_RETRY_LIMIT):
#         try:
#             # Use higher token limit to prevent truncation
#             # Truncation was the main cause of fallback-table renders
#             raw = call(prompt, key="designer", max_tokens=16000, json_mode=False)
#         except Exception as e:
#             print(f"      [attempt {attempt+1}] LLM error: {e}")
#             if attempt == config.SVG_RETRY_LIMIT - 1:
#                 return _fallback_slide(slide, style, plan)
#             continue

#         html_text = _extract_html(raw)
#         ok, reason = _validate(html_text, slot)

#         if ok:
#             html_text = _ensure_canvas_heights(html_text)
#             # Substitute [[icon:NAME:SIZE:COLOR]] → real inline SVG
#             html_text = substitute_icon_placeholders(html_text)
#             # Add Chart.js layout padding to prevent axis labels being clipped
#             html_text = _fix_chartjs_padding(html_text)
#             return html_text

#         preview = raw[:120].replace('\n', ' ')
#         print(f"      [attempt {attempt+1}] Failed: {reason}. Raw: {preview!r}")

#         # Progressive retry: increasingly strict prompts
#         if attempt == 0:
#             prefix = (
#                 "⚠ CRITICAL CORRECTION: Do NOT wrap output in JSON. "
#                 "Do NOT write {\"html\": \"...\"}. "
#                 "Output ONLY raw HTML starting with: "
#                 "<div class=\"h-full w-full\" style=\"background:{bg}\">\n"
#                 "Use [[icon:NAME:SIZE:COLOR]] for icons. "
#                 "No markdown fences. No JSON. Just HTML.\n\n"
#             ).format(bg=style.get('bg', '#F5F0E8'))
#         else:
#             prefix = (
#                 "FINAL ATTEMPT. Output EXACTLY this pattern:\n"
#                 f'<div class="h-full w-full" style="background:{style.get("bg","#F5F0E8")}">\n'
#                 "  <div class=\"p-12 h-full flex flex-col\">\n"
#                 "    ... your Tailwind content with [[icon:NAME:SIZE:COLOR]] ...\n"
#                 "  </div>\n"
#                 "</div>\n"
#                 "NO JSON. NO MARKDOWN. NO ```html. Just raw HTML.\n\n"
#             )
#         prompt = prefix + prompt

#     print(f"      [slot {slot}] All retries failed — Python fallback")
#     return _fallback_slide(slide, style, plan)


# # ══════════════════════════════════════════════════════════════════
# #  PUBLIC API
# # ══════════════════════════════════════════════════════════════════

# def run(plan: dict,
#         feedback: Optional[dict] = None,
#         slides_to_redo: Optional[list] = None) -> list[tuple[int, Optional[str]]]:
#     """
#     Generate HTML for all slides (or only slides_to_redo in patch mode).
#     Returns list of (slot, html_content | None).
#     """
#     style = _get_style(plan)
#     seed  = plan.get('_design_seed', config.DESIGN_SEED)
#     tone  = plan.get('_analysis', {}).get('tone', 'auto')
#     vs    = getattr(config, 'VISUAL_STYLE', 'auto')

#     # Show topic icons detected for this content
#     analysis     = plan.get('_analysis', {})
#     subject_text = (analysis.get('subject', '') + ' ' +
#                     ' '.join(analysis.get('key_entities', [])[:8]))
#     topic_icons  = suggest_icons_for_topic(subject_text)

#     print(f"  [Designer] Style={vs} | Tone={tone} | Seed={seed} | Palette={style.get('family','?')}")
#     if topic_icons:
#         print(f"  [Designer] Topic icons: {topic_icons[:8]}")

#     slides   = plan.get('slides', [])
#     total    = len(slides)
#     redo_set = set(slides_to_redo) if slides_to_redo else None
#     results: list[tuple[int, Optional[str]]] = []

#     # Build per-slot feedback map
#     slot_feedback: dict[int, str] = {}
#     if feedback and feedback.get('slides_to_fix'):
#         for sf in feedback['slides_to_fix']:
#             s = int(sf.get('slot', 0))
#             problem = sf.get('problem', '')
#             fix     = sf.get('fix', '')
#             hint    = sf.get('prev_content_hint', '')
#             slot_feedback[s] = (
#                 f"PROBLEM: {problem}. "
#                 f"FIX: {fix}. "
#                 f"CURRENT CONTENT: {hint}"
#             )

#     for slide in slides:
#         slot = slide.get('slot', 0)
#         name = slide.get('title', f'Slide {slot}')[:44]

#         if redo_set is not None and slot not in redo_set:
#             results.append((slot, None))
#             continue

#         fb = slot_feedback.get(slot, "")
#         print(f"    [{slot:02d}/{total}] {name:<46}", end=" ", flush=True)
#         html_out = _generate_slide(slide, style, feedback=fb, plan=plan)
#         results.append((slot, html_out))
#         print("✓")

#     return results






# # agents/designer.py
# #
# # AGENT 2 — VISUAL DESIGNER
# # ══════════════════════════
# # Generates one complete HTML slide per call.
# #
# # KEY DESIGN DECISIONS:
# #   1. Icons via [[icon:NAME:SIZE:COLOR]] placeholders.
# #      Python substitutes these AFTER the LLM returns HTML, using
# #      utils/icons.py which has REAL brand SVG paths (kubernetes wheel,
# #      docker whale, aws logo, etc.) — zero CDN dependency.
# #
# #   2. Topic-specific icons injected into every prompt.
# #      For a Kubernetes slide, the icon list starts: kubernetes, docker,
# #      container, network… so the LLM naturally picks the right ones.
# #
# #   3. DESIGN_SEED varies layout and aesthetic every run.
# #      Same data → different visual story each time.
# #
# #   4. max_tokens=16000 with split output: complex slides get more room.
# #      The original 8192 limit caused truncation → fallback table renders.
# #
# #   5. Fallback slide never shows raw dict/JSON — always styled HTML.

# import json, re, sys, html as html_lib
# from pathlib import Path
# from typing import Optional
# sys.path.insert(0, str(Path(__file__).parent.parent))
# from utils.llm import call
# from utils.icons import (
#     icon,
#     get_all_icon_names,
#     ICON_PATHS,
#     BRAND_ICONS,
#     ICON_ALIASES,
#     substitute_icon_placeholders,
#     suggest_icons_for_topic,
# )
# import config


# # ══════════════════════════════════════════════════════════════════
# #  PALETTE / STYLE SYSTEM
# # ══════════════════════════════════════════════════════════════════

# _PALETTES = {
#     "urgent": {
#         "bg": "#0F1117", "card": "#1A1D2E", "border": "#2D3148",
#         "text": "#F0F0F8", "muted": "#8888AA",
#         "red": "#EF4444", "amber": "#F59E0B", "blue": "#60A5FA", "green": "#34D399",
#         "family": "dark", "_severity": "critical",
#     },
#     "analytical": {
#         "bg": "#F7F3EC", "card": "#FFFFFF", "border": "#E0D8C8",
#         "text": "#1C1A17", "muted": "#6B6455",
#         "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
#         "family": "warm", "_severity": "balanced",
#     },
#     "educational": {
#         "bg": "#EFF6FF", "card": "#FFFFFF", "border": "#BFDBFE",
#         "text": "#1E3A5F", "muted": "#64748B",
#         "red": "#DC2626", "amber": "#D97706", "blue": "#1D4ED8", "green": "#15803D",
#         "family": "cool", "_severity": "calm",
#     },
#     "executive_summary": {
#         "bg": "#FDFAF5", "card": "#FFFFFF", "border": "#E8D5B0",
#         "text": "#1A1205", "muted": "#8A6C3A",
#         "red": "#C05621", "amber": "#B7791F", "blue": "#2B6CB0", "green": "#276749",
#         "family": "warm", "_severity": "warning",
#     },
#     "informational": {
#         "bg": "#F8FAFC", "card": "#FFFFFF", "border": "#E2E8F0",
#         "text": "#0F172A", "muted": "#64748B",
#         "red": "#DC2626", "amber": "#D97706", "blue": "#2563EB", "green": "#16A34A",
#         "family": "cool", "_severity": "balanced",
#     },
# }

# _STYLE_NOTEBOOKLM = {
#     "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
#     "text": "#1C1A17", "muted": "#6B6455",
#     "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
#     "family": "warm", "_severity": "balanced",
# }
# _STYLE_MODERN = {
#     "bg": "#F8F9FA", "card": "#FFFFFF", "border": "#DEE2E6",
#     "text": "#212529", "muted": "#6C757D",
#     "red": "#DC3545", "amber": "#FD7E14", "blue": "#0D6EFD", "green": "#198754",
#     "family": "cool", "_severity": "balanced",
# }
# _STYLE_DARK = {
#     "bg": "#0D1117", "card": "#161B22", "border": "#30363D",
#     "text": "#F0F6FC", "muted": "#8B949E",
#     "red": "#F85149", "amber": "#E3B341", "blue": "#58A6FF", "green": "#3FB950",
#     "family": "dark", "_severity": "critical",
# }


# def _get_style(plan: dict) -> dict:
#     vs   = getattr(config, 'VISUAL_STYLE', 'auto')
#     seed = plan.get('_design_seed', getattr(config, 'DESIGN_SEED', 5000))

#     if vs == 'notebooklm': return _STYLE_NOTEBOOKLM.copy()
#     if vs == 'modern':     return _STYLE_MODERN.copy()
#     if vs == 'dark':       return _STYLE_DARK.copy()

#     tone    = plan.get('_analysis', {}).get('tone', 'informational')
#     palette = _PALETTES.get(tone, _PALETTES['informational']).copy()

#     # Minor seed-based accent shift for variety
#     if seed > 7000:
#         palette['red']  = _shift_color(palette['red'],  -15)
#         palette['blue'] = _shift_color(palette['blue'], -15)
#     elif seed < 2500:
#         palette['amber'] = _shift_color(palette['amber'], +20)

#     return palette


# def _shift_color(hex_color: str, delta: int) -> str:
#     try:
#         h = hex_color.lstrip('#')
#         r, g, b = [int(h[i:i+2], 16) for i in (0, 2, 4)]
#         r = max(0, min(255, r + delta))
#         g = max(0, min(255, g + delta))
#         b = max(0, min(255, b + delta))
#         return f'#{r:02x}{g:02x}{b:02x}'
#     except Exception:
#         return hex_color


# # ══════════════════════════════════════════════════════════════════
# #  CHART.JS PADDING FIX
# #  Add layout.padding to every Chart.js config to prevent axis labels
# #  from being clipped by the canvas boundary (causes numbers cut off at bottom)
# # ══════════════════════════════════════════════════════════════════

# def _fix_chartjs_padding(html_text: str) -> str:
#     """
#     Inject layout.padding into Chart.js options if not already present.
#     This prevents axis tick labels from being clipped at canvas edges.
#     """
#     # Find all Chart.js new Chart() calls and inject padding if missing
#     def inject_padding(m: re.Match) -> str:
#         block = m.group(0)
#         if 'layout' in block and 'padding' in block:
#             return block  # Already has padding
#         # Inject after 'options: {' or before closing of options
#         return block.replace(
#             'animation: {duration: 0}',
#             'animation: {duration: 0}, layout: {padding: {bottom: 24, left: 8, right: 24, top: 8}}'
#         )
#     # Apply to script blocks containing Chart.js
#     result = re.sub(
#         r'new Chart\([^;]+\);',
#         inject_padding,
#         html_text,
#         flags=re.DOTALL,
#     )
#     return result


# # ══════════════════════════════════════════════════════════════════
# #  ICON LIST BUILDER
# #  Topic-specific brand icons come FIRST in the list so the LLM
# #  naturally picks kubernetes/docker/aws before generic server/network.
# # ══════════════════════════════════════════════════════════════════

# def _build_icon_list_for_slide(slide: dict, plan: dict = None) -> str:
#     analysis = (plan or {}).get('_analysis', {})
#     context  = " ".join([
#         analysis.get('subject', ''),
#         analysis.get('content_type', ''),
#         " ".join(analysis.get('key_entities', [])[:10]),
#         slide.get('title', ''),
#         slide.get('story_angle', ''),
#         slide.get('visual_description', ''),
#     ])

#     topic_icons = suggest_icons_for_topic(context)
#     brand_icons = sorted(BRAND_ICONS.keys())
#     generic     = sorted(ICON_PATHS.keys())

#     seen   = set()
#     result = []
#     for name in (topic_icons + brand_icons + generic):
#         if name not in seen:
#             seen.add(name)
#             result.append(name)

#     return ", ".join(result[:80])


# # ══════════════════════════════════════════════════════════════════
# #  DESIGNER PROMPT
# # ══════════════════════════════════════════════════════════════════

# DESIGNER_PROMPT = """⚠ OUTPUT FORMAT — READ FIRST:
# Output ONLY raw HTML. No JSON. No markdown. No ```html. No \\n escapes.
# Start directly with: <div class="h-full w-full" ...>
# End with closing </div> and any <script> tags.

# You are an expert Frontend Developer building one 1280×720px slide for a NotebookLM-quality PDF.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   SLIDE SPEC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Slot:           {slot}
#   Title:          {title}
#   Subtitle:       {subtitle}
#   Story angle:    {story_angle}
#   Key insight:    {key_insight}
#   Visual type:    {visual_type}
#   Visual desc:    {visual_description}
#   Color mood:     {color_mood}
#   Accent:         {accent_color}
#   Design seed:    {design_seed}

# SLIDE DATA (use EXACT values — never substitute):
# {slide_data}

# PREVIOUS CRITIC FEEDBACK (fix these):
# {feedback}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   PALETTE (use these exact hex values via Tailwind arbitrary syntax)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   bg={bg}  card={card}  text={text}  muted={muted}
#   border={border}  red={red}  amber={amber}  blue={blue}  green={green}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ICON SYSTEM — CRITICAL — READ CAREFULLY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⛔ ABSOLUTE BAN: NEVER write <svg> tags yourself. NEVER draw icons from memory.
#    The Kubernetes logo, Docker logo, or any other icon you know will look WRONG
#    if you attempt to draw it. Use ONLY the placeholder system below.

# ⛔ ABSOLUTE BAN: NEVER use <i data-lucide="..."> or any CDN icon library.

# ✅ THE ONLY CORRECT WAY to add any icon:
#    [[icon:NAME:SIZE:COLOR]]

#    Python replaces this placeholder with the correct professionally-drawn SVG.
#    This is the ONLY way icons render correctly in the PDF.

# Examples:
#   [[icon:kubernetes:64:{blue}]]        ← real Kubernetes wheel (not a blob)
#   [[icon:docker:48:{red}]]             ← real Docker whale
#   [[icon:server:32:{muted}]]           ← generic server icon
#   [[icon:alert-triangle:24:{amber}]]   ← warning icon

# Syntax: [[icon:NAME:SIZE:COLOR]]
#   NAME  = one of the names in AVAILABLE ICONS below (exact spelling)
#   SIZE  = integer pixels: 16 24 32 40 48 56 64 80 96
#   COLOR = exact hex like {blue} or {red}

# AVAILABLE ICONS (topic-specific ones listed FIRST — prefer these):
# {icon_list}

# Use [[icon:]] placeholders everywhere: every card header, every section title, every stat.
# Minimum 5 icons per slide. At least one large (64px+) in the hero area.
# If you write <svg> yourself, it will look like a random blob. Use [[icon:]] instead.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   TAILWIND CSS (CDN runtime — all classes work)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Use Tailwind for layout, spacing, typography:
#   bg-[{card}]  text-[{text}]  border-[{border}]  text-[{muted}]
#   h-[380px]  w-[45%]  border-l-4 border-[{red}]
#   font-bold font-black font-mono text-8xl rounded-xl shadow-lg p-6

# Typography scale:
#   Hero numbers: text-8xl or text-9xl font-black in accent color
#   Slide title:  text-4xl–text-5xl font-bold
#   Subtitles:    text-lg–text-2xl font-medium
#   Body:         text-sm–text-base leading-relaxed
#   Mono labels:  font-mono text-xs (for hostnames, IDs, versions, paths)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   CHART.JS (animation already disabled globally)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Use ONLY for true numeric data plots (bar, line, area, doughnut).
# NOT for metaphors, flows, or diagrams — use CSS/Tailwind for those.

# Rules:
#   1. Canvas wrapper: <div style="height:320px;position:relative;">
#   2. Canvas ID: chart_{slot}  (must be unique per slide)
#   3. Options: responsive:true, maintainAspectRatio:false, animation:{{duration:0}}
#   4. ALL <script> tags go at the VERY END of your output
#   5. After chart init: window.__chartsReady = (window.__chartsReady||0) + 1;
#   6. Use hex colors directly — no CSS vars inside Chart.js config

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ⚠ STRICT HEIGHT BUDGET — 720px TOTAL — NEVER OVERFLOW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The slide is EXACTLY 1280×720px with overflow:hidden. Content that goes
# below 720px is INVISIBLY CLIPPED — it will not show in the PDF.

# ALWAYS use this layout pattern as the outer wrapper:
#   <div class="h-full w-full flex flex-col" style="background:{bg}; max-height:720px; overflow:hidden;">

# HEIGHT BUDGET — every pixel of vertical space must add up to ≤ 720px:
#   • Outer padding top+bottom: 40-48px each (use pt-10 pb-10 = 80px)
#   • Title block (title + subtitle): ~90px
#   • Main visual area: 720 - 80padding - 90title - 60footer = ~490px MAX
#   • Bottom insight/footer strip: ≤ 60px

# RULES TO PREVENT OVERFLOW:
#   1. Use flex-1 min-h-0 on the main visual area so it flexibly fills remaining space
#   2. NEVER stack: title + subtitle + large content + insight box + padding without measuring
#   3. For bottom insight strips: keep them max 60px tall (py-3 max, single line text)
#   4. Cards in a grid: use gap-4 not gap-6, and limit card padding to p-4 not p-8
#   5. Cover slides: preview cards at bottom must use fixed h-[140px] max and pb-6 (not pb-12)
#   6. If a visual type has title + 4 cards + insight box: reduce card padding to p-3
#   7. NEVER use py-12 or p-12 inside the slide — maximum outer padding is p-10

# SAFE VERTICAL STACKING PATTERN:
#   <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}">
#     <!-- Header: fixed height ~80px -->
#     <div class="px-10 pt-8 pb-2 flex-shrink-0"> title + subtitle </div>
#     <!-- Main: fills remaining space, flex-1 prevents overflow -->  
#     <div class="flex-1 min-h-0 px-10 pb-4 overflow-hidden"> main visual </div>
#     <!-- Footer: fixed height max 56px -->
#     <div class="px-10 pb-4 flex-shrink-0"> insight strip </div>
#   </div>

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   NOTEBOOKLM VISUAL STYLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# • Cards: rounded-xl shadow-md, p-5–p-8, border-l-4 accent
# • Hero stat: text-8xl font-black in accent color as focal point
# • Backgrounds: subtle pattern or gradient OK (CSS only, no img URLs)
# • Design seed {design_seed}: >6000=bold/asymmetric, <3000=refined/symmetric
# • NO raw markdown (**bold** → use <strong>)
# • NO placeholder text — all content from slide data
# • NO JSON or dict text visible on any slide

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   VISUAL TYPE GUIDE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# cover_hero:
#   Full-bleed cover. CSS geometric bg (repeating-linear-gradient or radial-gradient).
#   CRITICAL: Use this EXACT structure to prevent bottom card clipping:
#   <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}; background-image:...">
#     <!-- Top: logo badge + title block — ~200px -->
#     <div class="px-12 pt-8 flex-shrink-0">
#       small badge pill (audience/version) + giant title text-5xl–text-6xl + subtitle text-xl
#     </div>
#     <!-- Middle: decorative element — flex-1 fills remaining -->
#     <div class="flex-1 min-h-0 flex items-center justify-center px-12">
#       optional large [[icon:NAME:96:COLOR]] or CSS decoration
#     </div>
#     <!-- Bottom: 3 preview cards — FIXED height, NO overflow -->
#     <div class="px-10 pb-6 flex-shrink-0 grid grid-cols-3 gap-4" style="height:160px">
#       3 cards each: [[icon:NAME:36:COLOR]] + bold title text-base + 1-line desc text-sm
#       Cards: rounded-xl bg-[{card}]/20 backdrop-blur p-4 border border-white/10
#     </div>
#   </div>
#   The bottom cards MUST use flex-shrink-0 + fixed height so they never get clipped.

# big_number_hero:
#   Left 55%: giant number text-[140px] or text-9xl font-black in accent.
#   Label text-2xl below. 2-3 supporting stat badges. Context sentence text-lg.
#   Right 45%: large [[icon:NAME:96:COLOR]] centered. Optional mini doughnut chart.

# stat_cards_row:
#   Title row with [[icon:NAME:32:COLOR]] right side.
#   4-card grid: each card has [[icon:NAME:40:COLOR]] top-right, big number text-4xl,
#   label, sub-label, colored top border (border-t-4).

# bar_chart_annotated:
#   Left 40%: headline + 3 key bullets each with [[icon:NAME:20:COLOR]] + text + metric badge.
#   Right 60%: Chart.js bar chart. Below: 2 insight callout boxes (border-l-4).

# area_chart_gradient:
#   Title + 3 stat pills top. Full-width Chart.js area/line with gradient fill.
#   Real timestamps on x-axis. Annotation at peak value.

# timeline_events:
#   Horizontal timeline: dots on a line, each event has [[icon:NAME:24:COLOR]],
#   date label, short description. Color dots by event type/severity.

# topology_map:
#   Title + legend. CSS grid of node cards (no SVG arrows needed).
#   Each card: [[icon:NAME:32:COLOR]] + node name in font-mono + status badge pill.
#   Group cards into labeled zones with subtle bg color.

# matrix_table:
#   Dark header row. Alternating row backgrounds. First column bold with [[icon:NAME:20:COLOR]].
#   Colored badge cells. Uppercase tracking-widest column headers.

# domino_chain:
#   Horizontal: 4-6 cards with chevron-right between them.
#   Each card: colored top border, [[icon:NAME:32:COLOR]], bold title, 2-line body.
#   Summary strip below spanning full width.

# comparison_panel:
#   Two equal panels side by side. Each: colored header + [[icon:NAME:40:COLOR]] + label.
#   Content inside: Chart.js mini bar OR 3-4 stat rows.

# priority_table:
#   Styled HTML table. Columns: Item | Priority | Action.
#   First col: [[icon:NAME:20:COLOR]] + bold name. Priority: colored pill.
#   Alternating row backgrounds.

# scatter_quadrant:
#   2×2 CSS grid (Impact/Effort, Risk/Value axes).
#   Each quadrant: colored bg-opacity-10, label top-left, item pills inside.
#   Axis labels on edges. Center point.

# funnel_diagram:
#   CSS trapezoid stages (clip-path:polygon). Each stage narrower than previous.
#   Stage label + count/% inside. Right side: stat callouts per stage.

# info_cards_grid:
#   Title. 2×2 or 3×2 card grid. Each: [[icon:NAME:32:COLOR]] top-left,
#   title font-semibold, 2-3 line desc. Alternating left-border accent colors.

# concept_diagram:
#   3-6 step horizontal flow. Each step: circle/box + [[icon:NAME:32:COLOR]] + number,
#   bold title, 2-line desc. Arrows between steps (CSS or → character styled).

# two_column_bullets:
#   Left 40%: large [[icon:NAME:64:COLOR]], title, key insight paragraph, metric badge.
#   Right 60%: 4-6 bullet items each with [[icon:NAME:20:COLOR]] + bold label + text.

# callout_hero:
#   Large pull-quote center (text-3xl font-italic). Attribution below.
#   3 supporting stats row below. Subtle gradient background.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Start with exactly: <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}; max-height:720px;">
# Generate complete, specific HTML now. Use [[icon:NAME:SIZE:COLOR]] for ALL icons.
# Remember: flex-1 min-h-0 on main content, flex-shrink-0 on header/footer."""


# # ══════════════════════════════════════════════════════════════════
# #  HTML EXTRACTION — handles all LLM output patterns
# # ══════════════════════════════════════════════════════════════════

# def _extract_html(raw: str) -> str:
#     s = raw.strip()

#     # JSON-wrapped {"html": "..."}
#     if s.startswith('{') or s.startswith('['):
#         try:
#             import json as _json
#             s_clean = re.sub(r'^```(?:json)?\s*', '', s)
#             s_clean = re.sub(r'\s*```$', '', s_clean)
#             obj = _json.loads(s_clean)
#             if isinstance(obj, list) and obj:
#                 obj = obj[0]
#             for key in ('html', 'content', 'slide', 'result', 'output', 'code'):
#                 if isinstance(obj, dict) and key in obj:
#                     candidate = obj[key]
#                     if isinstance(candidate, str) and len(candidate.strip()) > 50:
#                         return candidate.replace('\\n', '\n').replace('\\"', '"').strip()
#             if '<div' not in s[:3000].lower():
#                 return ""
#         except Exception:
#             pass

#         # Regex fallback for malformed JSON
#         m = re.search(r'"html"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.DOTALL)
#         if m:
#             candidate = m.group(1).replace('\\n', '\n').replace('\\"', '"')
#             if len(candidate.strip()) > 50:
#                 return candidate.strip()
#         if '<div' not in s[:3000].lower():
#             return ""

#     # Markdown fences
#     s = re.sub(r'^```(?:html)?\s*\n?', '', s)
#     s = re.sub(r'\n?```\s*$', '', s)

#     # Escaped newlines (LLM returned them as literals)
#     if s.count('\\n') > 15:
#         s = s.replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')

#     # Strip outer document wrapper tags
#     s = re.sub(r'<!DOCTYPE[^>]+>', '', s, flags=re.I)
#     s = re.sub(r'<html[^>]*>|</html>', '', s, flags=re.I)
#     s = re.sub(r'<head>.*?</head>', '', s, flags=re.DOTALL | re.I)
#     s = re.sub(r'<body[^>]*>|</body>', '', s, flags=re.I)

#     return s.strip()


# # ══════════════════════════════════════════════════════════════════
# #  VALIDATION
# # ══════════════════════════════════════════════════════════════════

# def _validate(html_text: str, slot: int) -> tuple[bool, str]:
#     if not html_text or len(html_text.strip()) < 300:
#         return False, f"Too short ({len(html_text)} chars)"

#     probe = html_text.strip()[:2500].lower()

#     if '<div' not in probe and '<section' not in probe:
#         return False, "No <div> or <section> found"
#     if html_text.strip().startswith('{"') or html_text.strip().startswith('[{"'):
#         return False, "Still JSON-wrapped"
#     if '```' in html_text:
#         return False, "Contains markdown fences"
#     if re.search(r'\*\*[^<]{1,60}\*\*', html_text):
#         return False, "Contains raw **markdown**"
#     if html_text.count('\\n') > 15:
#         return False, "Excessive literal \\n sequences"
#     if len(re.sub(r'<[^>]+>', '', html_text).strip()) < 60:
#         return False, "No meaningful text content"
#     if 'font-awesome' in html_text.lower():
#         return False, "Uses Font Awesome (not allowed)"
#     if 'data-lucide=' in html_text:
#         return False, "Uses Lucide CDN (use [[icon:...]] instead)"
#     # Warn if LLM drew raw SVG bypassing our [[icon:]] system
#     # We allow our substituted SVGs (they have viewBox) but catch LLM-drawn ones
#     # by looking for SVGs with circle/path combos that look like hand-drawn logos
#     raw_svg_count = html_text.lower().count('<svg ')
#     if raw_svg_count > 15:
#         # More than 15 raw SVGs = LLM drew its own icons, which look like blobs
#         return False, f"LLM drew {raw_svg_count} raw SVGs instead of using [[icon:]] placeholders"
#     return True, "ok"


# # ══════════════════════════════════════════════════════════════════
# #  CANVAS HEIGHT SAFETY PASS
# # ══════════════════════════════════════════════════════════════════

# def _ensure_canvas_heights(html_text: str) -> str:
#     lines  = html_text.split('\n')
#     result = []
#     for line in lines:
#         if '<canvas ' in line and 'id="chart_' in line:
#             prev = ' '.join(result[-3:]).lower()
#             if 'height' not in prev and 'h-[' not in prev:
#                 result.append('<div style="position:relative;height:320px">')
#                 result.append(line)
#                 result.append('</div>')
#                 continue
#         result.append(line)
#     return '\n'.join(result)


# # ══════════════════════════════════════════════════════════════════
# #  FALLBACK SLIDE — clean HTML, never shows raw dicts/JSON
# # ══════════════════════════════════════════════════════════════════

# def _safe_str(v) -> str:
#     if v is None:             return ""
#     if isinstance(v, bool):   return "Yes" if v else "No"
#     if isinstance(v, (int, float)): return str(v)
#     if isinstance(v, str):    return v[:200]
#     if isinstance(v, list):
#         if not v: return "—"
#         if all(isinstance(x, dict) for x in v):
#             parts = [str(x.get('title') or x.get('label') or x.get('fact') or '')[:60]
#                      for x in v[:5]]
#             return " · ".join(p for p in parts if p) or "—"
#         return ", ".join(str(x)[:40] for x in v[:10])
#     if isinstance(v, dict):
#         return "; ".join(f"{k}: {_safe_str(vv)}" for k, vv in list(v.items())[:5])
#     return str(v)[:200]


# def _fallback_slide(slide: dict, style: dict, plan: dict = None) -> str:
#     title   = html_lib.escape(slide.get('title', 'Slide'))
#     insight = html_lib.escape(slide.get('key_insight', ''))
#     data    = slide.get('data', {})
#     bg      = style.get('bg',     '#F5F0E8')
#     card    = style.get('card',   '#FFFFFF')
#     text_c  = style.get('text',   '#1A1A1A')
#     muted   = style.get('muted',  '#666666')
#     border  = style.get('border', '#D0CEC8')
#     blue    = style.get('blue',   '#2471A3')

#     # Use Python-rendered icon — guaranteed to show
#     info_icon = icon('info', 32, blue)

#     rows = "".join(
#         f'<tr>'
#         f'<td style="padding:9px 14px;color:{muted};font-size:12px;'
#         f'border-bottom:1px solid {border}">'
#         f'{html_lib.escape(str(k).replace("_"," ").title())}</td>'
#         f'<td style="padding:9px 14px;font-weight:600;color:{text_c};'
#         f'border-bottom:1px solid {border}">'
#         f'{html_lib.escape(_safe_str(v))}</td>'
#         f'</tr>'
#         for k, v in list(data.items())[:8]
#         if not str(k).startswith('_')
#     )
#     subtitle = (plan or {}).get('report_subtitle', 'Report')[:40]

#     return f"""<div class="h-full w-full" style="background:{bg}">
# <div style="padding:48px 64px;height:100%;box-sizing:border-box;
#             display:flex;flex-direction:column;justify-content:center;">
#   <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">
#     {info_icon}
#     <span style="font-size:10px;font-family:monospace;color:{blue};
#                  letter-spacing:3px;text-transform:uppercase">
#       {html_lib.escape(subtitle)}
#     </span>
#   </div>
#   <h2 style="font-size:38px;font-weight:900;color:{text_c};
#              margin:0 0 10px;line-height:1.2">{title}</h2>
#   <p style="font-size:16px;color:{muted};margin:0 0 22px;
#             max-width:700px;line-height:1.6">{insight}</p>
#   <div style="background:{card};border:1px solid {border};
#               border-radius:10px;overflow:hidden;max-width:800px">
#     <table style="width:100%;border-collapse:collapse">{rows}</table>
#   </div>
# </div>
# </div>"""


# # ══════════════════════════════════════════════════════════════════
# #  SINGLE SLIDE GENERATOR
# # ══════════════════════════════════════════════════════════════════

# def _generate_slide(slide: dict, style: dict,
#                     feedback: str = "", plan: dict = None) -> str:
#     slot = slide.get('slot', 0)
#     mood = slide.get('color_mood', 'info_blue')
#     seed = (plan.get('_design_seed', config.DESIGN_SEED)
#             if plan else config.DESIGN_SEED)

#     mood_to_accent = {
#         "critical_red":  style.get('red',   '#C0392B'),
#         "warning_amber": style.get('amber',  '#D4880E'),
#         "info_blue":     style.get('blue',   '#2471A3'),
#         "success_green": style.get('green',  '#1E8449'),
#         "neutral_slate": style.get('muted',  '#4A5568'),
#         "deep_purple":   '#6B46C1',
#         "teal_focus":    '#0D9488',
#     }
#     accent = mood_to_accent.get(mood, style.get('blue', '#2471A3'))

#     # Build the prompt
#     prompt = DESIGNER_PROMPT.format(
#         slot               = slot,
#         title              = slide.get('title', ''),
#         subtitle           = slide.get('subtitle', ''),
#         story_angle        = slide.get('story_angle', ''),
#         key_insight        = slide.get('key_insight', ''),
#         visual_type        = slide.get('visual_type', 'stat_cards_row'),
#         visual_description = slide.get('visual_description', ''),
#         color_mood         = mood,
#         accent_color       = accent,
#         design_seed        = seed,
#         slide_data         = json.dumps(
#                                  slide.get('data', {}), indent=2, default=str
#                              )[:2500],
#         feedback           = feedback or "None — produce your best first attempt.",
#         bg                 = style.get('bg',     '#F5F0E8'),
#         card               = style.get('card',   '#FFFFFF'),
#         text               = style.get('text',   '#1A1A1A'),
#         muted              = style.get('muted',  '#666666'),
#         border             = style.get('border', '#D0CEC8'),
#         red                = style.get('red',    '#C0392B'),
#         amber              = style.get('amber',  '#D4880E'),
#         blue               = style.get('blue',   '#2471A3'),
#         green              = style.get('green',  '#1E8449'),
#         icon_list          = _build_icon_list_for_slide(slide, plan),
#     )

#     for attempt in range(config.SVG_RETRY_LIMIT):
#         try:
#             # Use higher token limit to prevent truncation
#             # Truncation was the main cause of fallback-table renders
#             raw = call(prompt, key="designer", max_tokens=16000, json_mode=False)
#         except Exception as e:
#             print(f"      [attempt {attempt+1}] LLM error: {e}")
#             if attempt == config.SVG_RETRY_LIMIT - 1:
#                 return _fallback_slide(slide, style, plan)
#             continue

#         html_text = _extract_html(raw)
#         ok, reason = _validate(html_text, slot)

#         if ok:
#             html_text = _ensure_canvas_heights(html_text)
#             # Substitute [[icon:NAME:SIZE:COLOR]] → real inline SVG
#             html_text = substitute_icon_placeholders(html_text)
#             # Add Chart.js layout padding to prevent axis labels being clipped
#             html_text = _fix_chartjs_padding(html_text)
#             return html_text

#         preview = raw[:120].replace('\n', ' ')
#         print(f"      [attempt {attempt+1}] Failed: {reason}. Raw: {preview!r}")

#         # Progressive retry: increasingly strict prompts
#         if attempt == 0:
#             prefix = (
#                 "⚠ CRITICAL CORRECTION: Do NOT wrap output in JSON. "
#                 "Do NOT write {\"html\": \"...\"}. "
#                 "Output ONLY raw HTML starting with: "
#                 "<div class=\"h-full w-full\" style=\"background:{bg}\">\n"
#                 "Use [[icon:NAME:SIZE:COLOR]] for icons. "
#                 "No markdown fences. No JSON. Just HTML.\n\n"
#             ).format(bg=style.get('bg', '#F5F0E8'))
#         else:
#             prefix = (
#                 "FINAL ATTEMPT. Output EXACTLY this pattern:\n"
#                 f'<div class="h-full w-full" style="background:{style.get("bg","#F5F0E8")}">\n'
#                 "  <div class=\"p-12 h-full flex flex-col\">\n"
#                 "    ... your Tailwind content with [[icon:NAME:SIZE:COLOR]] ...\n"
#                 "  </div>\n"
#                 "</div>\n"
#                 "NO JSON. NO MARKDOWN. NO ```html. Just raw HTML.\n\n"
#             )
#         prompt = prefix + prompt

#     print(f"      [slot {slot}] All retries failed — Python fallback")
#     return _fallback_slide(slide, style, plan)


# # ══════════════════════════════════════════════════════════════════
# #  PUBLIC API
# # ══════════════════════════════════════════════════════════════════

# def run(plan: dict,
#         feedback: Optional[dict] = None,
#         slides_to_redo: Optional[list] = None) -> list[tuple[int, Optional[str]]]:
#     """
#     Generate HTML for all slides (or only slides_to_redo in patch mode).
#     Returns list of (slot, html_content | None).
#     """
#     style = _get_style(plan)
#     seed  = plan.get('_design_seed', config.DESIGN_SEED)
#     tone  = plan.get('_analysis', {}).get('tone', 'auto')
#     vs    = getattr(config, 'VISUAL_STYLE', 'auto')

#     # Show topic icons detected for this content
#     analysis     = plan.get('_analysis', {})
#     subject_text = (analysis.get('subject', '') + ' ' +
#                     ' '.join(analysis.get('key_entities', [])[:8]))
#     topic_icons  = suggest_icons_for_topic(subject_text)

#     print(f"  [Designer] Style={vs} | Tone={tone} | Seed={seed} | Palette={style.get('family','?')}")
#     if topic_icons:
#         print(f"  [Designer] Topic icons: {topic_icons[:8]}")

#     slides   = plan.get('slides', [])
#     total    = len(slides)
#     redo_set = set(slides_to_redo) if slides_to_redo else None
#     results: list[tuple[int, Optional[str]]] = []

#     # Build per-slot feedback map
#     slot_feedback: dict[int, str] = {}
#     if feedback and feedback.get('slides_to_fix'):
#         for sf in feedback['slides_to_fix']:
#             s = int(sf.get('slot', 0))
#             problem = sf.get('problem', '')
#             fix     = sf.get('fix', '')
#             hint    = sf.get('prev_content_hint', '')
#             slot_feedback[s] = (
#                 f"PROBLEM: {problem}. "
#                 f"FIX: {fix}. "
#                 f"CURRENT CONTENT: {hint}"
#             )

#     for slide in slides:
#         slot = slide.get('slot', 0)
#         name = slide.get('title', f'Slide {slot}')[:44]

#         if redo_set is not None and slot not in redo_set:
#             results.append((slot, None))
#             continue

#         fb = slot_feedback.get(slot, "")
#         print(f"    [{slot:02d}/{total}] {name:<46}", end=" ", flush=True)
#         html_out = _generate_slide(slide, style, feedback=fb, plan=plan)
#         results.append((slot, html_out))
#         print("✓")

#     return results


# agents/designer.py
#
# AGENT 2 — VISUAL DESIGNER
# ══════════════════════════
# Generates one complete HTML slide per call.
#
# KEY DESIGN DECISIONS:
#   1. Icons via [[icon:NAME:SIZE:COLOR]] placeholders.
#      Python substitutes these AFTER the LLM returns HTML, using
#      utils/icons.py which has REAL brand SVG paths (kubernetes wheel,
#      docker whale, aws logo, etc.) — zero CDN dependency.
#
#   2. Topic-specific icons injected into every prompt.
#      For a Kubernetes slide, the icon list starts: kubernetes, docker,
#      container, network… so the LLM naturally picks the right ones.
#
#   3. DESIGN_SEED varies layout and aesthetic every run.
#      Same data → different visual story each time.
#
#   4. max_tokens=16000 with split output: complex slides get more room.
#      The original 8192 limit caused truncation → fallback table renders.
#
#   5. Fallback slide never shows raw dict/JSON — always styled HTML.

import json, re, sys, html as html_lib
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call
from utils.icons import (
    icon,
    get_all_icon_names,
    ICON_PATHS,
    BRAND_ICONS,
    ICON_ALIASES,
    substitute_icon_placeholders,
    suggest_icons_for_topic,
)
import config


# ══════════════════════════════════════════════════════════════════
#  PALETTE / STYLE SYSTEM
# ══════════════════════════════════════════════════════════════════

_PALETTES = {
    "urgent": {
        "bg": "#0F1117", "card": "#1A1D2E", "border": "#2D3148",
        "text": "#F0F0F8", "muted": "#8888AA",
        "red": "#EF4444", "amber": "#F59E0B", "blue": "#60A5FA", "green": "#34D399",
        "family": "dark", "_severity": "critical",
    },
    "analytical": {
        "bg": "#F7F3EC", "card": "#FFFFFF", "border": "#E0D8C8",
        "text": "#1C1A17", "muted": "#6B6455",
        "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
        "family": "warm", "_severity": "balanced",
    },
    "educational": {
        "bg": "#EFF6FF", "card": "#FFFFFF", "border": "#BFDBFE",
        "text": "#1E3A5F", "muted": "#64748B",
        "red": "#DC2626", "amber": "#D97706", "blue": "#1D4ED8", "green": "#15803D",
        "family": "cool", "_severity": "calm",
    },
    "executive_summary": {
        "bg": "#FDFAF5", "card": "#FFFFFF", "border": "#E8D5B0",
        "text": "#1A1205", "muted": "#8A6C3A",
        "red": "#C05621", "amber": "#B7791F", "blue": "#2B6CB0", "green": "#276749",
        "family": "warm", "_severity": "warning",
    },
    "informational": {
        "bg": "#F8FAFC", "card": "#FFFFFF", "border": "#E2E8F0",
        "text": "#0F172A", "muted": "#64748B",
        "red": "#DC2626", "amber": "#D97706", "blue": "#2563EB", "green": "#16A34A",
        "family": "cool", "_severity": "balanced",
    },
}

_STYLE_NOTEBOOKLM = {
    "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
    "text": "#1C1A17", "muted": "#6B6455",
    "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
    "family": "warm", "_severity": "balanced",
}
_STYLE_MODERN = {
    "bg": "#F8F9FA", "card": "#FFFFFF", "border": "#DEE2E6",
    "text": "#212529", "muted": "#6C757D",
    "red": "#DC3545", "amber": "#FD7E14", "blue": "#0D6EFD", "green": "#198754",
    "family": "cool", "_severity": "balanced",
}
_STYLE_DARK = {
    "bg": "#0D1117", "card": "#161B22", "border": "#30363D",
    "text": "#F0F6FC", "muted": "#8B949E",
    "red": "#F85149", "amber": "#E3B341", "blue": "#58A6FF", "green": "#3FB950",
    "family": "dark", "_severity": "critical",
}


def _get_style(plan: dict) -> dict:
    vs   = getattr(config, 'VISUAL_STYLE', 'auto')
    seed = plan.get('_design_seed', getattr(config, 'DESIGN_SEED', 5000))

    if vs == 'notebooklm': return _STYLE_NOTEBOOKLM.copy()
    if vs == 'modern':     return _STYLE_MODERN.copy()
    if vs == 'dark':       return _STYLE_DARK.copy()

    tone    = plan.get('_analysis', {}).get('tone', 'informational')
    palette = _PALETTES.get(tone, _PALETTES['informational']).copy()

    # Minor seed-based accent shift for variety
    if seed > 7000:
        palette['red']  = _shift_color(palette['red'],  -15)
        palette['blue'] = _shift_color(palette['blue'], -15)
    elif seed < 2500:
        palette['amber'] = _shift_color(palette['amber'], +20)

    return palette


def _shift_color(hex_color: str, delta: int) -> str:
    try:
        h = hex_color.lstrip('#')
        r, g, b = [int(h[i:i+2], 16) for i in (0, 2, 4)]
        r = max(0, min(255, r + delta))
        g = max(0, min(255, g + delta))
        b = max(0, min(255, b + delta))
        return f'#{r:02x}{g:02x}{b:02x}'
    except Exception:
        return hex_color


# ══════════════════════════════════════════════════════════════════
#  CHART.JS PADDING FIX
#  Add layout.padding to every Chart.js config to prevent axis labels
#  from being clipped by the canvas boundary (causes numbers cut off at bottom)
# ══════════════════════════════════════════════════════════════════

def _fix_chartjs_padding(html_text: str) -> str:
    """
    Inject layout.padding into Chart.js options if not already present.
    This prevents axis tick labels from being clipped at canvas edges.
    """
    # Find all Chart.js new Chart() calls and inject padding if missing
    def inject_padding(m: re.Match) -> str:
        block = m.group(0)
        if 'layout' in block and 'padding' in block:
            return block  # Already has padding
        # Inject after 'options: {' or before closing of options
        return block.replace(
            'animation: {duration: 0}',
            'animation: {duration: 0}, layout: {padding: {bottom: 24, left: 8, right: 24, top: 8}}'
        )
    # Apply to script blocks containing Chart.js
    result = re.sub(
        r'new Chart\([^;]+\);',
        inject_padding,
        html_text,
        flags=re.DOTALL,
    )
    return result


# ══════════════════════════════════════════════════════════════════
#  ICON LIST BUILDER
#  Topic-specific brand icons come FIRST in the list so the LLM
#  naturally picks kubernetes/docker/aws before generic server/network.
# ══════════════════════════════════════════════════════════════════

def _build_icon_list_for_slide(slide: dict, plan: dict = None) -> str:
    analysis = (plan or {}).get('_analysis', {})
    context  = " ".join([
        analysis.get('subject', ''),
        analysis.get('content_type', ''),
        " ".join(analysis.get('key_entities', [])[:10]),
        slide.get('title', ''),
        slide.get('story_angle', ''),
        slide.get('visual_description', ''),
    ])

    topic_icons = suggest_icons_for_topic(context)
    brand_icons = sorted(BRAND_ICONS.keys())
    generic     = sorted(ICON_PATHS.keys())

    seen   = set()
    result = []
    for name in (topic_icons + brand_icons + generic):
        if name not in seen:
            seen.add(name)
            result.append(name)

    return ", ".join(result[:80])


# ══════════════════════════════════════════════════════════════════
#  DESIGNER PROMPT
# ══════════════════════════════════════════════════════════════════

DESIGNER_PROMPT = """⚠ OUTPUT FORMAT — READ FIRST:
Output ONLY raw HTML. No JSON. No markdown. No ```html. No \\n escapes.
Start directly with: <div class="h-full w-full" ...>
End with closing </div> and any <script> tags.

You are an expert Frontend Developer building one 1280×720px slide for a NotebookLM-quality PDF.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SLIDE SPEC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Slot:           {slot}
  Title:          {title}
  Subtitle:       {subtitle}
  Story angle:    {story_angle}
  Key insight:    {key_insight}
  Visual type:    {visual_type}
  Visual desc:    {visual_description}
  Color mood:     {color_mood}
  Accent:         {accent_color}
  Design seed:    {design_seed}

SLIDE DATA (use EXACT values — never substitute):
{slide_data}

PREVIOUS CRITIC FEEDBACK (fix these):
{feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PALETTE (use these exact hex values via Tailwind arbitrary syntax)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  bg={bg}  card={card}  text={text}  muted={muted}
  border={border}  red={red}  amber={amber}  blue={blue}  green={green}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ICON SYSTEM — CRITICAL — READ CAREFULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⛔ ABSOLUTE BAN: NEVER write <svg> tags yourself. NEVER draw icons from memory.
   The Kubernetes logo, Docker logo, or any other icon you know will look WRONG
   if you attempt to draw it. Use ONLY the placeholder system below.

⛔ ABSOLUTE BAN: NEVER use <i data-lucide="..."> or any CDN icon library.

✅ THE ONLY CORRECT WAY to add any icon:
   [[icon:NAME:SIZE:COLOR]]

   Python replaces this placeholder with the correct professionally-drawn SVG.
   This is the ONLY way icons render correctly in the PDF.

Examples:
  [[icon:kubernetes:64:{blue}]]        ← real Kubernetes wheel (not a blob)
  [[icon:docker:48:{red}]]             ← real Docker whale
  [[icon:server:32:{muted}]]           ← generic server icon
  [[icon:alert-triangle:24:{amber}]]   ← warning icon

Syntax: [[icon:NAME:SIZE:COLOR]]
  NAME  = one of the names in AVAILABLE ICONS below (exact spelling)
  SIZE  = integer pixels: 16 24 32 40 48 56 64 80 96
  COLOR = exact hex like {blue} or {red}

AVAILABLE ICONS (topic-specific ones listed FIRST — prefer these):
{icon_list}

Use [[icon:]] placeholders everywhere: every card header, every section title, every stat.
Minimum 5 icons per slide. At least one large (64px+) in the hero area.
If you write <svg> yourself, it will look like a random blob. Use [[icon:]] instead.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TAILWIND CSS (CDN runtime — all classes work)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use Tailwind for layout, spacing, typography:
  bg-[{card}]  text-[{text}]  border-[{border}]  text-[{muted}]
  h-[380px]  w-[45%]  border-l-4 border-[{red}]
  font-bold font-black font-mono text-8xl rounded-xl shadow-lg p-6

Typography scale:
  Hero numbers: text-8xl or text-9xl font-black in accent color
  Slide title:  text-4xl–text-5xl font-bold
  Subtitles:    text-lg–text-2xl font-medium
  Body:         text-sm–text-base leading-relaxed
  Mono labels:  font-mono text-xs (for hostnames, IDs, versions, paths)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CHART.JS (animation already disabled globally)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use ONLY for true numeric data plots (bar, line, area, doughnut).
NOT for metaphors, flows, or diagrams — use CSS/Tailwind for those.

Rules:
  1. Canvas wrapper: <div style="height:320px;position:relative;">
  2. Canvas ID: chart_{slot}  (must be unique per slide)
  3. Options: responsive:true, maintainAspectRatio:false, animation:{{duration:0}}
  4. ALL <script> tags go at the VERY END of your output
  5. After chart init: window.__chartsReady = (window.__chartsReady||0) + 1;
  6. Use hex colors directly — no CSS vars inside Chart.js config

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚠ STRICT HEIGHT BUDGET — 720px TOTAL — NEVER OVERFLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The slide is EXACTLY 1280×720px with overflow:hidden. Content that goes
below 720px is INVISIBLY CLIPPED — it will not show in the PDF.

ALWAYS use this layout pattern as the outer wrapper:
  <div class="h-full w-full flex flex-col" style="background:{bg}; max-height:720px; overflow:hidden;">

HEIGHT BUDGET — every pixel of vertical space must add up to ≤ 720px:
  • Outer padding top+bottom: 40-48px each (use pt-10 pb-10 = 80px)
  • Title block (title + subtitle): ~90px
  • Main visual area: 720 - 80padding - 90title - 60footer = ~490px MAX
  • Bottom insight/footer strip: ≤ 60px

RULES TO PREVENT OVERFLOW:
  1. Use flex-1 min-h-0 on the main visual area so it flexibly fills remaining space
  2. NEVER stack: title + subtitle + large content + insight box + padding without measuring
  3. For bottom insight strips: keep them max 60px tall (py-3 max, single line text)
  4. Cards in a grid: use gap-4 not gap-6, and limit card padding to p-4 not p-8
  5. Cover slides: preview cards at bottom must use fixed h-[140px] max and pb-6 (not pb-12)
  6. If a visual type has title + 4 cards + insight box: reduce card padding to p-3
  7. NEVER use py-12 or p-12 inside the slide — maximum outer padding is p-10

SAFE VERTICAL STACKING PATTERN:
  <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}">
    <!-- Header: fixed height ~80px -->
    <div class="px-10 pt-8 pb-2 flex-shrink-0"> title + subtitle </div>
    <!-- Main: fills remaining space, flex-1 prevents overflow -->  
    <div class="flex-1 min-h-0 px-10 pb-4 overflow-hidden"> main visual </div>
    <!-- Footer: fixed height max 56px -->
    <div class="px-10 pb-4 flex-shrink-0"> insight strip </div>
  </div>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  NOTEBOOKLM VISUAL STYLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Cards: rounded-xl shadow-md, p-5–p-8, border-l-4 accent
• Hero stat: text-8xl font-black in accent color as focal point
• Backgrounds: subtle pattern or gradient OK (CSS only, no img URLs)
• Design seed {design_seed}: >6000=bold/asymmetric, <3000=refined/symmetric
• NO raw markdown (**bold** → use <strong>)
• NO placeholder text — all content from slide data
• NO JSON or dict text visible on any slide

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ★ CONTENT DENSITY — CRITICAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Slides MUST be information-rich, NOT just decorative boxes.
- Every card, row, or bullet MUST include a DESCRIPTION of 2-3 FULL SENTENCES rendered as
  visible <p> or <span> text. One-word labels or single-stat cards are NOT acceptable.
- Render ALL items from SLIDE DATA — do NOT skip or summarize. If data has 5 items, show 5 items.
- Each item should show: icon + bold title + metric/stat + multi-sentence description paragraph.
- Use text-xs leading-relaxed for descriptions so they fit without overflow.
- NEVER leave a card with just a title and number — always add a description line.
- Body text should convey insight, not just label the metric. Example:
  BAD:  "CPU: 94%"
  GOOD: "CPU: 94% — Application server sustained 94% utilisation for 47 minutes,
        triggering thread pool exhaustion and 1,847 queued requests."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VISUAL TYPE GUIDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cover_hero:
  Full-bleed cover. CSS geometric bg (repeating-linear-gradient or radial-gradient).
  CRITICAL: Use this EXACT structure to prevent bottom card clipping:
  <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}; background-image:...">
    <!-- Top: logo badge + title block — ~200px -->
    <div class="px-12 pt-8 flex-shrink-0">
      small badge pill (audience/version) + giant title text-5xl–text-6xl + subtitle text-xl
    </div>
    <!-- Middle: decorative element — flex-1 fills remaining -->
    <div class="flex-1 min-h-0 flex items-center justify-center px-12">
      optional large [[icon:NAME:96:COLOR]] or CSS decoration
    </div>
    <!-- Bottom: 3 preview cards — FIXED height, NO overflow -->
    <div class="px-10 pb-6 flex-shrink-0 grid grid-cols-3 gap-4" style="height:160px">
      3 cards each: [[icon:NAME:36:COLOR]] + bold title text-base + 1-line desc text-sm
      Cards: rounded-xl bg-[{card}]/20 backdrop-blur p-4 border border-white/10
    </div>
  </div>
  The bottom cards MUST use flex-shrink-0 + fixed height so they never get clipped.

big_number_hero:
  Left 55%: giant number text-[140px] or text-9xl font-black in accent.
  Label text-2xl below. 2-3 supporting stat badges. Context sentence text-lg.
  Right 45%: large [[icon:NAME:96:COLOR]] centered. Optional mini doughnut chart.

stat_cards_row:
  Title row with [[icon:NAME:32:COLOR]] right side.
  4-card grid: each card has [[icon:NAME:40:COLOR]] top-right, big number text-4xl,
  label, sub-label, colored top border (border-t-4).
  ★ BELOW each number: a text-xs description paragraph (2-3 sentences) explaining what
  the metric means and why it matters. Cards must NOT be just a number and label.

bar_chart_annotated:
  Left 40%: headline + 3-4 key bullets each with [[icon:NAME:20:COLOR]] + bold title +
  metric badge + text-xs description sentence explaining the bullet.
  Right 60%: Chart.js bar chart. Below: 2 insight callout boxes (border-l-4) with full-sentence text.

area_chart_gradient:
  Title + 3 stat pills top. Full-width Chart.js area/line with gradient fill.
  Real timestamps on x-axis. Annotation at peak value.

timeline_events:
  Horizontal timeline: dots on a line, each event has [[icon:NAME:24:COLOR]],
  date label, short description. Color dots by event type/severity.

topology_map:
  Title + legend. CSS grid of node cards (no SVG arrows needed).
  Each card: [[icon:NAME:32:COLOR]] + node name in font-mono + status badge pill.
  Group cards into labeled zones with subtle bg color.

matrix_table:
  Dark header row. Alternating row backgrounds. First column bold with [[icon:NAME:20:COLOR]].
  Colored badge cells. Uppercase tracking-widest column headers.

domino_chain:
  Horizontal: 4-6 cards with chevron-right between them.
  Each card: colored top border, [[icon:NAME:32:COLOR]], bold title, 2-line body.
  Summary strip below spanning full width.

comparison_panel:
  Two equal panels side by side. Each: colored header + [[icon:NAME:40:COLOR]] + label.
  Content inside: Chart.js mini bar OR 3-4 stat rows.

priority_table:
  Styled HTML table. Columns: Item | Priority | Action.
  First col: [[icon:NAME:20:COLOR]] + bold name. Priority: colored pill.
  Alternating row backgrounds.

scatter_quadrant:
  2×2 CSS grid (Impact/Effort, Risk/Value axes).
  Each quadrant: colored bg-opacity-10, label top-left, item pills inside.
  Axis labels on edges. Center point.

risk_impact_matrix:
  ★ THE MOST IMPORTANT SLIDE FOR ALERTS/LOGS — render with maximum quality.

  EXACT LAYOUT (must follow precisely):
  <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}">
    <!-- Header: ~72px -->
    <div class="px-10 pt-6 pb-2 flex-shrink-0 flex items-center gap-3">
      [[icon:alert-triangle:28:{red}]]
      <div>
        <h2 class="text-3xl font-black text-[{text}]">slide title</h2>
        <p class="text-sm text-[{muted}]">subtitle</p>
      </div>
    </div>
    <!-- Body: flex-1 min-h-0 -->
    <div class="flex-1 min-h-0 flex gap-4 px-10 pb-2">
      <!-- LEFT: 2×2 Quadrant Grid (63% width) -->
      <div class="flex flex-col gap-0" style="width:63%; min-height:0">
        <!-- Axis label row -->
        <div class="flex justify-end mb-1 flex-shrink-0">
          <span class="text-[10px] font-mono text-[{red}] tracking-widest uppercase mr-2">HIGH IMPACT →</span>
        </div>
        <div class="flex gap-0 flex-1 min-h-0">
          <!-- Y-axis label -->
          <div class="flex items-center flex-shrink-0 mr-1">
            <span class="text-[10px] font-mono text-[{muted}] tracking-widest" style="writing-mode:vertical-lr;transform:rotate(180deg)">↑ HIGH EFFORT</span>
          </div>
          <!-- 4 quadrants as 2×2 grid -->
          <div class="flex-1 min-h-0 grid grid-cols-2 grid-rows-2 gap-1">
            <!-- Q1: LOW impact / LOW effort (top-left) -->
            <div class="rounded-lg border border-[{border}] p-3 flex flex-col" style="background:rgba(255,255,255,0.03)">
              <span class="text-[9px] font-mono text-[{muted}] tracking-widest mb-2 flex-shrink-0">LOW IMPACT / LOW EFFORT</span>
              <!-- items loop: each item = -->
              <div class="flex items-center gap-2 mb-1">
                [[icon:icon-name:20:{muted}]]
                <div>
                  <div class="text-xs font-semibold text-[{muted}]">Item Name</div>
                  <div class="text-[10px] text-[{muted}] font-mono">stat value</div>
                </div>
              </div>
            </div>
            <!-- Q2: HIGH impact / LOW effort (top-right) — RED ACCENT = DO FIRST -->
            <div class="rounded-lg border border-[{red}]/40 p-3 flex flex-col" style="background:rgba(192,57,43,0.08)">
              <span class="text-[9px] font-mono tracking-widest mb-2 flex-shrink-0" style="color:{red}">HIGH IMPACT / LOW EFFORT ★</span>
              <!-- items: use red accent -->
              <div class="flex items-center gap-2 mb-1">
                [[icon:icon-name:20:{red}]]
                <div>
                  <div class="text-xs font-bold text-[{text}]">Item Name</div>
                  <div class="text-[10px] font-mono" style="color:{red}">stat value</div>
                </div>
                <span class="ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded" style="background:{red};color:white">DO FIRST</span>
              </div>
            </div>
            <!-- Q3: LOW impact / HIGH effort (bottom-left) — DEPRIORITIZE -->
            <div class="rounded-lg border border-[{border}] p-3 flex flex-col" style="background:rgba(255,255,255,0.02)">
              <span class="text-[9px] font-mono text-[{muted}] tracking-widest mb-2 flex-shrink-0">LOW IMPACT / HIGH EFFORT</span>
              <!-- items -->
            </div>
            <!-- Q4: HIGH impact / HIGH effort (bottom-right) — PLAN -->
            <div class="rounded-lg border border-[{amber}]/40 p-3 flex flex-col" style="background:rgba(212,136,14,0.06)">
              <span class="text-[9px] font-mono tracking-widest mb-2 flex-shrink-0" style="color:{amber}">HIGH IMPACT / HIGH EFFORT</span>
              <!-- items: amber accent -->
              <div class="flex items-center gap-2 mb-1">
                [[icon:icon-name:20:{amber}]]
                <div>
                  <div class="text-xs font-bold text-[{text}]">Item Name</div>
                  <div class="text-[10px] font-mono text-[{amber}]">stat value</div>
                </div>
                <span class="ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded" style="background:{amber};color:white">PLAN</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- RIGHT: Insight Panel (37% width) -->
      <div class="flex flex-col gap-3 flex-shrink-0" style="width:37%; min-height:0">
        <!-- Quadrant count summary badges -->
        <div class="grid grid-cols-2 gap-2 flex-shrink-0">
          <div class="rounded-lg p-2 text-center" style="background:rgba(192,57,43,0.12)">
            <div class="text-2xl font-black" style="color:{red}">N</div>
            <div class="text-[9px] font-mono text-[{muted}] tracking-wide">HIGH IMPACT</div>
          </div>
          <div class="rounded-lg p-2 text-center" style="background:rgba(212,136,14,0.10)">
            <div class="text-2xl font-black text-[{amber}]">N</div>
            <div class="text-[9px] font-mono text-[{muted}] tracking-wide">NEEDS PLAN</div>
          </div>
        </div>
        <!-- Strategic Guidance -->
        <div class="rounded-xl p-4 flex-shrink-0" style="background:rgba(255,255,255,0.05);border:1px solid {border}">
          <div class="flex items-center gap-2 mb-2">
            [[icon:target:20:{blue}]]
            <span class="text-sm font-bold text-[{text}]">Strategic Guidance</span>
          </div>
          <p class="text-xs text-[{muted}] leading-relaxed">strategic_guidance text here</p>
        </div>
        <!-- Immediate Action -->
        <div class="rounded-xl p-4 flex-1 min-h-0" style="background:rgba(212,136,14,0.08);border:1px solid rgba(212,136,14,0.3)">
          <div class="flex items-center gap-2 mb-2">
            [[icon:shield-alert:20:{amber}]]
            <span class="text-sm font-bold text-[{text}]">Immediate Action Required</span>
          </div>
          <p class="text-xs text-[{muted}] leading-relaxed">immediate_action text here</p>
        </div>
      </div>
    </div>
    <!-- Footer: ~42px -->
    <div class="px-10 pb-3 flex-shrink-0 flex items-center justify-between border-t border-[{border}]/30">
      <div class="flex items-center gap-4 text-[10px] font-mono">
        <span class="flex items-center gap-1">
          [[icon:activity:12:{green}]]
          <span class="text-[{green}]">System Health: {{system_health}}</span>
        </span>
        <span class="flex items-center gap-1">
          [[icon:clock:12:{muted}]]
          <span class="text-[{muted}]">Last Sync: {{last_sync}}</span>
        </span>
      </div>
      <span class="text-[10px] font-mono text-[{muted}]">Design Seed: {design_seed}</span>
    </div>
  </div>

  RULES for risk_impact_matrix:
  - ALL FOUR quadrants must have at least 1 item — NEVER leave a quadrant empty
  - When SLIDE DATA has enough issues: include 2-4+ items per quadrant (not one lonely row)
  - Each item in data may include optional "detail" (or "description") — render as a second line
  - HIGH IMPACT / LOW EFFORT items: RED border, "DO FIRST" badge, bold text
  - HIGH IMPACT / HIGH EFFORT items: AMBER border, "PLAN" badge
  - LOW quadrant items: muted styling, smaller text, no badge
  - Each item: [[icon:NAME:20:COLOR]] + bold name + font-mono stat (+ detail if present)
  - Right panel shows count of high-impact items as large numbers
  - strategic_guidance: 2-3 sentences specific to THIS data (not generic)
  - immediate_action: ONE specific action with deadline/owner if available
  - system_health color: green=Nominal, amber=Degraded, red=Critical
  - Footer always present with system health + sync time

funnel_diagram:
  CSS trapezoid stages (clip-path:polygon). Each stage narrower than previous.
  Stage label + count/% inside. Right side: stat callouts per stage.

info_cards_grid:
  Title. 2×2 or 3×2 card grid. Each: [[icon:NAME:32:COLOR]] top-left,
  title font-semibold, 2-3 sentence description paragraph (text-xs leading-relaxed).
  Alternating left-border accent colors.
  ★ Each card MUST include a multi-sentence description — not just a title.

concept_diagram:
  3-6 step horizontal flow. Each step: circle/box + [[icon:NAME:32:COLOR]] + number,
  bold title, 2-sentence description. Arrows between steps (CSS or → character styled).

two_column_bullets:
  Left 40%: large [[icon:NAME:64:COLOR]], title, key insight paragraph (2-3 sentences), metric badge.
  Right 60%: 4-6 bullet items each with [[icon:NAME:20:COLOR]] + bold label +
  text-xs description sentence (NOT just a label — explain what it means).

callout_hero:
  Large pull-quote center (text-3xl font-italic). Attribution below.
  3 supporting stats row below. Subtle gradient background.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Start with exactly: <div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}; max-height:720px;">
Generate complete, specific HTML now. Use [[icon:NAME:SIZE:COLOR]] for ALL icons.
Remember: flex-1 min-h-0 on main content, flex-shrink-0 on header/footer.
★ CONTENT DENSITY CHECK: Every card/bullet MUST have a multi-sentence description rendered
  as visible text. Slides with only titles and numbers will be rejected."""


# ══════════════════════════════════════════════════════════════════
#  HTML EXTRACTION — handles all LLM output patterns
# ══════════════════════════════════════════════════════════════════

def _extract_html(raw: str) -> str:
    s = raw.strip()

    # JSON-wrapped {"html": "..."}
    if s.startswith('{') or s.startswith('['):
        try:
            import json as _json
            s_clean = re.sub(r'^```(?:json)?\s*', '', s)
            s_clean = re.sub(r'\s*```$', '', s_clean)
            obj = _json.loads(s_clean)
            if isinstance(obj, list) and obj:
                obj = obj[0]
            for key in ('html', 'content', 'slide', 'result', 'output', 'code'):
                if isinstance(obj, dict) and key in obj:
                    candidate = obj[key]
                    if isinstance(candidate, str) and len(candidate.strip()) > 50:
                        return candidate.replace('\\n', '\n').replace('\\"', '"').strip()
            if '<div' not in s[:3000].lower():
                return ""
        except Exception:
            pass

        # Regex fallback for malformed JSON
        m = re.search(r'"html"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.DOTALL)
        if m:
            candidate = m.group(1).replace('\\n', '\n').replace('\\"', '"')
            if len(candidate.strip()) > 50:
                return candidate.strip()
        if '<div' not in s[:3000].lower():
            return ""

    # Markdown fences
    s = re.sub(r'^```(?:html)?\s*\n?', '', s)
    s = re.sub(r'\n?```\s*$', '', s)

    # Escaped newlines (LLM returned them as literals)
    if s.count('\\n') > 15:
        s = s.replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')

    # Strip outer document wrapper tags
    s = re.sub(r'<!DOCTYPE[^>]+>', '', s, flags=re.I)
    s = re.sub(r'<html[^>]*>|</html>', '', s, flags=re.I)
    s = re.sub(r'<head>.*?</head>', '', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<body[^>]*>|</body>', '', s, flags=re.I)

    return s.strip()


# ══════════════════════════════════════════════════════════════════
#  VALIDATION
# ══════════════════════════════════════════════════════════════════

def _validate(html_text: str, slot: int) -> tuple[bool, str]:
    if not html_text or len(html_text.strip()) < 300:
        return False, f"Too short ({len(html_text)} chars)"

    probe = html_text.strip()[:2500].lower()

    if '<div' not in probe and '<section' not in probe:
        return False, "No <div> or <section> found"
    if html_text.strip().startswith('{"') or html_text.strip().startswith('[{"'):
        return False, "Still JSON-wrapped"
    if '```' in html_text:
        return False, "Contains markdown fences"
    if re.search(r'\*\*[^<]{1,60}\*\*', html_text):
        return False, "Contains raw **markdown**"
    if html_text.count('\\n') > 15:
        return False, "Excessive literal \\n sequences"
    if len(re.sub(r'<[^>]+>', '', html_text).strip()) < 60:
        return False, "No meaningful text content"
    if 'font-awesome' in html_text.lower():
        return False, "Uses Font Awesome (not allowed)"
    if 'data-lucide=' in html_text:
        return False, "Uses Lucide CDN (use [[icon:...]] instead)"
    # Warn if LLM drew raw SVG bypassing our [[icon:]] system
    # We allow our substituted SVGs (they have viewBox) but catch LLM-drawn ones
    # by looking for SVGs with circle/path combos that look like hand-drawn logos
    raw_svg_count = html_text.lower().count('<svg ')
    if raw_svg_count > 15:
        # More than 15 raw SVGs = LLM drew its own icons, which look like blobs
        return False, f"LLM drew {raw_svg_count} raw SVGs instead of using [[icon:]] placeholders"
    return True, "ok"


# ══════════════════════════════════════════════════════════════════
#  CANVAS HEIGHT SAFETY PASS
# ══════════════════════════════════════════════════════════════════

def _ensure_canvas_heights(html_text: str) -> str:
    lines  = html_text.split('\n')
    result = []
    for line in lines:
        if '<canvas ' in line and 'id="chart_' in line:
            prev = ' '.join(result[-3:]).lower()
            if 'height' not in prev and 'h-[' not in prev:
                result.append('<div style="position:relative;height:320px">')
                result.append(line)
                result.append('</div>')
                continue
        result.append(line)
    return '\n'.join(result)


# ══════════════════════════════════════════════════════════════════
#  FALLBACK SLIDE — clean HTML, never shows raw dicts/JSON
# ══════════════════════════════════════════════════════════════════

def _safe_str(v) -> str:
    if v is None:             return ""
    if isinstance(v, bool):   return "Yes" if v else "No"
    if isinstance(v, (int, float)): return str(v)
    if isinstance(v, str):    return v[:200]
    if isinstance(v, list):
        if not v: return "—"
        if all(isinstance(x, dict) for x in v):
            parts = [str(x.get('title') or x.get('label') or x.get('fact') or '')[:60]
                     for x in v[:5]]
            return " · ".join(p for p in parts if p) or "—"
        return ", ".join(str(x)[:40] for x in v[:10])
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_safe_str(vv)}" for k, vv in list(v.items())[:5])
    return str(v)[:200]


def _fallback_slide(slide: dict, style: dict, plan: dict = None) -> str:
    title   = html_lib.escape(slide.get('title', 'Slide'))
    insight = html_lib.escape(slide.get('key_insight', ''))
    data    = slide.get('data', {})
    bg      = style.get('bg',     '#F5F0E8')
    card    = style.get('card',   '#FFFFFF')
    text_c  = style.get('text',   '#1A1A1A')
    muted   = style.get('muted',  '#666666')
    border  = style.get('border', '#D0CEC8')
    blue    = style.get('blue',   '#2471A3')

    # Use Python-rendered icon — guaranteed to show
    info_icon = icon('info', 32, blue)

    rows = "".join(
        f'<tr>'
        f'<td style="padding:9px 14px;color:{muted};font-size:12px;'
        f'border-bottom:1px solid {border}">'
        f'{html_lib.escape(str(k).replace("_"," ").title())}</td>'
        f'<td style="padding:9px 14px;font-weight:600;color:{text_c};'
        f'border-bottom:1px solid {border}">'
        f'{html_lib.escape(_safe_str(v))}</td>'
        f'</tr>'
        for k, v in list(data.items())[:8]
        if not str(k).startswith('_')
    )
    subtitle = (plan or {}).get('report_subtitle', 'Report')[:40]

    return f"""<div class="h-full w-full" style="background:{bg}">
<div style="padding:48px 64px;height:100%;box-sizing:border-box;
            display:flex;flex-direction:column;justify-content:center;">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">
    {info_icon}
    <span style="font-size:10px;font-family:monospace;color:{blue};
                 letter-spacing:3px;text-transform:uppercase">
      {html_lib.escape(subtitle)}
    </span>
  </div>
  <h2 style="font-size:38px;font-weight:900;color:{text_c};
             margin:0 0 10px;line-height:1.2">{title}</h2>
  <p style="font-size:16px;color:{muted};margin:0 0 22px;
            max-width:700px;line-height:1.6">{insight}</p>
  <div style="background:{card};border:1px solid {border};
              border-radius:10px;overflow:hidden;max-width:800px">
    <table style="width:100%;border-collapse:collapse">{rows}</table>
  </div>
</div>
</div>"""


# ══════════════════════════════════════════════════════════════════
#  SINGLE SLIDE GENERATOR
# ══════════════════════════════════════════════════════════════════

def _render_risk_impact_matrix(slide: dict, style: dict, plan: dict = None) -> str:
    """
    Python-side guaranteed renderer for risk_impact_matrix slides.
    Called when:
      a) The LLM produces invalid HTML for this slide type, OR
      b) visual_type == "risk_impact_matrix" and we want extra reliability.
    Reads structured data from slide["data"] and builds HTML directly.
    The output is always correct — no LLM involvement.
    """
    from utils.icons import icon as render_icon, substitute_icon_placeholders
    import html as _html

    data      = slide.get('data', {})
    title     = slide.get('title', 'Risk vs. Impact Analysis')
    subtitle  = slide.get('subtitle', 'Prioritizing remediation efforts')

    bg     = style.get('bg',     '#0D1117')
    card   = style.get('card',   '#161B22')
    text   = style.get('text',   '#F0F6FC')
    muted  = style.get('muted',  '#8B949E')
    border = style.get('border', '#30363D')
    red    = style.get('red',    '#EF4444')
    amber  = style.get('amber',  '#F59E0B')
    blue   = style.get('blue',   '#60A5FA')
    green  = style.get('green',  '#3FB950')

    def safe(v): return _html.escape(str(v)) if v else ""

    max_per_q = int(getattr(config, "RISK_MATRIX_QUADRANT_MAX_ITEMS", 6))

    # ── Parse quadrant items ──────────────────────────────────────
    def render_items(items: list, accent: str, badge_text: str = "") -> str:
        if not items:
            return f'<p class="text-[10px] text-[{muted}] italic">No items in this quadrant</p>'
        out = ""
        for j, item in enumerate(items[:max_per_q]):
            name = safe(item.get('name', ''))
            stat = safe(item.get('stat', ''))
            detail_raw = item.get('detail') or item.get('description') or ''
            detail = safe(detail_raw)
            detail_html = ""
            if detail:
                detail_html = (
                    f'<div style="font-size:8px;color:{muted};line-height:1.3;margin-top:2px;'
                    f'word-break:break-word;max-height:2.6em;overflow:hidden">{detail}</div>'
                )
            ic_name = item.get('icon', 'alert-circle')
            ic_svg = render_icon(ic_name, 16, accent)
            # One badge per quadrant (first row) — avoids repeating "NOW" on every item
            show_badge = bool(badge_text) and j == 0
            badge = (
                f'<div style="flex-shrink:0;align-self:flex-start">'
                f'<span style="background:{accent};color:white;font-size:7px;'
                f'font-weight:700;padding:1px 4px;border-radius:3px;white-space:nowrap">'
                f'{badge_text}</span></div>'
                if show_badge else ""
            )
            out += f'''
              <div style="display:flex;align-items:flex-start;gap:5px;margin-bottom:4px;min-width:0">
                <div style="flex-shrink:0;margin-top:1px">{ic_svg}</div>
                <div style="min-width:0;flex:1">
                  <div style="font-size:10px;font-weight:700;color:{text};line-height:1.2;
                              word-break:break-word">{name}</div>
                  <div style="font-size:8px;font-family:monospace;color:{accent};margin-top:1px">{stat}</div>
                  {detail_html}
                </div>
                {badge}
              </div>'''
        return out

    hi_lo = data.get('high_impact_low_effort', [])
    hi_hi = data.get('high_impact_high_effort', [])
    lo_lo = data.get('low_impact_low_effort', [])
    lo_hi = data.get('low_impact_high_effort', [])

    guidance       = safe(data.get('strategic_guidance', 'Focus on high-impact items first.'))
    immediate      = safe(data.get('immediate_action', 'Review critical items immediately.'))
    sys_health     = safe(data.get('system_health', 'Nominal'))
    last_sync      = safe(data.get('last_sync', 'N/A'))
    seed           = plan.get('_design_seed', '') if plan else ''

    health_color = red if sys_health == 'Critical' else (amber if sys_health == 'Degraded' else green)
    hi_count = len(hi_lo) + len(hi_hi)
    plan_count = len(hi_hi)

    alert_icon   = render_icon('alert-triangle', 26, red)
    target_icon  = render_icon('target', 18, blue)
    shield_icon  = render_icon('shield-alert', 18, amber)
    activity_icon = render_icon('activity', 11, health_color)
    clock_icon   = render_icon('clock', 11, muted)

    return f'''<div class="h-full w-full flex flex-col overflow-hidden" style="background:{bg}">

  <!-- HEADER ~68px -->
  <div style="padding:18px 36px 8px;flex-shrink:0;display:flex;align-items:flex-start;gap:12px">
    {alert_icon}
    <div>
      <h2 style="font-size:28px;font-weight:900;color:{text};margin:0;line-height:1.2">{safe(title)}</h2>
      <p style="font-size:13px;color:{muted};margin:3px 0 0;font-weight:400">{safe(subtitle)}</p>
    </div>
  </div>

  <!-- BODY flex-1 -->
  <div style="flex:1;min-height:0;display:flex;gap:14px;padding:0 36px 8px">

    <!-- LEFT: 2×2 Quadrant Grid (62%) -->
    <div style="width:62%;min-height:0;display:flex;flex-direction:column;gap:0">
      <!-- Axis top label -->
      <div style="display:flex;justify-flex-end;margin-bottom:4px;flex-shrink:0">
        <span style="font-size:9px;font-family:monospace;color:{red};letter-spacing:2px;
                     text-transform:uppercase;margin-left:auto;padding-right:2px">HIGH IMPACT →</span>
      </div>
      <div style="flex:1;min-height:0;display:flex;gap:4px">
        <!-- Y-axis label -->
        <div style="display:flex;align-items:center;flex-shrink:0;margin-right:2px">
          <span style="font-size:9px;font-family:monospace;color:{muted};letter-spacing:2px;
                       writing-mode:vertical-lr;transform:rotate(180deg)">↑ HIGH EFFORT</span>
        </div>
        <!-- 2×2 grid -->
        <div style="flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;
                    grid-template-rows:1fr 1fr;gap:6px">

          <!-- Q1: LOW / LOW (top-left) -->
          <div style="border-radius:10px;border:1px solid {border};padding:10px 12px;
                      background:rgba(255,255,255,0.025);overflow:hidden;display:flex;flex-direction:column">
            <span style="font-size:8px;font-family:monospace;color:{muted};letter-spacing:1.5px;
                         text-transform:uppercase;flex-shrink:0;margin-bottom:8px">Low Impact / Low Effort</span>
            {render_items(lo_lo, muted, "")}
          </div>

          <!-- Q2: HIGH / LOW (top-right) — PRIMARY PRIORITY -->
          <div style="border-radius:10px;border:1px solid rgba(239,68,68,0.5);padding:10px 12px;
                      background:rgba(239,68,68,0.08);overflow:hidden;display:flex;flex-direction:column">
            <div style="display:flex;align-items:center;justify-content:space-between;
                        flex-shrink:0;margin-bottom:8px">
              <span style="font-size:8px;font-family:monospace;color:{red};letter-spacing:1.5px;
                           text-transform:uppercase">High Impact / Low Effort</span>
              <span style="font-size:8px;font-weight:900;color:{red};background:rgba(239,68,68,0.15);
                           padding:1px 6px;border-radius:3px">★ DO FIRST</span>
            </div>
            {render_items(hi_lo, red, "NOW")}
          </div>

          <!-- Q3: LOW / HIGH (bottom-left) — DEPRIORITIZE -->
          <div style="border-radius:10px;border:1px solid {border};padding:10px 12px;
                      background:rgba(255,255,255,0.02);overflow:hidden;display:flex;flex-direction:column">
            <span style="font-size:8px;font-family:monospace;color:{muted};letter-spacing:1.5px;
                         text-transform:uppercase;flex-shrink:0;margin-bottom:8px">Low Impact / High Effort</span>
            {render_items(lo_hi, muted, "")}
          </div>

          <!-- Q4: HIGH / HIGH (bottom-right) — PLAN -->
          <div style="border-radius:10px;border:1px solid rgba(245,158,11,0.45);padding:10px 12px;
                      background:rgba(245,158,11,0.07);overflow:hidden;display:flex;flex-direction:column">
            <div style="display:flex;align-items:center;justify-content:space-between;
                        flex-shrink:0;margin-bottom:8px">
              <span style="font-size:8px;font-family:monospace;color:{amber};letter-spacing:1.5px;
                           text-transform:uppercase">High Impact / High Effort</span>
              <span style="font-size:8px;font-weight:900;color:{amber};background:rgba(245,158,11,0.15);
                           padding:1px 6px;border-radius:3px">PLAN</span>
            </div>
            {render_items(hi_hi, amber, "")}
          </div>

        </div>
      </div>
    </div>

    <!-- RIGHT: Insight Panel (38%) -->
    <div style="width:38%;min-height:0;display:flex;flex-direction:column;gap:10px;flex-shrink:0">

      <!-- Count summary -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;flex-shrink:0">
        <div style="border-radius:10px;padding:10px;text-align:center;background:rgba(239,68,68,0.1)">
          <div style="font-size:32px;font-weight:900;color:{red};line-height:1">{hi_count}</div>
          <div style="font-size:8px;font-family:monospace;color:{muted};letter-spacing:1px;margin-top:2px">HIGH IMPACT</div>
        </div>
        <div style="border-radius:10px;padding:10px;text-align:center;background:rgba(245,158,11,0.09)">
          <div style="font-size:32px;font-weight:900;color:{amber};line-height:1">{plan_count}</div>
          <div style="font-size:8px;font-family:monospace;color:{muted};letter-spacing:1px;margin-top:2px">NEEDS PLAN</div>
        </div>
      </div>

      <!-- Strategic Guidance -->
      <div style="border-radius:12px;padding:14px;flex-shrink:0;
                  background:rgba(255,255,255,0.04);border:1px solid {border}">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          {target_icon}
          <span style="font-size:12px;font-weight:700;color:{text}">Strategic Guidance</span>
        </div>
        <p style="font-size:11px;color:{muted};line-height:1.55;margin:0">{guidance}</p>
      </div>

      <!-- Immediate Action -->
      <div style="border-radius:12px;padding:14px;flex:1;min-height:0;
                  background:rgba(245,158,11,0.07);border:1px solid rgba(245,158,11,0.3)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          {shield_icon}
          <span style="font-size:12px;font-weight:700;color:{text}">Immediate Action Required</span>
        </div>
        <p style="font-size:11px;color:{muted};line-height:1.55;margin:0">{immediate}</p>
      </div>

    </div>
  </div>

  <!-- FOOTER ~40px -->
  <div style="padding:6px 36px 10px;flex-shrink:0;display:flex;align-items:center;
              justify-content:space-between;border-top:1px solid rgba(255,255,255,0.06)">
    <div style="display:flex;align-items:center;gap:20px;font-size:10px;font-family:monospace">
      <span style="display:flex;align-items:center;gap:4px;color:{health_color}">
        {activity_icon} System Health: {sys_health}
      </span>
      <span style="display:flex;align-items:center;gap:4px;color:{muted}">
        {clock_icon} Last Sync: {last_sync}
      </span>
    </div>
    <span style="font-size:10px;font-family:monospace;color:{muted}">Design Seed: {seed}</span>
  </div>

</div>'''


# ══════════════════════════════════════════════════════════════════
#  SINGLE SLIDE GENERATOR
# ══════════════════════════════════════════════════════════════════

def _generate_slide(slide: dict, style: dict,
                    feedback: str = "", plan: dict = None) -> str:
    """Generate HTML for one slide. Uses Python renderer for risk_impact_matrix."""
    visual_type = slide.get('visual_type', '')

    # risk_impact_matrix: try LLM first (for variety), Python fallback always works
    is_rim = (visual_type == 'risk_impact_matrix')

    slot = slide.get('slot', 0)
    mood = slide.get('color_mood', 'info_blue')
    seed = (plan.get('_design_seed', config.DESIGN_SEED)
            if plan else config.DESIGN_SEED)

    mood_to_accent = {
        "critical_red":  style.get('red',   '#C0392B'),
        "warning_amber": style.get('amber',  '#D4880E'),
        "info_blue":     style.get('blue',   '#2471A3'),
        "success_green": style.get('green',  '#1E8449'),
        "neutral_slate": style.get('muted',  '#4A5568'),
        "deep_purple":   '#6B46C1',
        "teal_focus":    '#0D9488',
    }
    accent = mood_to_accent.get(mood, style.get('blue', '#2471A3'))

    _data_cap = (
        int(getattr(config, "DESIGNER_RISK_MATRIX_DATA_JSON_MAX_CHARS", 12_000))
        if is_rim
        else int(getattr(config, "DESIGNER_SLIDE_DATA_JSON_MAX_CHARS", 2500))
    )
    _slide_json = json.dumps(slide.get('data', {}), indent=2, default=str)
    if len(_slide_json) > _data_cap:
        _slide_json = _slide_json[:_data_cap] + "\n... [truncated]"

    # Build the prompt
    prompt = DESIGNER_PROMPT.format(
        slot               = slot,
        title              = slide.get('title', ''),
        subtitle           = slide.get('subtitle', ''),
        story_angle        = slide.get('story_angle', ''),
        key_insight        = slide.get('key_insight', ''),
        visual_type        = slide.get('visual_type', 'stat_cards_row'),
        visual_description = slide.get('visual_description', ''),
        color_mood         = mood,
        accent_color       = accent,
        design_seed        = seed,
        slide_data         = _slide_json,
        feedback           = feedback or "None — produce your best first attempt.",
        bg                 = style.get('bg',     '#F5F0E8'),
        card               = style.get('card',   '#FFFFFF'),
        text               = style.get('text',   '#1A1A1A'),
        muted              = style.get('muted',  '#666666'),
        border             = style.get('border', '#D0CEC8'),
        red                = style.get('red',    '#C0392B'),
        amber              = style.get('amber',  '#D4880E'),
        blue               = style.get('blue',   '#2471A3'),
        green              = style.get('green',  '#1E8449'),
        icon_list          = _build_icon_list_for_slide(slide, plan),
    )

    for attempt in range(config.SVG_RETRY_LIMIT):
        try:
            # Use higher token limit to prevent truncation
            # Truncation was the main cause of fallback-table renders
            raw = call(prompt, key="designer", max_tokens=16000, json_mode=False)
        except Exception as e:
            print(f"      [attempt {attempt+1}] LLM error: {e}")
            if attempt == config.SVG_RETRY_LIMIT - 1:
                if is_rim:
                    return _render_risk_impact_matrix(slide, style, plan)
                return _fallback_slide(slide, style, plan)
            continue

        html_text = _extract_html(raw)
        ok, reason = _validate(html_text, slot)

        if ok:
            html_text = _ensure_canvas_heights(html_text)
            # Substitute [[icon:NAME:SIZE:COLOR]] → real inline SVG
            html_text = substitute_icon_placeholders(html_text)
            # Add Chart.js layout padding to prevent axis labels being clipped
            html_text = _fix_chartjs_padding(html_text)
            return html_text

        preview = raw[:120].replace('\n', ' ')
        print(f"      [attempt {attempt+1}] Failed: {reason}. Raw: {preview!r}")

        # Progressive retry: increasingly strict prompts
        if attempt == 0:
            prefix = (
                "⚠ CRITICAL CORRECTION: Do NOT wrap output in JSON. "
                "Do NOT write {\"html\": \"...\"}. "
                "Output ONLY raw HTML starting with: "
                "<div class=\"h-full w-full\" style=\"background:{bg}\">\n"
                "Use [[icon:NAME:SIZE:COLOR]] for icons. "
                "No markdown fences. No JSON. Just HTML.\n\n"
            ).format(bg=style.get('bg', '#F5F0E8'))
        else:
            prefix = (
                "FINAL ATTEMPT. Output EXACTLY this pattern:\n"
                f'<div class="h-full w-full" style="background:{style.get("bg","#F5F0E8")}">\n'
                "  <div class=\"p-12 h-full flex flex-col\">\n"
                "    ... your Tailwind content with [[icon:NAME:SIZE:COLOR]] ...\n"
                "  </div>\n"
                "</div>\n"
                "NO JSON. NO MARKDOWN. NO ```html. Just raw HTML.\n\n"
            )
        prompt = prefix + prompt

    print(f"      [slot {slot}] All retries failed — Python fallback")
    # risk_impact_matrix gets the dedicated Python renderer — always correct output
    if is_rim:
        print(f"      [slot {slot}] Using guaranteed Python risk_impact_matrix renderer")
        return _render_risk_impact_matrix(slide, style, plan)
    return _fallback_slide(slide, style, plan)


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(plan: dict,
        feedback: Optional[dict] = None,
        slides_to_redo: Optional[list] = None) -> list[tuple[int, Optional[str]]]:
    """
    Generate HTML for all slides (or only slides_to_redo in patch mode).
    Returns list of (slot, html_content | None).
    """
    style = _get_style(plan)
    seed  = plan.get('_design_seed', config.DESIGN_SEED)
    tone  = plan.get('_analysis', {}).get('tone', 'auto')
    vs    = getattr(config, 'VISUAL_STYLE', 'auto')

    # Show topic icons detected for this content
    analysis     = plan.get('_analysis', {})
    subject_text = (analysis.get('subject', '') + ' ' +
                    ' '.join(analysis.get('key_entities', [])[:8]))
    topic_icons  = suggest_icons_for_topic(subject_text)

    print(f"  [Designer] Style={vs} | Tone={tone} | Seed={seed} | Palette={style.get('family','?')}")
    if topic_icons:
        print(f"  [Designer] Topic icons: {topic_icons[:8]}")

    slides   = plan.get('slides', [])
    total    = len(slides)
    redo_set = set(slides_to_redo) if slides_to_redo else None
    results: list[tuple[int, Optional[str]]] = []

    # Build per-slot feedback map
    slot_feedback: dict[int, str] = {}
    if feedback and feedback.get('slides_to_fix'):
        for sf in feedback['slides_to_fix']:
            s = int(sf.get('slot', 0))
            problem = sf.get('problem', '')
            fix     = sf.get('fix', '')
            hint    = sf.get('prev_content_hint', '')
            slot_feedback[s] = (
                f"PROBLEM: {problem}. "
                f"FIX: {fix}. "
                f"CURRENT CONTENT: {hint}"
            )

    for slide in slides:
        slot = slide.get('slot', 0)
        name = slide.get('title', f'Slide {slot}')[:44]

        if redo_set is not None and slot not in redo_set:
            results.append((slot, None))
            continue

        fb = slot_feedback.get(slot, "")
        print(f"    [{slot:02d}/{total}] {name:<46}", end=" ", flush=True)
        html_out = _generate_slide(slide, style, feedback=fb, plan=plan)
        results.append((slot, html_out))
        print("✓")

    return results