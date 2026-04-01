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

import json, re, sys, uuid
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call
import config


# ══════════════════════════════════════════════════════════════════
#  SEVERITY → PALETTE
# ══════════════════════════════════════════════════════════════════

def _derive_auto_style(plan: dict) -> dict:
    parsed   = plan.get('_parsed', {})
    total    = parsed.get('total', 0) or 0
    firing   = parsed.get('firing', 0) or 0
    cpu      = parsed.get('cpu_max', 0) or 0
    kafka    = parsed.get('kafka_max_lag', 0) or 0
    disks    = parsed.get('critical_disk', {})
    max_disk = max(disks.values(), default=0) if isinstance(disks, dict) else 0

    score = 0
    if total > 0 and firing / max(total, 1) > 0.5: score += 30
    if cpu > 100:        score += 25
    elif cpu > 80:       score += 15
    if kafka > 500000:   score += 20
    elif kafka > 100000: score += 10
    if max_disk > 99:    score += 20
    elif max_disk > 90:  score += 10
    if total > 300:      score += 10

    if score >= 65:
        return {
            "bg": "#1A1A1F", "card": "#242430", "border": "#38383F",
            "text": "#F0F0F5", "muted": "#9090A0",
            "red": "#E53E3E", "amber": "#ECC94B", "blue": "#63B3ED", "green": "#68D391",
            "_severity": "critical", "_score": score,
        }
    elif score >= 40:
        return {
            "bg": "#FDF6EC", "card": "#FFFFFF", "border": "#E8D5B0",
            "text": "#1A1205", "muted": "#8A6C3A",
            "red": "#C05621", "amber": "#B7791F", "blue": "#2B6CB0", "green": "#276749",
            "_severity": "warning", "_score": score,
        }
    elif score >= 20:
        return {
            "bg": "#F5F0E8", "card": "#FFFFFF", "border": "#D4C9B0",
            "text": "#1C1A17", "muted": "#6B6455",
            "red": "#C0392B", "amber": "#D4880E", "blue": "#2471A3", "green": "#1E8449",
            "_severity": "balanced", "_score": score,
        }
    else:
        return {
            "bg": "#F0F4F8", "card": "#FFFFFF", "border": "#CBD5E0",
            "text": "#1A202C", "muted": "#718096",
            "red": "#E53E3E", "amber": "#DD6B20", "blue": "#2B6CB0", "green": "#276749",
            "_severity": "calm", "_score": score,
        }


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
  YOUR TOOLBOX (use all three — never raw SVG for charts)
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
     alert-triangle  alert-circle  server  database  cpu  hard-drive
     activity  trending-up  trending-down  zap  cloud  network
     layers  timer  check-circle  x-circle  info  bar-chart-2
     pie-chart  git-branch  git-merge  shield  flame  box
   NEVER use Font Awesome. ALWAYS use Lucide.
   Icons render as inline SVG — they look crisp and work in Playwright PDF.

3. CHART.JS (already loaded, animation:false set globally)
   For line, bar, area, doughnut charts ONLY (not for diagrams/tables).
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
  2. NO raw SVG for charts — use Chart.js canvas elements.
  3. NO Font Awesome — use Lucide icons only.
  4. USE EXACT data values from the DATA section.
  5. NO raw markdown — use <span class="font-bold"> not **bold**.
  6. ALL Chart.js <script> tags must go at the very END of your output.
  7. Every chart canvas must be inside a div with explicit pixel height.
  8. Use Tailwind arbitrary values for exact palette colors.
  9. The outer wrapper div must be: <div class="h-full w-full" style="background:{bg}">

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VISUAL TYPE GUIDE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cover_hero:
  Full-slide cover. Decorative background (CSS pattern with Tailwind, no SVG needed).
  Large title (text-6xl font-bold font-serif). Date badge (pill). Subtitle.
  Bottom: 3 equal preview cards each with a Lucide icon + label + description.
  <div class="h-full w-full flex flex-col" style="background:{bg}">

stat_cards_row:
  4 equal stat cards in a grid. Each card: Lucide icon top-right, giant number,
  label, sub-label. Top colored border-l-4. Use real values from data.
  <div class="h-full w-full p-14 flex flex-col gap-6" style="background:{bg}">
    <h2>...</h2>
    <div class="grid grid-cols-4 gap-6 flex-1">...</div>

bar_chart_annotated:
  Left side (40%): headline + key insight bullets with Lucide icons.
  Right side (60%): Chart.js bar chart in explicit height div.
  Below chart: 1-2 colored callout boxes with left border.

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
  CSS trapezoid-shaped divs (clip-path or border tricks) stacked top to bottom.
  Each layer: category name + count. Colored by severity.
  Or: use a horizontal bar chart via Chart.js as a proxy for funnel.

big_number_hero:
  Giant number (text-[120px] or text-9xl, font-black). Label below.
  Context sentence. Right side: Lucide icon (large, w-40 h-40) or
  a simple Chart.js doughnut/gauge. Colored by severity.

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
        except Exception:
            # Not valid JSON — fall through to string processing
            pass

        # Regex fallback: pull the value from "html": "..." even if JSON is malformed
        m = re.search(r'"html"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]?', s, re.DOTALL)
        if m:
            candidate = m.group(1).replace('\\n', '\n').replace('\\t', '  ').replace('\\"', '"')
            if len(candidate.strip()) > 50:
                return candidate.strip()

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
    if stripped.startswith('{"html"') or stripped.startswith('{ "html"'):
        return False, "Still JSON-wrapped after extraction"
    if stripped.startswith('{"') or stripped.startswith('[{"'):
        return False, "Still JSON object after extraction"
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

def _fallback_slide(slide: dict, style: dict) -> str:
    title   = slide.get('title', 'Slide')
    insight = slide.get('key_insight', '')
    data    = slide.get('data', {})
    bg      = style.get('bg', '#F5F0E8')
    card    = style.get('card', '#FFFFFF')
    text    = style.get('text', '#1A1A1A')
    muted   = style.get('muted', '#666666')
    border  = style.get('border', '#D0CEC8')
    red     = style.get('red', '#C0392B')

    rows = "".join(
        f'<tr><td style="padding:10px 14px;color:{muted};font-size:13px;'
        f'border-bottom:1px solid {border}">{str(k).replace("_"," ").title()}</td>'
        f'<td style="padding:10px 14px;font-weight:700;color:{text};'
        f'border-bottom:1px solid {border}">{v}</td></tr>'
        for k, v in list(data.items())[:8]
        if isinstance(v, (int, float, str)) and not str(k).startswith('_')
    )
    return f"""<div class="h-full w-full" style="background:{bg}">
<div style="padding:52px 72px;height:100%;box-sizing:border-box;
            display:flex;flex-direction:column;justify-content:center">
  <div style="font-size:11px;font-family:monospace;color:{red};
              letter-spacing:3px;margin-bottom:16px">EXECUTIVE SRE DIAGNOSTIC REPORT</div>
  <h2 style="font-size:40px;font-weight:800;color:{text};margin:0 0 12px;line-height:1.15">
    {title}</h2>
  <p style="font-size:18px;color:{muted};margin:0 0 24px;max-width:720px">{insight}</p>
  <div style="background:{card};border:1px solid {border};border-radius:10px;overflow:hidden;max-width:860px">
    <table style="width:100%;border-collapse:collapse">{rows}</table>
  </div>
</div></div>"""


# ══════════════════════════════════════════════════════════════════
#  GENERATE ONE SLIDE
# ══════════════════════════════════════════════════════════════════

def _generate_slide(slide: dict, style: dict, feedback: str = "") -> str:
    slot   = slide.get('slot', 0)
    mood   = slide.get('color_mood', 'neutral')
    accent_map = {
        "critical_red":  style.get('red', '#C0392B'),
        "warning_amber": style.get('amber', '#D4880E'),
        "info_blue":     style.get('blue', '#2471A3'),
        "neutral":       style.get('muted', '#555555'),
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
            raw = call(prompt, key="designer", max_tokens=4096)
        except Exception as e:
            print(f"      [attempt {attempt+1}] LLM error: {e}")
            if attempt == config.SVG_RETRY_LIMIT - 1:
                return _fallback_slide(slide, style)
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
    return _fallback_slide(slide, style)


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
    score  = style.get('_score', '')
    vs     = getattr(config, 'VISUAL_STYLE', 'auto')
    print(f"  [Designer] Style: {vs} → severity: {sev}"
          + (f" (score {score})" if score else ""))

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
        html = _generate_slide(slide, style, feedback=fb)
        results.append((slot, html))
        print("✓")

    return results
