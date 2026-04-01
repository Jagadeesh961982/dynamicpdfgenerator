# agents/assembler.py
#
# AGENT 3 — HTML ASSEMBLER
# ═════════════════════════
# Merges all slide HTML snippets into one complete print-ready HTML file.
#
# CDN STRATEGY (all work in Playwright offline mode):
#   • Tailwind: play.tailwindcss.com  — runtime JIT, all classes available
#   • Chart.js: cdnjs.cloudflare.com  — stable offline-friendly CDN
#   • Lucide:   unpkg.com/lucide      — SVG icon library, no network icons
#
# KEY DESIGN DECISIONS:
#   1. Tailwind loaded via play.tailwindcss.com — no config needed, all
#      arbitrary values (h-[380px], bg-[#C0392B]) work out of the box.
#   2. Chart.js animation globally disabled via Chart.defaults before
#      any slide scripts run — guarantees PDF snapshot catches all charts.
#   3. Lucide.createIcons() called after DOMContentLoaded to render all
#      <i data-lucide="..."> elements into inline SVGs.
#   4. window.__chartsReady counter: each chart increments it on creation.
#      Playwright waits for this to equal the total chart count.
#   5. CSS scopes: .slide has overflow:hidden and fixed 1280x720 dimensions.
#      Tailwind's h-full on slide content fills exactly that space.
#   6. Print CSS: each .slide gets page-break-after:always so each slide
#      prints as one A-landscape PDF page.

import re, sys
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from agents.designer import _get_style


# ══════════════════════════════════════════════════════════════════
#  COUNT CHARTS IN SLIDE HTML
#  (so Playwright knows how many __chartsReady increments to wait for)
# ══════════════════════════════════════════════════════════════════

def _count_charts(slides_html: list) -> int:
    total = 0
    for _, html in slides_html:
        if html:
            total += html.lower().count('new chart(')
    return total


# ══════════════════════════════════════════════════════════════════
#  GLOBAL CSS
#  Only structural rules — all visual styling is Tailwind in each slide.
# ══════════════════════════════════════════════════════════════════

def _build_global_css(style: dict) -> str:
    bg     = style.get('bg', '#F5F0E8')
    card   = style.get('card', '#FFFFFF')
    text   = style.get('text', '#1A1A1A')
    muted  = style.get('muted', '#666666')
    border = style.get('border', '#D0CEC8')
    red    = style.get('red', '#C0392B')
    amber  = style.get('amber', '#D4880E')
    blue   = style.get('blue', '#2471A3')
    green  = style.get('green', '#1E8449')

    return f"""
/* ── CSS custom properties (available to all slide content) ─────── */
:root {{
  --bg:     {bg};
  --card:   {card};
  --text:   {text};
  --muted:  {muted};
  --border: {border};
  --red:    {red};
  --amber:  {amber};
  --blue:   {blue};
  --green:  {green};
}}

/* ── Page shell ─────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; }}
body {{
  background: #B0AAA0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  padding: 28px 12px;
  font-family: 'Inter', sans-serif;
}}

/* ── Slide container ─────────────────────────────────────────────── */
.slide {{
  width:  1280px;
  height: 720px;
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 10px 40px rgba(0,0,0,0.25);
  /* background set per-slide by LLM content */
}}

/* ── Slide decorations (badge + brand — always on top) ─────────── */
.slide-num {{
  position: absolute;
  top: 16px;
  left: 24px;
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  color: {muted};
  letter-spacing: 2px;
  opacity: 0.55;
  z-index: 50;
  pointer-events: none;
}}
.slide-brand {{
  position: absolute;
  bottom: 12px;
  right: 22px;
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  color: {muted};
  opacity: 0.5;
  z-index: 50;
  pointer-events: none;
  display: flex;
  align-items: center;
  gap: 4px;
}}

/* ── Navigation overlay (browser preview only) ──────────────────── */
.nav-overlay {{
  position: fixed;
  bottom: 16px;
  right: 16px;
  background: rgba(0,0,0,0.75);
  color: #fff;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  z-index: 200;
  pointer-events: none;
}}
.print-btn {{
  position: fixed;
  top: 14px;
  left: 14px;
  background: {blue};
  color: #fff;
  border: none;
  padding: 9px 18px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  z-index: 200;
  letter-spacing: 0.3px;
}}
.print-btn:hover {{ opacity: 0.88; }}

/* ── Tailwind 'h-full' on slide content fills exactly 720px ──────── */
.slide > *:first-child {{ height: 100%; width: 100%; }}

/* ── Print / PDF export ─────────────────────────────────────────── */
@media print {{
  @page {{ size: 1280px 720px; margin: 0; }}
  html, body {{
    background: white !important;
    padding: 0 !important;
    gap: 0 !important;
    display: block !important;
  }}
  .slide {{
    page-break-after: always;
    page-break-inside: avoid;
    break-after: page;
    width:  1280px !important;
    height: 720px  !important;
    box-shadow: none !important;
  }}
  .slide:last-child {{ page-break-after: auto; }}
  .nav-overlay, .print-btn {{ display: none !important; }}
}}
"""


# ══════════════════════════════════════════════════════════════════
#  WRAP ONE SLIDE
# ══════════════════════════════════════════════════════════════════

def _wrap_slide(slot: int, html_content: str, plan_slide: dict, style: dict) -> str:
    subtitle  = plan_slide.get('subtitle', 'Executive SRE Report')
    sub_label = (subtitle or 'Executive SRE Report')[:45]
    muted     = style.get('muted', '#666666')

    # Small SVG dot for brand footer (no external icons needed)
    dot_svg = (f'<svg width="8" height="8" viewBox="0 0 8 8">'
               f'<circle cx="4" cy="4" r="3" fill="{muted}" opacity="0.5"/></svg>')

    return (
        f'<section class="slide" data-slot="{slot}">'
        f'<span class="slide-num">{slot:02d}</span>'
        + html_content
        + f'<div class="slide-brand">{dot_svg}{sub_label}</div>'
        f'</section>'
    )


# ══════════════════════════════════════════════════════════════════
#  NAV JAVASCRIPT
# ══════════════════════════════════════════════════════════════════

NAV_JS = """
<script>
(function() {
  /* Slide counter nav overlay */
  var slides = document.querySelectorAll('.slide');
  var nav    = document.getElementById('nav-overlay');
  var total  = slides.length;
  if (!nav) return;
  var obs = new IntersectionObserver(function(entries) {
    entries.forEach(function(e) {
      if (e.isIntersecting)
        nav.textContent = 'Slide ' + e.target.dataset.slot + ' / ' + total;
    });
  }, { threshold: 0.5 });
  slides.forEach(function(s) { obs.observe(s); });
})();
</script>
"""


# ══════════════════════════════════════════════════════════════════
#  CDN SCRIPT / LINK BLOCK
#  Loaded ONCE in <head>. Order matters:
#    1. Google Fonts
#    2. Tailwind CDN (play.tailwindcss.com — full runtime JIT)
#    3. Chart.js (stable CDN)
#    4. Lucide icons
#    5. Global Chart.js defaults (animation off)
#    6. Lucide init deferred to DOMContentLoaded
# ══════════════════════════════════════════════════════════════════

CDN_HEAD = """
  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;800&family=Inter:wght@300;400;500;600;700&family=Sora:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">

  <!-- Tailwind CSS CDN (runtime JIT — all arbitrary values work) -->
  <script src="https://cdn.tailwindcss.com"></script>

  <!-- Chart.js -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>

  <!-- Lucide icons (renders <i data-lucide="name"> → inline SVG) -->
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>

  <script>
    /* ── Global Chart.js defaults: disable ALL animation ── */
    document.addEventListener('DOMContentLoaded', function() {
      if (window.Chart) {
        Chart.defaults.animation = false;
        Chart.defaults.animations = { numbers: false };
        Chart.defaults.transitions = {};
      }

      /* ── Render all Lucide icons ── */
      if (window.lucide) {
        lucide.createIcons();
      }
    });

    /* ── Chart ready sentinel counter (Playwright awaits this) ── */
    window.__chartsReady = 0;
    window.__chartsTotal = 0; /* set by assembler in a data attribute */
  </script>
"""


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(plan: dict, slides_html: list, prev_sections: Optional[list] = None) -> tuple:
    """
    Assemble all slides into one complete HTML document.

    Args:
        plan:          Full plan from Agent 1
        slides_html:   List of (slot, html_content|None) from Agent 2
        prev_sections: Previous iteration section strings (for patch mode)

    Returns:
        (html_string, sections_list)
    """
    style = _get_style(plan)

    # Build lookups
    plan_slides  = {s['slot']: s for s in plan.get('slides', [])}
    html_by_slot = {slot: html for slot, html in slides_html if html is not None}

    prev_by_slot: dict = {}
    if prev_sections:
        for sec in prev_sections:
            m = re.search(r'data-slot="(\d+)"', sec)
            if m:
                prev_by_slot[int(m.group(1))] = sec

    # Assemble sections in slot order
    slots_ordered = sorted(plan_slides.keys())
    sections      = []

    for slot in slots_ordered:
        plan_slide = plan_slides[slot]
        if slot in html_by_slot:
            section = _wrap_slide(slot, html_by_slot[slot], plan_slide, style)
        elif slot in prev_by_slot:
            section = prev_by_slot[slot]
        else:
            # Empty placeholder
            bg   = style.get('bg', '#F5F0E8')
            text = style.get('text', '#1A1A1A')
            muted = style.get('muted', '#666666')
            section = (
                f'<section class="slide" data-slot="{slot}">'
                f'<span class="slide-num">{slot:02d}</span>'
                f'<div class="h-full w-full flex items-center justify-center" style="background:{bg}">'
                f'<p style="color:{muted};font-size:18px">Slide {slot} — {plan_slide.get("title","")}</p>'
                f'</div></section>'
            )
        sections.append(section)

    # Count charts in all slides so Playwright knows how long to wait
    chart_count = _count_charts(slides_html)

    css          = _build_global_css(style)
    report_title = plan.get('report_title', 'Infrastructure Alert Report')

    html = (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "  <meta charset='UTF-8'>\n"
        "  <meta name='viewport' content='width=1280'>\n"
        f"  <title>{report_title}</title>\n"
        + CDN_HEAD
        + f"  <style>{css}</style>\n"
        # Embed chart total count so Playwright script can read it
        f"  <meta name='chart-total' content='{chart_count}'>\n"
        "</head>\n"
        "<body>\n"
        "<button class='print-btn' onclick='window.print()'>🖨 Print / Save PDF</button>\n"
        f"<div class='nav-overlay' id='nav-overlay'>Slide 1 / {len(sections)}</div>\n"
        + "\n".join(sections)
        + "\n"
        + NAV_JS
        + "\n</body>\n</html>"
    )

    print(f"  [Assembler] Done — {len(sections)} slides, {chart_count} charts ({len(html):,} chars)")
    return html, sections
