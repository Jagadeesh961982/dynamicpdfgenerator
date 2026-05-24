# agents/critic.py
#
# AGENT 4 — CRITIC
# ═════════════════
# Quality reviewer. Scores on 6 weighted dimensions.
# Checks persona compliance, visual variety, overflow risk, font diversity.
# Returns structured feedback + slides_to_fix with enough context
# for the designer to produce a genuinely better result on retry.

import json, re, sys
from dataclasses import dataclass, field
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call_json
import config


@dataclass
class CriticResult:
    scores:         dict  = field(default_factory=dict)
    feedback:       dict  = field(default_factory=dict)
    weighted_score: float = 0.0
    priority_fixes: list  = field(default_factory=list)
    slides_to_fix:  list  = field(default_factory=list)
    verdict:        str   = ""
    passed:         bool  = False

    WEIGHTS = {
        "data_accuracy":    0.25,
        "visual_quality":   0.25,
        "insight_depth":    0.20,
        "aesthetic_variety":0.15,
        "completeness":     0.10,
        "layout_integrity": 0.05,
    }

    def compute_score(self):
        self.weighted_score = sum(
            self.scores.get(d, 5.0) * w
            for d, w in self.WEIGHTS.items()
        )
        self.passed = self.weighted_score >= config.PASS_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "dimension_scores":   self.scores,
            "dimension_feedback": self.feedback,
            "weighted_score":     round(self.weighted_score, 2),
            "priority_fixes":     self.priority_fixes,
            "slides_to_fix":      self.slides_to_fix,
            "verdict":            self.verdict,
            "passed":             self.passed,
        }

    def print_report(self):
        bars = {d: "#" * int(s) + "." * (10 - int(s))
                for d, s in self.scores.items()}
        sep = "=" * 68
        status = "PASS" if self.passed else "RETRY"
        print(f"\n{sep}")
        print(f"  CRITIC SCORE: {self.weighted_score:.2f}/10  [{status}]")
        print(f"  {self.verdict}")
        print(f"{'-'*68}")
        for d, score in self.scores.items():
            fb = self.feedback.get(d, "")[:55]
            print(f"  {d:<22} {bars.get(d,''):<10} {score:.1f}  {fb}")
        print(f"{'-'*68}")
        if self.priority_fixes:
            print("  Priority fixes:")
            for i, fx in enumerate(self.priority_fixes, 1):
                print(f"    {i}. {fx}")
        if self.slides_to_fix:
            slots = [str(s.get('slot', '?')) for s in self.slides_to_fix]
            print(f"  Slides to patch: {', '.join(slots)}")
        print(f"{sep}\n")


# ══════════════════════════════════════════════════════════════════
#  SLIDE CONTENT + VISUAL EXTRACTOR
# ══════════════════════════════════════════════════════════════════

_DARK_BG_PATTERN  = re.compile(r'background[:\s]+#([0-9a-fA-F]{6})', re.IGNORECASE)
_FONT_FAMILY_PAT  = re.compile(r"font-family\s*:\s*['\"]?([^;'\"]+)", re.IGNORECASE)


def _is_dark_color(hex_val: str) -> bool:
    """Returns True if the hex color has luminance below 0.18 (dark)."""
    try:
        h = hex_val.lstrip('#')
        if len(h) != 6:
            return False
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.18
    except Exception:
        return False


def _extract_slide_previews(html: str, plan_slides: list) -> list[dict]:
    """
    Extract per-slide metadata for both deterministic checks and the LLM prompt.
    Includes: text preview, background color, font signals, persona compliance hints.
    """
    plan_by_slot = {s.get('slot'): s for s in plan_slides}
    previews = []

    for m in re.finditer(
        r'<section[^>]+data-slot="(\d+)"[^>]*>(.*?)</section>',
        html, re.DOTALL | re.IGNORECASE
    ):
        slot = int(m.group(1))
        body = m.group(2)

        # Readable text
        text = re.sub(r'<[^>]+>', ' ', body)
        text = re.sub(r'\s+', ' ', text).strip()

        # Background color(s) in this slide
        bg_colors = list(dict.fromkeys(
            c.lower() for c in _DARK_BG_PATTERN.findall(body)
        ))
        primary_bg = bg_colors[0] if bg_colors else 'unknown'

        # Font families used
        fonts_raw = _FONT_FAMILY_PAT.findall(body)
        fonts = list(dict.fromkeys(f.split(',')[0].strip().strip("'\"") for f in fonts_raw))

        # Persona signals
        has_playfair  = any('playfair' in f.lower() for f in fonts) or 'Playfair' in body
        has_sora      = any('sora' in f.lower() for f in fonts) or "'Sora'" in body
        has_jetbrains = any('jetbrains' in f.lower() for f in fonts) or 'JetBrains Mono' in body
        has_chart     = 'new chart(' in body.lower()
        has_icon      = '<svg' in body.lower() and 'viewBox' in body
        has_stub      = '[[icon:' in body

        # Overflow risk signals
        overflow_risks = []
        if re.search(r'\bpy-1[2-9]\b|\bp-1[2-9]\b', body):
            overflow_risks.append('oversized-padding')
        if re.search(r'font-size\s*:\s*(?:[5-9]\d|[1-9]\d{2,})px', body):
            overflow_risks.append('large-px-font')
        if re.search(r'min-h-\[\d{3,}px\]', body):
            overflow_risks.append('fixed-min-height')

        # Default/forbidden background check
        is_default_bg = '#eff6ff' in body.lower() or 'EFF6FF' in body
        is_pure_black = primary_bg in ('0d1117', '0a0e1a', '000000', '0d0d0d')

        # Expected persona from plan
        plan_slide = plan_by_slot.get(slot, {})
        expected_persona = plan_slide.get('aesthetic_persona', 'unknown')

        previews.append({
            'slot':             slot,
            'preview':          text[:220],
            'char_count':       len(text),
            'primary_bg':       primary_bg,
            'bg_colors':        bg_colors[:3],
            'is_dark':          _is_dark_color(primary_bg),
            'fonts':            fonts[:4],
            'has_playfair':     has_playfair,
            'has_sora':         has_sora,
            'has_jetbrains':    has_jetbrains,
            'has_chart':        has_chart,
            'has_icon':         has_icon,
            'has_stub':         has_stub,
            'is_short':         len(text.strip()) < 120,
            'overflow_risks':   overflow_risks,
            'is_default_bg':    is_default_bg,
            'is_pure_black':    is_pure_black,
            'expected_persona': expected_persona,
        })

    return previews


# ══════════════════════════════════════════════════════════════════
#  DETERMINISTIC CHECKS
# ══════════════════════════════════════════════════════════════════

def _quick_checks(html: str, plan: dict, previews: list[dict], output_format: str = "pdf") -> list[str]:
    """
    Run hard structural checks that don't need LLM judgment.
    Each issue found becomes a priority_fix and contributes to score cap.
    """
    issues = []

    # 1. Unsubstituted icon placeholders
    if '[[icon:' in html:
        issues.append("Unsubstituted [[icon:...]] placeholders found — Python substitution failed")

    # 2. Raw markdown bold in output
    if re.search(r'\*\*[^<]{1,60}\*\*', html):
        issues.append("Raw **markdown** bold found in HTML — must use <strong> tags")

    # 3. Placeholder text
    if re.search(r'\blorem ipsum\b|\bplaceholder\b', html, re.IGNORECASE):
        issues.append("Placeholder or lorem-ipsum text detected in slides")

    # 4. Slide count
    n_slides = html.count('<section')
    target   = config.N_SLIDES
    if n_slides < max(target - 4, 6):
        issues.append(f"Only {n_slides} slides rendered — expected ~{target}")

    # 5. Default EFF6FF background (old white-card syndrome)
    n_default = sum(1 for p in previews if p['is_default_bg'])
    if n_default > 0:
        issues.append(
            f"{n_default} slide(s) still use default #EFF6FF background — "
            "aesthetic personas not applied"
        )

    # 6. Pure-black background (should be dark navy now)
    n_pure_black = sum(1 for p in previews if p['is_pure_black'])
    if n_pure_black > 0:
        issues.append(
            f"{n_pure_black} slide(s) use pure-black bg (#0D1117/#0A0E1A) — "
            "use dark navy (#0F1629) instead for cohesive look"
        )

    # 7. Background variety — all slides same color = no visual differentiation
    # Skip for PPTX where a unified theme is intentional and correct.
    unique_bgs = {p['primary_bg'] for p in previews if p['primary_bg'] != 'unknown'}
    if output_format != "pptx" and len(unique_bgs) < max(2, len(previews) // 4):
        issues.append(
            f"Only {len(unique_bgs)} unique background color(s) across {len(previews)} slides — "
            "personas are not producing visual variety"
        )

    # 8. Font monoculture — Inter only, Playfair/Sora never used
    any_playfair  = any(p['has_playfair']  for p in previews)
    any_sora      = any(p['has_sora']      for p in previews)
    any_jetbrains = any(p['has_jetbrains'] for p in previews)
    if not any_playfair and not any_sora:
        issues.append(
            "No Playfair Display or Sora fonts used anywhere — "
            "editorial/narrative personas require distinctive typography"
        )

    # 9. Overflow risk patterns
    overflow_slides = [p['slot'] for p in previews if p['overflow_risks']]
    if overflow_slides:
        issues.append(
            f"Overflow-risk patterns (oversized padding / fixed min-height) in "
            f"slide(s): {overflow_slides[:4]}"
        )

    # 10. Key entity coverage
    analysis = plan.get('_analysis', {})
    entities = analysis.get('key_entities', [])
    if entities:
        found = sum(1 for e in entities[:10] if e.lower() in html.lower())
        if found < max(1, len(entities[:10]) // 3):
            issues.append(
                f"Only {found}/{len(entities[:10])} key entities visible — "
                "content is too generic"
            )

    # 11. No icons at all — PDF looks like a plain text doc
    n_with_icons = sum(1 for p in previews if p['has_icon'])
    if n_with_icons < max(1, len(previews) // 2):
        issues.append(
            f"Only {n_with_icons}/{len(previews)} slides have icons — "
            "visual richness is very low"
        )

    return issues


# ══════════════════════════════════════════════════════════════════
#  SCORE CAPS FROM STRUCTURAL ISSUES
# ══════════════════════════════════════════════════════════════════

def _compute_caps(issues: list[str], previews: list[dict], output_format: str = "pdf") -> dict:
    """
    Returns per-dimension score caps based on deterministic findings.
    The LLM score is min(llm_score, cap).
    """
    caps = {d: 10.0 for d in CriticResult.WEIGHTS}

    # Default EFF6FF: visual quality and aesthetic variety capped hard
    n_default = sum(1 for p in previews if p['is_default_bg'])
    if n_default > 0:
        caps['visual_quality']    = min(caps['visual_quality'],    4.5)
        caps['aesthetic_variety'] = min(caps['aesthetic_variety'], 3.5)

    # No font variety
    if not any(p['has_playfair'] or p['has_sora'] for p in previews):
        caps['visual_quality']    = min(caps['visual_quality'],    5.5)
        caps['aesthetic_variety'] = min(caps['aesthetic_variety'], 5.0)

    # Low background variety — skip for PPTX where unified theme is intentional
    unique_bgs = {p['primary_bg'] for p in previews if p['primary_bg'] != 'unknown'}
    if output_format != "pptx" and len(unique_bgs) < 3:
        caps['aesthetic_variety'] = min(caps['aesthetic_variety'], 4.0)

    # Pure black backgrounds
    n_pure_black = sum(1 for p in previews if p['is_pure_black'])
    if n_pure_black > 0:
        caps['aesthetic_variety'] = min(caps['aesthetic_variety'], 6.0)

    # Overflow risks
    n_overflow = sum(1 for p in previews if p['overflow_risks'])
    if n_overflow > 1:
        caps['layout_integrity'] = min(caps['layout_integrity'], 5.0)

    # Unsubstituted icons
    if any('placeholder' in i.lower() or 'icon' in i.lower() for i in issues):
        caps['visual_quality'] = min(caps['visual_quality'], 5.0)

    # Short/empty slides
    n_short = sum(1 for p in previews if p['is_short'])
    if n_short > 0:
        caps['completeness']    = min(caps['completeness'],    max(3.0, 7.0 - n_short * 1.5))
        caps['data_accuracy']   = min(caps['data_accuracy'],   max(4.0, 7.5 - n_short * 1.0))

    return caps


# ══════════════════════════════════════════════════════════════════
#  CRITIC PROMPT
# ══════════════════════════════════════════════════════════════════

CRITIC_PROMPT = """You are an exceptionally strict quality reviewer for professional PDF presentations.
Your job is to be HARDER than the designer expects — only truly excellent work scores 8+.

REPORT CONTEXT:
  Content type:    {content_type}
  Subject:         {subject}
  Target audience: {audience}
  Data richness:   {data_richness}
  Narrative arc:   {narrative_arc}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORING DIMENSIONS (0.0–10.0 each)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  data_accuracy    — Real numbers, real names, real facts used throughout?
                     Penalise: "N items", "X%", placeholder values, generic statements.
                     Reward: specific hostnames, exact percentages, named entities from the data.

  visual_quality   — Information-rich visuals? Icons on every card? Charts where data warrants?
                     Penalise: plain text walls, cards with only a title + 1 line, no icons.
                     Reward: stat cards with multi-sentence descriptions, icon-per-item, Chart.js charts.

  insight_depth    — Specific, named insights? Does the slide EXPLAIN WHY a metric matters?
                     Penalise: single-sentence bullets, restating metrics without context.
                     Reward: 2-3 sentence descriptions per item explaining significance and impact.

  aesthetic_variety — Are the slides visually distinct from each other?
                      Penalise: all slides with identical background / same card style / same font.
                      Reward: distinct personas per slide (dark navy / vibrant accent / warm cream);
                              Playfair Display on editorial slides; JetBrains Mono on technical slides;
                              Sora on warm/narrative slides; variety of layout structures.

  completeness     — Cover + themed analysis + conclusion present? All plan slides rendered?
                     Penalise: missing sections, slides that ignore their plan visual_type.

  layout_integrity — Clean spacing, no text clipping, print-ready, no overflow artefacts?
                     Penalise: text cut off, oversized padding, cards spilling outside bounds,
                               font-size > 56px on non-hero elements.

STRICT SCORING GUIDE:
  9–10 = Publication-ready. Every slide is specific, beautiful, and uses the correct persona.
  7–8  = Good — mostly specific, minor persona or density issues.
  5–6  = Mediocre — some real data but generic visuals or monotone backgrounds.
  3–4  = Poor — little real data, mostly generic, personas not applied.
  1–2  = Unacceptable — placeholder content, all slides look the same.

IMPORTANT: If ALL slides have the same background color, aesthetic_variety MUST be ≤ 4.0.
IMPORTANT: If no Playfair Display or Sora fonts appear anywhere, aesthetic_variety MUST be ≤ 5.5.
IMPORTANT: If slides use generic white cards on light-blue bg, visual_quality MUST be ≤ 5.0.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEY FACTS TO VERIFY (check each appears in slides):
{key_facts}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SLIDE PLAN (intended — check each slide matches its visual_type and persona):
{slide_plan_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PER-SLIDE ANALYSIS (bg color, fonts, icons, overflow risks):
{slide_previews}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HTML EXCERPT (first 4000 chars):
{html_excerpt}

HTML SIZE: {html_size} chars  |  SLIDE COUNT: {slide_count}
STRUCTURAL ISSUES ALREADY DETECTED: {known_issues}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY this JSON (no markdown, no extra keys):
{{
  "dimension_scores": {{
    "data_accuracy":    8.5,
    "visual_quality":   7.0,
    "insight_depth":    8.0,
    "aesthetic_variety":6.5,
    "completeness":     9.0,
    "layout_integrity": 7.5
  }},
  "dimension_feedback": {{
    "data_accuracy":    "Specific finding about data use",
    "visual_quality":   "Specific finding about visuals and icons",
    "insight_depth":    "Specific finding about depth of explanations",
    "aesthetic_variety":"Specific finding: which slides looked the same / which were distinct",
    "completeness":     "Specific finding about coverage",
    "layout_integrity": "Specific finding about spacing/overflow/fonts"
  }},
  "priority_fixes": [
    "Most important fix — be specific: slot number + exact change needed",
    "Second fix",
    "Third fix",
    "Fourth fix (if needed)",
    "Fifth fix (if needed)"
  ],
  "verdict": "One sentence overall verdict mentioning the best and worst aspect",
  "slides_to_fix": [
    {{
      "slot": 5,
      "expected_persona": "infographic_vibrant",
      "problem": "Specific problem — e.g.: Slide 5 uses default white bg with blue cards — infographic_vibrant persona not applied",
      "fix": "Specific actionable fix — e.g.: Apply solid accent color as background, use white rounded-2xl cards with shadow-2xl, add large central [[icon:NAME:128:white]]",
      "prev_content_hint": "What the slide currently shows in 1 sentence"
    }}
  ]
}}

RULES for slides_to_fix:
  - Include any slide where: persona was NOT applied | bg is default/uniform | content is thin
  - Maximum 6 slides
  - "problem" must name the SPECIFIC failure: wrong bg color, missing font, no icons, thin content
  - "fix" must give the EXACT CSS/layout change: bg color, font-family, card style, icon usage
  - Include "expected_persona" from the slide plan — designer uses this to re-render correctly
  - Empty/short slides (char_count < 120) MUST be listed with a full re-render instruction"""


# ══════════════════════════════════════════════════════════════════
#  SLIDES-TO-FIX ENRICHMENT
# ══════════════════════════════════════════════════════════════════

_PERSONA_FIX_HINTS = {
    'editorial_dark': (
        "Apply bg #0F1629 (dark navy). Use Playfair Display font-black for headline. "
        "Cards: bg-[#1A2235] border border-[#2A3352] rounded-lg. No white cards. "
        "Accent color only on text/numbers."
    ),
    'data_dashboard': (
        "Apply bg #0A1020 with grid overlay. ALL numbers font-mono tracking-widest. "
        "Cards: bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.07)]. "
        "Bloomberg terminal density. No colored left-border accents."
    ),
    'magazine_spread': (
        "Apply bg #FDFAF5 (warm cream). Use Playfair Display text-5xl+ for headline. "
        "Cards: bg-white border-b-2 rounded-none (editorial, not rounded-xl). "
        "Left accent band or giant headline top section."
    ),
    'infographic_vibrant': (
        "Apply accent color AS FULL BACKGROUND (solid vivid color). "
        "Cards: bg-white rounded-2xl shadow-2xl. "
        "Use large [[icon:NAME:128:white]] as central focal point."
    ),
    'minimalist_focus': (
        "Apply bg #FFFFFF. ONE massive focal element: giant number (font-size:160px) OR "
        "Playfair blockquote (font-size:52px) OR large icon [[icon:NAME:160:accent]]. "
        "NO cards, NO header zone, NO footer. Pure whitespace."
    ),
    'technical_dense': (
        "Apply bg #131926. ALL text font-mono JetBrains Mono. "
        "Cards: bg-[#1C2333] border border-[#1E2A40] rounded-sm. "
        "Split: LEFT label+value rows, RIGHT chart or table. Dense, no whitespace."
    ),
    'narrative_warm': (
        "Apply bg #FFFBF0 (warm cream). Sora font headlines. "
        "Left-aligned article layout, flowing paragraph + 2-col fact grid. "
        "Cards: bg-[#FEF9F0] border border-[#F5DEB3] rounded-2xl."
    ),
    'vibrant_split': (
        "Hard left/right split: left 40% = accent color bg + white icon + white text, "
        "right 60% = #FDFAF5 bg + data cards. "
        "Outer: display:flex flex-direction:row. No footer."
    ),
}


def _enrich_fixes(
    llm_fixes: list[dict],
    previews: list[dict],
    plan_slides: list,
) -> list[dict]:
    """
    Enrich designer fix instructions with persona-specific CSS guidance
    and add deterministic catches the LLM may have missed.
    """
    plan_by_slot  = {s.get('slot'): s for s in plan_slides}
    llm_slots     = {int(f.get('slot', 0)) for f in llm_fixes}
    enriched = []

    for fix in llm_fixes:
        slot    = int(fix.get('slot', 0))
        persona = fix.get('expected_persona') or \
                  plan_by_slot.get(slot, {}).get('aesthetic_persona', 'editorial_dark')
        hint    = _PERSONA_FIX_HINTS.get(persona, '')
        if hint and hint not in fix.get('fix', ''):
            fix['fix'] = f"{fix.get('fix', '')} | PERSONA CSS: {hint}"
        fix['expected_persona'] = persona
        enriched.append(fix)

    # Deterministic: empty/short slides not caught by LLM
    for p in previews:
        if p['is_short'] and p['slot'] not in llm_slots:
            slot    = p['slot']
            persona = plan_by_slot.get(slot, {}).get('aesthetic_persona', 'editorial_dark')
            enriched.append({
                'slot':             slot,
                'expected_persona': persona,
                'problem':          f"Slide {slot} is nearly empty ({p['char_count']} text chars)",
                'fix':              (
                    f"Full re-render needed. "
                    f"| PERSONA CSS: {_PERSONA_FIX_HINTS.get(persona, '')}"
                ),
                'prev_content_hint': p['preview'][:100],
            })
            llm_slots.add(slot)

    # Deterministic: unsubstituted icon stubs
    for p in previews:
        if p['has_stub'] and p['slot'] not in llm_slots:
            slot    = p['slot']
            persona = plan_by_slot.get(slot, {}).get('aesthetic_persona', 'editorial_dark')
            enriched.append({
                'slot':             slot,
                'expected_persona': persona,
                'problem':          f"Slide {slot} has unsubstituted [[icon:...]] placeholders",
                'fix':              "Use [[icon:NAME:SIZE:COLOR]] syntax exactly — Python replaces them",
                'prev_content_hint': p['preview'][:100],
            })
            llm_slots.add(slot)

    # Deterministic: default EFF6FF bg (persona not applied at all)
    for p in previews:
        if p['is_default_bg'] and p['slot'] not in llm_slots:
            slot    = p['slot']
            persona = plan_by_slot.get(slot, {}).get('aesthetic_persona', 'editorial_dark')
            enriched.append({
                'slot':             slot,
                'expected_persona': persona,
                'problem':          f"Slide {slot} uses default #EFF6FF bg — {persona} persona not applied",
                'fix':              _PERSONA_FIX_HINTS.get(persona, 'Apply correct persona background'),
                'prev_content_hint': p['preview'][:100],
            })
            llm_slots.add(slot)

    return enriched[:6]


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(html: str, plan: dict, output_format: str = "pdf") -> CriticResult:
    print("  [Critic] Reviewing report quality...")

    analysis    = plan.get('_analysis', {})
    plan_slides = plan.get('slides', [])

    # ── Per-slide analysis ─────────────────────────────────────────
    previews = _extract_slide_previews(html, plan_slides)

    # ── Deterministic checks ───────────────────────────────────────
    issues = _quick_checks(html, plan, previews, output_format=output_format)
    caps   = _compute_caps(issues, previews, output_format=output_format)

    # ── Build prompts ──────────────────────────────────────────────
    key_facts_data = {
        'content_type':  analysis.get('content_type', 'unknown'),
        'subject':       analysis.get('subject', ''),
        'key_entities':  analysis.get('key_entities', [])[:12],
        'top_facts':     [f.get('fact', '') for f in analysis.get('key_facts', [])[:12]],
        'data_richness': analysis.get('data_richness', 'unknown'),
    }

    slide_plan_summary = "\n".join(
        f"  Slot {s.get('slot'):2d}: [{s.get('visual_type','?'):22s}] "
        f"persona={s.get('aesthetic_persona','?'):20s} | {s.get('title','')[:40]}"
        for s in plan_slides
    )

    slide_previews_text = "\n".join(
        f"  Slot {p['slot']:2d}: "
        f"bg=#{p['primary_bg']:<8} "
        f"{'DARK' if p['is_dark'] else 'LIGHT':<5} "
        f"{'DEFAULT-BG ' if p['is_default_bg'] else ''}"
        f"{'PURE-BLACK ' if p['is_pure_black'] else ''}"
        f"{'[SHORT] ' if p['is_short'] else ''}"
        f"{'[NO-ICON] ' if not p['has_icon'] else ''}"
        f"{'[STUB] ' if p['has_stub'] else ''}"
        f"{'[CHART] ' if p['has_chart'] else ''}"
        f"{'[Playfair] ' if p['has_playfair'] else ''}"
        f"{'[Sora] ' if p['has_sora'] else ''}"
        f"{'[JetBrainsMono] ' if p['has_jetbrains'] else ''}"
        f"{'[OVERFLOW-RISK:' + ','.join(p['overflow_risks']) + '] ' if p['overflow_risks'] else ''}"
        f"persona_expected={p['expected_persona']} | "
        f"{p['preview'][:120]}"
        for p in previews
    )

    # ── LLM review ────────────────────────────────────────────────
    prompt = CRITIC_PROMPT.format(
        content_type       = analysis.get('content_type', 'unknown'),
        subject            = analysis.get('subject', '')[:220],
        audience           = analysis.get('audience', 'General'),
        data_richness      = analysis.get('data_richness', 'unknown'),
        narrative_arc      = analysis.get('narrative_arc', '')[:220],
        key_facts          = json.dumps(key_facts_data, indent=2)[:2000],
        slide_plan_summary = slide_plan_summary[:3500],
        slide_previews     = slide_previews_text[:5000],
        html_excerpt       = html[:4000],
        html_size          = len(html),
        slide_count        = html.count('<section'),
        known_issues       = "; ".join(issues) if issues else "None detected",
    )

    try:
        raw = call_json(prompt, key="critic", max_tokens=6000)
    except Exception as e:
        print(f"  [Critic] LLM failed: {e} — deterministic fallback")
        n    = len(issues)
        base = max(4.0, 9.0 - n * 1.2)
        raw  = {
            "dimension_scores": {
                "data_accuracy":    base,
                "visual_quality":   base - 0.5,
                "insight_depth":    base,
                "aesthetic_variety":base - 1.0,
                "completeness":     base,
                "layout_integrity": base,
            },
            "dimension_feedback": {d: "LLM unavailable" for d in CriticResult.WEIGHTS},
            "priority_fixes":     issues[:5] or ["Review output manually"],
            "verdict":            f"Deterministic review: {n} structural issue(s) found",
            "slides_to_fix":      [],
        }

    # ── Apply score caps ───────────────────────────────────────────
    raw_scores  = raw.get("dimension_scores", {})
    final_scores = {
        d: min(float(raw_scores.get(d, 5.0)), caps[d])
        for d in CriticResult.WEIGHTS
    }

    # ── PPTX override: unified theme is intentional ────────────────
    # The critic was trained to reward visual variety, which conflicts with the
    # intentional single-persona theme we enforce for PPTX.  Override the
    # aesthetic_variety score so the loop is not stuck fighting itself.
    if output_format == "pptx":
        final_scores['aesthetic_variety'] = 9.0
        print("  [Critic] PPTX mode — aesthetic_variety overridden to 9.0 (unified theme is correct)")

    # ── Enrich slides_to_fix ───────────────────────────────────────
    llm_fixes = raw.get("slides_to_fix") or []

    # For PPTX, remove any fix that asks for a persona change — the unified
    # theme is intentional and the designer should not fight it.
    if output_format == "pptx":
        persona_keywords = {'persona', 'background', 'vibrant', 'split', 'infographic', 'editorial'}
        llm_fixes = [
            f for f in llm_fixes
            if not any(kw in (f.get('problem', '') + f.get('fix', '')).lower()
                       for kw in persona_keywords)
        ]

    enriched_fixes = _enrich_fixes(llm_fixes, previews, plan_slides)

    # ── Assemble result ────────────────────────────────────────────
    priority_fixes = issues + [f for f in raw.get("priority_fixes", []) if f not in issues]

    result = CriticResult(
        scores         = final_scores,
        feedback       = raw.get("dimension_feedback", {}),
        priority_fixes = priority_fixes[:6],
        slides_to_fix  = enriched_fixes,
        verdict        = raw.get("verdict", ""),
    )
    result.compute_score()
    result.print_report()
    return result
