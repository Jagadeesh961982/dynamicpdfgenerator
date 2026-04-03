# agents/designer.py
#
# AGENT 2 — VISUAL DESIGNER
# ══════════════════════════
# Generates a complete HTML snippet per slide using:
#   • Tailwind CSS (CDN play.tailwindcss.com — runtime JIT, no config needed)
#   • Chart.js  (CDN, with animation:false + chart-ready sentinel for Playwright)
#   • Lucide icons (CDN, lightweight SVG icon set, works offline in Playwright)
#
# KEY FIXES vs previous broken approach:
#   1. Uses play.tailwindcss.com (runtime JIT) — all classes work without config
#   2. Chart canvas wrapped in explicit height container (h-[380px] etc.)
#   3. Chart scripts use unique IDs: chart_s{slot}_{uid}
#   4. Lucide icons used instead of Font Awesome (Font Awesome CDN fails in Playwright)
#   5. Script tags extracted to bottom of slide, not inline in card divs
#   6. chart-ready sentinel: window.__chartsReady++ so Playwright can await it
#   7. Fallback: pure CSS/HTML table if chart init fails

import html, json, re, sys, uuid
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call
import config


# ══════════════════════════════════════════════════════════════════
#  SEVERITY → PALETTE
# ══════════════════════════════════════════════════════════════════

def _derive_auto_style(plan: dict) -> dict:
    analysis = plan.get('_analysis', {})
    tone = analysis.get('tone', 'informational')

    PALETTES = {
        "urgent": {
            "bg": "#1A1A1F", "card": "#242430", "border": "#38383F",
            "text": "#F0F0F5", "muted": "#9090A0",
            "red": "#E53E3E", "amber": "#ECC94B", "blue": "#63B3ED", "green": "#68D391",
            "_severity": "critical", "_score": 80,
        },
        "analytical": {
            "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
            "text": "#1C1A17", "muted": "#6B6455",
            "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
            "_severity": "balanced", "_score": 40,
        },
        "educational": {
            "bg": "#F0F4F8", "card": "#FFFFFF", "border": "#CBD5E0",
            "text": "#1A202C", "muted": "#718096",
            "red": "#E53E3E", "amber": "#DD6B20", "blue": "#2B6CB0", "green": "#276749",
            "_severity": "calm", "_score": 10,
        },
        "executive_summary": {
            "bg": "#FDF6EC", "card": "#FFFFFF", "border": "#E8D5B0",
            "text": "#1A1205", "muted": "#8A6C3A",
            "red": "#C05621", "amber": "#B7791F", "blue": "#2B6CB0", "green": "#276749",
            "_severity": "warning", "_score": 50,
        },
        "informational": {
            "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
            "text": "#1C1A17", "muted": "#6B6455",
            "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
            "_severity": "balanced", "_score": 30,
        },
    }
    return PALETTES.get(tone, PALETTES["informational"])


def _get_style(plan: dict) -> dict:
    vs = getattr(config, 'VISUAL_STYLE', 'auto')
    if vs == 'notebooklm':
        return {
            "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
            "text": "#1C1A17", "muted": "#6B6455",
            "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
            "_severity": "balanced", "_score": 0,
        }
    if vs == 'modern':
        return {
            "bg": "#F8F9FA", "card": "#FFFFFF", "border": "#DEE2E6",
            "text": "#212529", "muted": "#6C757D",
            "red": "#DC3545", "amber": "#FD7E14", "blue": "#0D6EFD", "green": "#198754",
            "_severity": "balanced", "_score": 0,
        }
    return _derive_auto_style(plan)


# Keep backward-compat alias
STYLE_CONTEXT = {}
COLOR_MOODS = {
    "critical_red":  "#C0392B",
    "warning_amber": "#D4880E",
    "info_blue":     "#2471A3",
    "neutral":       "#555555",
}


# ══════════════════════════════════════════════════════════════════
#  DESIGNER PROMPT
#  The LLM writes Tailwind + Chart.js + Lucide HTML per slide.
# ══════════════════════════════════════════════════════════════════

DESIGNER_PROMPT = """⚠ OUTPUT FORMAT — READ THIS FIRST:
Output ONLY raw HTML. Do NOT wrap in JSON. Do NOT write {{"html": "..."}}.
Never return JSON slide metadata, slide plan objects, or {{"slide_N": ...}} — only HTML markup.
Do NOT use markdown code fences (no ```html). Do NOT escape newlines as \\n.
Start your response directly with: <div class="h-full w-full" ...>
End your response with the closing </div> and optional <script> tags.

You are an expert Frontend Developer and Data Visualization Engineer.
Generate a COMPLETE, SELF-CONTAINED HTML snippet for ONE 1280x720px presentation slide.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SLIDE SPEC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Slot:               {slot}
  Title:              {title}
  Subtitle:           {subtitle}
  Story angle:        {story_angle}
  Key insight:        {key_insight}
  Visual type:        {visual_type}
  Visual description: {visual_description}
  Suggested accent:   {accent_color}

DATA FOR THIS SLIDE (use EXACT values — never round, never substitute):
{slide_data}

PREVIOUS CRITIC FEEDBACK (fix these specifically):
{feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STYLE CONTEXT (all slides share this palette)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Severity:    {severity}
  Background:  {bg}
  Card bg:     {card}
  Text:        {text}
  Muted:       {muted}
  Border:      {border}
  Red accent:  {red}
  Amber accent:{amber}
  Blue accent: {blue}
  Green accent:{green}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  NOTEBOOKLM / INFOGRAPHIC AESTHETIC (apply on every slide)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Aim for publication-ready, vibrant slides — not plain text + default charts only.
  • Cards: rounded-xl, shadow-lg or shadow-md, bg-[{card}], generous padding (p-5–p-8).
    Use a left accent border-l-4 with border-[{red}], border-[{blue}], or border-[{amber}] by severity.
  • Typography: titles font-bold sans-serif; hostnames, topics, URLs, consumer groups in
    font-mono text-xs or text-sm inside muted rounded boxes (bg-black/5 or border border-[{border}]).
  • Hero metric: when data has one critical number, show it text-5xl–text-8xl font-black in
    text-[{red}] or the slide accent — make it the visual focal point.
  • Icons: at least one LARGE Lucide in the primary visual zone (w-14 h-14 or w-16 h-16);
    every major card/header row includes a Lucide (w-8 h-8+) with explicit text-[{red}] / text-[{blue}] etc.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  YOUR TOOLBOX (Tailwind + Lucide + Chart.js + illustrative SVG/CSS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. TAILWIND CSS (play.tailwindcss.com runtime — all classes available)
   Use Tailwind for EVERYTHING: layout, spacing, typography, colors.
   Use arbitrary values freely: h-[380px], bg-[#C0392B], text-[#1C1A17]
   For the palette colors, use arbitrary value syntax:
     bg-[{card}]  text-[{text}]  border-[{border}]  text-[{muted}]
   Typography helpers: font-serif, font-mono, tracking-widest, uppercase

2. LUCIDE ICONS (via CDN, already loaded in the page)
   Use icons with: <i data-lucide="icon-name" class="w-8 h-8 text-[{red}]"></i>
   Available icons (use the exact kebab-case name):
     Infrastructure / infra: alert-triangle  alert-circle  server  database  cpu  hard-drive
     activity  trending-up  trending-down  zap  cloud  network  layers  timer
     chart / data: bar-chart-2  pie-chart  chart-line  chart-area  chart-bar  gauge
     status: check-circle  x-circle  info  shield  flame  box
     General / editorial: book-open  book  globe  lightbulb  rocket  target  users
     briefcase  graduation-cap  microscope  sparkles  link  link-2-off  unlink
     git-branch  git-merge  workflow  layout-grid  panel-left
   NEVER use Font Awesome. ALWAYS use Lucide.
   Icons render as inline SVG — they look crisp and work in Playwright PDF.

   ILLUSTRATIVE SVG / CSS (not a substitute for Chart.js data plots):
   • Do NOT hand-roll SVG for time-series, bar plots, or line charts — use Chart.js canvas for those.
   • DO use inline SVG, CSS clip-path, or dense div grids for metaphors: funnel silhouettes,
     threshold lines, grids of small squares/tiles suggesting volume, flow connectors.
     These must use palette hex colors and sit in normal flow so PDF capture works.

3. CHART.JS (already loaded, animation:false set globally)
   For line, bar, area, doughnut charts ONLY (true numeric plots — not for metaphor diagrams).
   CRITICAL rules for PDF rendering:
     a. Canvas MUST be inside a div with explicit pixel height: <div style="height:320px; position:relative;">
     b. Canvas ID must be unique: id="chart_{slot}"
     c. Use responsive:true, maintainAspectRatio:false in options
     d. animation: {{duration: 0}} — REQUIRED for PDF
     e. Put the <script> tag AT THE END of your entire HTML output (after all divs)
     f. After creating the chart, do: window.__chartsReady = (window.__chartsReady||0) + 1;
   
   CHART COLORS: Use hex values directly (not CSS variables).
   Example Chart.js init:
   <script>
   (function() {{
     var ctx = document.getElementById('chart_{slot}').getContext('2d');
     new Chart(ctx, {{
       type: 'bar',
       data: {{
         labels: ['Label1','Label2','Label3'],
         datasets: [{{
           label: 'Alert Count',
           data: [50, 127, 165],
           backgroundColor: ['{red}', '{blue}', '{amber}'],
           borderRadius: 4,
         }}]
       }},
       options: {{
         animation: {{duration: 0}},
         responsive: true,
         maintainAspectRatio: false,
         plugins: {{ legend: {{ display: false }} }},
         scales: {{
           y: {{ beginAtZero: true, grid: {{ color: '{border}' }} }},
           x: {{ grid: {{ display: false }} }}
         }}
       }}
     }});
     window.__chartsReady = (window.__chartsReady||0) + 1;
   }})();
   </script>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HARD RULES (never break):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Output ONLY inner HTML. NO <html><head><body> outer tags.
  2. For DATA charts (bars, lines, areas, doughnuts): use Chart.js canvas — never hand-drawn SVG plots.
     For ILLUSTRATIONS (funnels, thresholds, tile grids, decorative shapes): inline SVG or CSS is OK.
  3. NO Font Awesome — use Lucide icons only.
  4. USE EXACT data values from the DATA section.
  5. NO raw markdown — use <span class="font-bold"> not **bold**.
  6. ALL Chart.js <script> tags must go at the very END of your output.
  7. Every chart canvas must be inside a div with explicit pixel height.
  8. Use Tailwind arbitrary values for exact palette colors.
  9. The outer wrapper div must be: <div class="h-full w-full" style="background:{bg}">
 10. EVERY slide MUST include at least 3 Lucide <i data-lucide="..."> icons (visible, accent-colored).
     At least ONE icon must be w-12 h-12 or larger in the primary visual or hero area.
     Every major card or section header must have an icon — never plain text-only blocks.
 11. NEVER output raw JSON, JSON strings, or Python dict reprs as visible slide text.
     Always render data as styled HTML (cards, lists, tables).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VISUAL TYPE GUIDE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cover_hero:
  Full-slide cover. Decorative background (CSS pattern with Tailwind, no SVG needed).
  Large title (text-6xl font-bold font-serif). Date badge (pill). Subtitle.
  Bottom: 3 equal preview cards each with a Lucide icon + label + description.
  If DATA has preview_cards / preview_items with an "icon" hint, map it to a VALID Lucide
  kebab-case name (e.g. broken_link → link-2-off, overflowing_boxes → layers, server_warning → server).
  NEVER print JSON or dict text on the slide — always render as styled cards with <i data-lucide="...">.
  <div class="h-full w-full flex flex-col" style="background:{bg}">

stat_cards_row:
  4 equal stat cards in a grid. Each card: Lucide icon top-right, giant number,
  label, sub-label. Top colored border-l-4. Use real values from data.
  <div class="h-full w-full p-14 flex flex-col gap-6" style="background:{bg}">
    <h2>...</h2>
    <div class="grid grid-cols-4 gap-6 flex-1">...</div>

bar_chart_annotated:
  Prefer a rich infographic when the story is backlog, saturation, flow, or severity — use elevated
  cards, large hero numbers, mono metadata boxes, and Lucide (not only a generic bar).
  Use Chart.js bar chart ONLY when you need a true multi-category numeric comparison.
  Typical split: left (40%): headline + bullets with icons; right (60%): main visual (chart OR
  custom infographic). Below: 1-2 callout boxes with border-l-4 and real values.

area_chart_gradient:
  Full-width Chart.js line chart with fill:true and gradient background.
  Headline + 2-3 bullet points above the chart.
  Real timestamps on x-axis, real values.

flap_chart:
  Top: Chart.js line chart showing metric fluctuating near threshold (explicit threshold line via annotation or a line dataset).
  Middle: 2-3 host cards in a row (hostname + percentage + OS badge).
  Bottom: Insight + Recommendation box with left blue border.

topology_map:
  CSS grid of system cards (no SVG). Each card: Lucide icon + hostname + status badge.
  Status badge colored by severity. Connecting arrows via CSS (border + arrow div).
  Group cards into zones (Storage, Compute, Network, etc.).

matrix_table:
  HTML table with Tailwind classes. Dark header row. Team rows × dimension cols.
  Colored cells with actual impact text. Empty cells light gray text.
  Title + subtitle above table.

domino_chain:
  Horizontal row of cards with Lucide chevron-right arrows between them.
  Each card: colored top border, Lucide icon, bold title, 2-line body.
  Header box above: "These are cascading failures, not isolated events."

comparison_panel:
  Two equal panels. Each: dark colored header with Lucide icon + hostname.
  Chart.js mini chart inside (or Tailwind-based bar visualization for simple data).
  Key stats in monospace below.

priority_table:
  Styled HTML table. Columns: System | Immediate Action | Observability Tuning.
  First col: bold + Lucide icon. Priority dots (colored circles via Tailwind).
  Alternating row backgrounds.

scatter_quadrant:
  4-quadrant layout using CSS grid (2x2). Each quadrant: colored bg, label,
  list of real issues inside. No SVG. Pure Tailwind CSS layout.
  Axis labels as text on the borders.

funnel_diagram:
  NotebookLM-style flow metaphor — NOT a default horizontal bar as the main graphic.
  Pattern: horizontal funnel silhouette (CSS clip-path trapezoids OR inline SVG path) narrowing
  left→right. Fill the wide region with many small tiles (grid of tiny divs with bg-[{blue}]/30–/60,
  overlapping slightly) to suggest message/volume backlog. Add a vertical threshold line
  (border or SVG line) with label e.g. "Alert threshold: N" in mono. Show the headline metric
  above in text-6xl font-black text-[{red}]. Left or below: 2-3 font-mono boxes for Topic,
  Consumer group, Instance from DATA. Bottom: full-width insight strip in a muted card.
  Vertical stack variant: trapezoid layers top-to-bottom with category + count, colored by severity.

big_number_hero:
  Giant number (text-[120px] or text-9xl, font-black). Label below.
  Context sentence. Right side: Lucide icon (large, w-40 h-40) or
  a simple Chart.js doughnut/gauge. Colored by severity.

concept_diagram:
  Explain a workflow, architecture, or idea with CSS layout (flex/grid).
  3-6 steps as connected cards or a horizontal flow. Each step: Lucide icon (w-10 h-10),
  bold title, short body. Use arrows or border connectors between steps.
  No raw SVG for charts — use Lucide + Tailwind only.

info_cards_grid:
  2x2 or 3x2 grid of rounded cards on bg-[{card}]. Each card: Lucide icon top-left,
  title, 2-line description. Alternate subtle border-l-4 or top accent colors.
  Use real labels from the DATA section.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Generate the complete HTML slide content now. Use REAL data. Be specific and visual."""


# ══════════════════════════════════════════════════════════════════
#  VALIDATION
# ══════════════════════════════════════════════════════════════════

def _extract_html_from_response(raw: str) -> str:
    """
    Robustly extract HTML from whatever the LLM returned.
    Handles these cases (all observed in the wild):
      1. Raw HTML (ideal)                        → <div class="h-full...">...</div>
      2. JSON-wrapped: {"html": "<div>...</div>"} → extract the html field
      3. JSON array:   [{"html": "..."}]           → extract first element's html
      4. Markdown fences: ```html\n...\n```        → strip fences
      5. Escaped newlines: \\n inside JSON strings → unescape
      6. JSON with "content"/"slide"/"result" key  → try those fields too
    """
    s = raw.strip()

    # ── Case 2/3/6: JSON response (most common failure mode) ─────
    # The model wraps its HTML in {"html": "..."} or similar
    if s.startswith('{') or s.startswith('['):
        # Try to parse as JSON and extract the HTML value
        try:
            import json as _json
            # Remove outer ``` if present
            s_clean = re.sub(r'^```(?:json)?\s*', '', s)
            s_clean = re.sub(r'\s*```$', '', s_clean)
            obj = _json.loads(s_clean)

            # Unwrap array
            if isinstance(obj, list) and obj:
                obj = obj[0]

            # Try common field names the model uses
            for key in ('html', 'content', 'slide', 'result', 'output', 'code'):
                if isinstance(obj, dict) and key in obj:
                    candidate = obj[key]
                    if isinstance(candidate, str) and len(candidate.strip()) > 50:
                        # Unescape JSON-encoded newlines/tabs
                        candidate = candidate.replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')
                        return candidate.strip()
            # Valid JSON but no HTML field — do not pass slide-plan metadata as HTML
            return ""
        except Exception:
            # Not valid JSON — fall through to string processing
            pass

        # Regex fallback: pull the value from "html": "..." even if JSON is malformed
        m = re.search(r'"html"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]?', s, re.DOTALL)
        if m:
            candidate = m.group(1).replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')
            if len(candidate.strip()) > 50:
                return candidate.strip()

        # Looks like JSON object/array but no extractable HTML — never return raw JSON
        t = s.lstrip()
        if t.startswith(('{', '[')) and '<div' not in s[:3000].lower():
            return ""

    # ── Case 4: Markdown code fences ─────────────────────────────
    s = re.sub(r'^```(?:html)?\s*\n?', '', s)
    s = re.sub(r'\n?```\s*$', '', s)

    # ── Case 5: Literal \n text (not in JSON context) ─────────────
    # If the string has lots of literal \n sequences it was escaped outside JSON
    if s.count('\\n') > 10:
        s = s.replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')

    # ── Cases 1 & rest: Remove outer document wrappers ───────────
    s = re.sub(r'<!DOCTYPE[^>]+>', '', s, flags=re.I)
    s = re.sub(r'<html[^>]*>|</html>', '', s, flags=re.I)
    s = re.sub(r'<head>.*?</head>', '', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<body[^>]*>|</body>', '', s, flags=re.I)

    return s.strip()


def _validate(html: str, slot: int) -> tuple[bool, str]:
    if not html or len(html.strip()) < 300:
        return False, f"Too short ({len(html)} chars)"
    # Detect if extraction failed — still looks like JSON
    stripped = html.strip()
    probe = stripped[:2500].lower()
    # Real slide HTML must contain a div or section near the start (pretty JSON starts with {\n)
    if '<div' not in probe and '<section' not in probe:
        return False, "No <div>/<section> in output — not valid slide HTML"
    if stripped.startswith('{"html"') or stripped.startswith('{ "html"'):
        return False, "Still JSON-wrapped after extraction"
    if stripped.startswith('{"') or stripped.startswith('[{"'):
        return False, "Still JSON object after extraction"
    if '"visual_type"' in html and 'h-full' not in html:
        return False, "Slide metadata JSON instead of HTML"
    if '```' in html:
        return False, "Contains markdown fences"
    if re.search(r'\*\*[^<]{1,60}\*\*', html):
        return False, "Contains raw **markdown**"
    if stripped.lower().startswith('<!doctype') or stripped.lower().startswith('<html'):
        return False, "Contains full document wrapper"
    # Check for literal \n rendering (not actual newlines)
    if html.count('\\n') > 15:
        return False, "Contains excessive literal \\n escape sequences"
    if len(re.sub(r'<[^>]+>', '', html).strip()) < 80:
        return False, "No meaningful text content"
    if 'font-awesome' in html.lower():
        return False, "Uses Font Awesome — use Lucide icons instead"
    return True, "ok"


def _strip_wrapper(html: str) -> str:
    """Alias kept for compatibility — now delegates to _extract_html_from_response."""
    return _extract_html_from_response(html)


def _fix_chart_canvas_heights(html: str) -> str:
    """
    Safety pass: ensure every <canvas> element has a parent with explicit pixel height.
    If a canvas is found without a height-bearing parent, wrap it.
    """
    def ensure_height(m):
        canvas_tag = m.group(0)
        return f'<div style="position:relative;height:320px">{canvas_tag}</div>'

    # Only wrap canvases that are NOT already inside a style="height:..." div
    # Simple heuristic: if canvas tag is preceded by position:relative in parent, skip
    # Otherwise wrap
    lines = html.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '<canvas ' in line and 'id="chart_' in line:
            # Check if previous non-empty line has height
            prev_lines = [l for l in result[-3:] if l.strip()]
            prev = ' '.join(prev_lines).lower()
            if 'height' not in prev and 'h-[' not in prev:
                result.append('<div style="position:relative;height:320px">')
                result.append(line)
                result.append('</div>')
                i += 1
                continue
        result.append(line)
        i += 1
    return '\n'.join(result)


# ══════════════════════════════════════════════════════════════════
#  FALLBACK RENDERER (when LLM fails all retries)
# ══════════════════════════════════════════════════════════════════

def _fallback_format_value(v) -> str:
    """
    Turn slide data values into safe table cell text.
    Never dump Python repr of lists/dicts (causes raw JSON-looking garbage in PDF).
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v[:900]
    if isinstance(v, list):
        if not v:
            return "—"
        if all(isinstance(x, dict) for x in v):
            parts = []
            for item in v[:6]:
                t = item.get("title") or item.get("label") or ""
                d = item.get("description") or item.get("sub") or ""
                line = f"{t}: {d}".strip(": ").strip()
                if line:
                    parts.append(line)
            return " · ".join(parts)[:900] if parts else "—"
        if all(isinstance(x, (str, int, float, bool)) for x in v):
            return ", ".join(str(x) for x in v[:25])[:900]
        return json.dumps(v, default=str)[:400]
    if isinstance(v, dict):
        bits = []
        for kk, vv in list(v.items())[:8]:
            if isinstance(vv, (dict, list)):
                bits.append(f"{kk}: {_fallback_format_value(vv)}")
            else:
                bits.append(f"{kk}: {vv}")
        return "; ".join(bits)[:900]
    return str(v)[:500]


def _fallback_slide(slide: dict, style: dict, plan: dict = None) -> str:
    title   = slide.get('title', 'Slide')
    insight = slide.get('key_insight', '')
    data    = slide.get('data', {})
    bg      = style.get('bg', '#F5F0E8')
    card    = style.get('card', '#FFFFFF')
    text    = style.get('text', '#1A1A1A')
    muted   = style.get('muted', '#666666')
    border  = style.get('border', '#D0CEC8')
    accent  = style.get('blue', '#2471A3')
    report_sub = (plan or {}).get('report_subtitle', 'Generated Report')

    rows = "".join(
        f'<tr><td style="padding:10px 14px;color:{muted};font-size:13px;'
        f'border-bottom:1px solid {border}">{html.escape(str(k).replace("_"," ").title())}</td>'
        f'<td style="padding:10px 14px;font-weight:700;color:{text};'
        f'border-bottom:1px solid {border}">{html.escape(_fallback_format_value(v))}</td></tr>'
        for k, v in list(data.items())[:8]
        if not str(k).startswith('_')
    )
    return f"""<div class="h-full w-full" style="background:{bg}">
<div style="padding:52px 72px;height:100%;box-sizing:border-box;
            display:flex;flex-direction:column;justify-content:center">
  <div style="font-size:11px;font-family:monospace;color:{accent};
              letter-spacing:3px;margin-bottom:16px">{html.escape(report_sub.upper())}</div>
  <h2 style="font-size:40px;font-weight:800;color:{text};margin:0 0 12px;line-height:1.15">
    {html.escape(title)}</h2>
  <p style="font-size:18px;color:{muted};margin:0 0 24px;max-width:720px">{html.escape(insight)}</p>
  <div style="background:{card};border:1px solid {border};border-radius:10px;overflow:hidden;max-width:860px">
    <table style="width:100%;border-collapse:collapse">{rows}</table>
  </div>
</div></div>"""


# ══════════════════════════════════════════════════════════════════
#  GENERATE ONE SLIDE
# ══════════════════════════════════════════════════════════════════

def _generate_slide(slide: dict, style: dict, feedback: str = "", plan: dict = None) -> str:
    slot   = slide.get('slot', 0)
    mood   = slide.get('color_mood', 'neutral')
    accent_map = {
        "critical_red":  style.get('red', '#C0392B'),
        "warning_amber": style.get('amber', '#D4880E'),
        "info_blue":     style.get('blue', '#2471A3'),
        "neutral":       style.get('muted', '#555555'),
        "success_green": style.get('green', '#1E8449'),
    }
    accent = accent_map.get(mood, style.get('blue', '#2471A3'))
    sev    = style.get('_severity', 'balanced')

    prompt = DESIGNER_PROMPT.format(
        slot               = slot,
        title              = slide.get('title', ''),
        subtitle           = slide.get('subtitle', ''),
        story_angle        = slide.get('story_angle', ''),
        key_insight        = slide.get('key_insight', ''),
        visual_type        = slide.get('visual_type', 'stat_cards_row'),
        visual_description = slide.get('visual_description', ''),
        layout_hint        = slide.get('layout_hint', 'left_text_right_visual'),
        accent_color       = accent,
        slide_data         = json.dumps(slide.get('data', {}), indent=2, default=str)[:2000],
        feedback           = feedback or "None",
        severity           = sev,
        bg                 = style.get('bg', '#F5F0E8'),
        card               = style.get('card', '#FFFFFF'),
        text               = style.get('text', '#1A1A1A'),
        muted              = style.get('muted', '#666666'),
        border             = style.get('border', '#D0CEC8'),
        red                = style.get('red', '#C0392B'),
        amber              = style.get('amber', '#D4880E'),
        blue               = style.get('blue', '#2471A3'),
        green              = style.get('green', '#1E8449'),
    )

    for attempt in range(config.SVG_RETRY_LIMIT):
        try:
            # Plain text/HTML — must NOT use API json_mode (see utils.llm.call json_mode=False)
            raw = call(prompt, key="designer", max_tokens=8192)
        except Exception as e:
            print(f"      [attempt {attempt+1}] LLM error: {e}")
            if attempt == config.SVG_RETRY_LIMIT - 1:
                return _fallback_slide(slide, style, plan)
            continue

        # Always run through the robust extractor
        html = _extract_html_from_response(raw)
        ok, reason = _validate(html, slot)
        if ok:
            html = _fix_chart_canvas_heights(html)
            return html

        # Log what we actually got to aid debugging
        preview = raw[:120].replace('\n', ' ')
        print(f"      [attempt {attempt+1}] Failed ({reason}). Raw starts: {preview!r}")

        # Progressive retry prompts — get increasingly strict
        if attempt == 0:
            prefix = (
                "⚠ CRITICAL CORRECTION NEEDED: Do NOT wrap your output in JSON. "
                "Do NOT write {\"html\": \"...\"}. "
                "Output ONLY the raw HTML starting with <div class=\"h-full w-full\">. "
                "No JSON. No markdown. No \\n escape sequences. Just HTML.\n\n"
            )
        else:
            prefix = (
                "FINAL ATTEMPT — ONLY OUTPUT THIS EXACT FORMAT:\n"
                "<div class=\"h-full w-full\" style=\"background:{bg}\">\n"
                "  ... your Tailwind HTML content here ...\n"
                "</div>\n"
                "NO JSON WRAPPER. NO MARKDOWN FENCES. NO \\n ESCAPES. RAW HTML ONLY.\n\n"
            ).format(bg=style.get('bg', '#F5F0E8'))
        prompt = prefix + prompt

    print(f"      [slot {slot}] All retries failed — using Python fallback")
    return _fallback_slide(slide, style, plan)


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(plan: dict,
        feedback: Optional[dict] = None,
        slides_to_redo: Optional[list] = None) -> list:
    """
    Generate HTML for all slides (or only slides_to_redo in patch mode).
    Returns list of (slot, html_content|None) tuples.
    """
    style  = _get_style(plan)
    sev    = style.get('_severity', 'balanced')
    vs     = getattr(config, 'VISUAL_STYLE', 'auto')
    tone   = plan.get('_analysis', {}).get('tone', 'auto')
    print(f"  [Designer] Style: {vs} → tone: {tone}, palette: {sev}")

    slides   = plan.get('slides', [])
    total    = len(slides)
    redo_set = set(slides_to_redo) if slides_to_redo else None
    results  = []

    slot_feedback: dict = {}
    if feedback and feedback.get('slides_to_fix'):
        for sf in feedback['slides_to_fix']:
            s = int(sf.get('slot', 0))
            slot_feedback[s] = f"PROBLEM: {sf.get('problem','')}. FIX: {sf.get('fix','')}"

    for slide in slides:
        slot = slide.get('slot', 0)
        name = slide.get('title', f'Slide {slot}')[:44]

        if redo_set is not None and slot not in redo_set:
            results.append((slot, None))
            continue

        fb = slot_feedback.get(slot, "")
        print(f"    [{slot:02d}/{total}] {name:<46}", end=" ", flush=True)
        html = _generate_slide(slide, style, feedback=fb, plan=plan)
        results.append((slot, html))
        print("✓")

    return results
