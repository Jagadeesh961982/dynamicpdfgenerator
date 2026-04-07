# agents/assembler.py
#
# AGENT 3 — HTML ASSEMBLER
# ═════════════════════════
# Merges all slide HTML snippets into one complete print-ready HTML file.
#
# CDN STRATEGY:
#   • Tailwind: cdn.tailwindcss.com (runtime JIT — all classes including arbitrary values)
#   • Chart.js:  cdnjs.cloudflare.com (stable, offline-friendly)
#   • Fonts:     Google Fonts (Inter for body, Playfair Display for editorial headings)
#   • Icons:     NONE — all icons are inline SVG from utils/icons.py
#
# KEY DESIGN DECISIONS:
#   1. Icons are inline SVG — zero CDN icon dependency, 100% PDF render success.
#   2. Chart.js animation globally disabled via Chart.defaults before any slides run.
#   3. window.__chartsReady counter: each chart increments it after creation.
#      Playwright waits for this count before PDF capture.
#   4. Each .slide is exactly 1280×720px. overflow:hidden prevents bleed.
#   5. CSS @media print: page-break-after:always per slide = one PDF page each.
#   6. Tailwind arbitrary values (h-[380px], bg-[#C0392B]) work via CDN runtime.

import re, sys
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from agents.designer import _get_style


# ══════════════════════════════════════════════════════════════════
#  COUNT CHART.JS INSTANCES
# ══════════════════════════════════════════════════════════════════

def _count_charts(slides_html: list) -> int:
    return sum(
        html.lower().count('new chart(')
        for _, html in slides_html
        if html
    )


# ══════════════════════════════════════════════════════════════════
#  CSS — structural only; visual styling is per-slide via Tailwind
# ══════════════════════════════════════════════════════════════════

def _build_global_css(style: dict) -> str:
    bg     = style.get('bg',     '#F5F0E8')
    muted  = style.get('muted',  '#666666')
    blue   = style.get('blue',   '#2471A3')
    border = style.get('border', '#D0CEC8')
    family = style.get('family', 'warm')

    # Shell background: complementary to slide palette
    shell_bg = {
        'warm': '#9A9080',
        'cool': '#7A8898',
        'dark': '#050810',
    }.get(family, '#8A8880')

    return f"""
:root {{
  --bg:     {bg};
  --muted:  {muted};
  --blue:   {blue};
  --border: {border};
}}

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; }}

body {{
  background: {shell_bg};
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 28px;
  padding: 32px 16px;
  font-family: 'Inter', sans-serif;
}}

/* ── Slide container ─────────────────────────────────────────────── */
.slide {{
  width:  1280px;
  height: 720px;
  position: relative;
  overflow: hidden;          /* hard clip — nothing bleeds out */
  flex-shrink: 0;
  box-shadow: 0 16px 48px rgba(0,0,0,0.35), 0 4px 12px rgba(0,0,0,0.2);
  border-radius: 2px;
}}

/* Slide inner content must never exceed 720px */
.slide > *:first-child {{
  height: 100%;
  width:  100%;
  max-height: 720px;
  overflow: hidden;          /* belt-and-suspenders: inner wrapper also clips */
  box-sizing: border-box;
}}

/* ── Slide number badge ──────────────────────────────────────── */
.slide-num {{
  position: absolute;
  top: 14px;
  left: 20px;
  font-size: 9px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: {muted};
  letter-spacing: 2.5px;
  opacity: 0.45;
  z-index: 50;
  pointer-events: none;
  text-transform: uppercase;
}}

/* ── Brand footer ────────────────────────────────────────────── */
.slide-brand {{
  position: absolute;
  bottom: 11px;
  right: 20px;
  font-size: 9px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: {muted};
  opacity: 0.4;
  z-index: 50;
  pointer-events: none;
  display: flex;
  align-items: center;
  gap: 5px;
}}

/* ── Nav overlay (browser preview only) ─────────────────────── */
#nav-overlay {{
  position: fixed;
  bottom: 14px;
  right: 14px;
  background: rgba(0,0,0,0.72);
  color: #fff;
  padding: 5px 10px;
  border-radius: 5px;
  font-size: 10px;
  font-family: monospace;
  z-index: 200;
  pointer-events: none;
}}

/* ── Print button ────────────────────────────────────────────── */
.print-btn {{
  position: fixed;
  top: 12px;
  left: 12px;
  background: {blue};
  color: #fff;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  z-index: 200;
}}
.print-btn:hover {{ opacity: 0.85; }}

/* ── Print / PDF export ──────────────────────────────────────── */
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
    border-radius: 0 !important;
  }}
  .slide:last-child {{ page-break-after: auto; }}
  #nav-overlay, .print-btn {{ display: none !important; }}
}}
"""


# ══════════════════════════════════════════════════════════════════
#  HEAD BLOCK — fonts + Tailwind + Chart.js (no icon CDN needed)
# ══════════════════════════════════════════════════════════════════

CDN_HEAD = """
  <!-- Fonts: Inter (body) + Playfair Display (editorial headings) + JetBrains Mono -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,800;0,900;1,700&family=Inter:wght@300;400;500;600;700;800&family=Sora:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">

  <!-- Tailwind CSS CDN runtime (all classes including arbitrary values) -->
  <script src="https://cdn.tailwindcss.com"></script>

  <!-- Chart.js (stable CDN) -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>

  <script>
    /* ── Globally disable Chart.js animations — required for PDF ── */
    document.addEventListener('DOMContentLoaded', function() {
      if (window.Chart) {
        Chart.defaults.animation = false;
        Chart.defaults.animations = { numbers: false };
        Chart.defaults.transitions = {};
      }
    });

    /* ── Chart ready sentinel — Playwright awaits this ── */
    window.__chartsReady = 0;
  </script>
"""

# ══════════════════════════════════════════════════════════════════
#  SLIDE WRAPPER
# ══════════════════════════════════════════════════════════════════

def _wrap_slide(slot: int, html_content: str,
                plan_slide: dict, style: dict) -> str:
    subtitle = (plan_slide.get('subtitle') or plan_slide.get('title') or 'Report')[:48]
    muted    = style.get('muted', '#666666')

    # Tiny dot SVG for brand footer
    dot = (f'<svg width="6" height="6" viewBox="0 0 6 6" '
           f'fill="{muted}" opacity="0.5"><circle cx="3" cy="3" r="2.5"/></svg>')

    return (
        f'<section class="slide" data-slot="{slot}">'
        f'<span class="slide-num">{slot:02d}</span>'
        + html_content +
        f'<div class="slide-brand">{dot}{subtitle}</div>'
        f'</section>'
    )


# ══════════════════════════════════════════════════════════════════
#  NAV JAVASCRIPT
# ══════════════════════════════════════════════════════════════════

NAV_JS = """
<script>
(function() {
  var slides = document.querySelectorAll('.slide');
  var nav    = document.getElementById('nav-overlay');
  if (!nav || !slides.length) return;
  var total = slides.length;
  nav.textContent = 'Slide 1 / ' + total;
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
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(plan: dict,
        slides_html: list,
        prev_sections: Optional[list] = None) -> tuple[str, list]:
    """
    Assemble all slides into a complete HTML document.

    Args:
        plan:          Full plan dict from Agent 1.
        slides_html:   List of (slot, html_content | None) from Agent 2.
        prev_sections: Previous iteration's section HTML strings (patch mode).

    Returns:
        (html_string, sections_list)
    """
    style = _get_style(plan)

    # Build lookup maps
    plan_slides  = {s['slot']: s for s in plan.get('slides', [])}
    html_by_slot = {slot: html for slot, html in slides_html if html is not None}

    prev_by_slot: dict[int, str] = {}
    if prev_sections:
        for sec in prev_sections:
            m = re.search(r'data-slot="(\d+)"', sec)
            if m:
                prev_by_slot[int(m.group(1))] = sec

    # Assemble sections in slot order
    slots_ordered = sorted(plan_slides.keys())
    sections: list[str] = []
    bg    = style.get('bg',    '#F5F0E8')
    muted = style.get('muted', '#666666')

    for slot in slots_ordered:
        plan_slide = plan_slides[slot]

        if slot in html_by_slot:
            section = _wrap_slide(slot, html_by_slot[slot], plan_slide, style)
        elif slot in prev_by_slot:
            section = prev_by_slot[slot]
        else:
            # Empty placeholder — marks it for critic to flag
            section = (
                f'<section class="slide" data-slot="{slot}">'
                f'<span class="slide-num">{slot:02d}</span>'
                f'<div class="h-full w-full flex items-center justify-center" style="background:{bg}">'
                f'<p style="color:{muted};font-size:18px;font-family:monospace">'
                f'Slide {slot} — {plan_slide.get("title", "")}'
                f'</p></div></section>'
            )
        sections.append(section)

    chart_count  = _count_charts(slides_html)
    report_title = plan.get('report_title', 'Report')
    css          = _build_global_css(style)

    html = (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "  <meta charset='UTF-8'>\n"
        "  <meta name='viewport' content='width=1280'>\n"
        f"  <title>{report_title}</title>\n"
        + CDN_HEAD +
        f"  <style>{css}</style>\n"
        f"  <meta name='chart-total' content='{chart_count}'>\n"
        "</head>\n"
        "<body>\n"
        "<button class='print-btn' onclick='window.print()'>🖨 Print / Save PDF</button>\n"
        f"<div id='nav-overlay'>Slide 1 / {len(sections)}</div>\n"
        + "\n".join(sections) + "\n"
        + NAV_JS +
        "\n</body>\n</html>"
    )

    print(f"  [Assembler] {len(sections)} slides | {chart_count} charts | {len(html):,} chars")
    return html, sections