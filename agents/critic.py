# agents/critic.py
#
# AGENT 4 — CRITIC
# ═════════════════
# Quality reviewer. Scores on 5 weighted dimensions.
# Returns structured feedback + slides_to_fix with enough context
# for the designer to actually fix the problem (not just redo blindly).
#
# KEY IMPROVEMENTS:
#   1. Passes previous slide HTML excerpts in feedback so designer
#      can diff and improve — not just regenerate.
#   2. Icon check: verifies [[icon:...]] were substituted (no raw placeholders).
#   3. Slide content length check catches empty/short slides reliably.
#   4. Scoring capped when structural issues found.
#   5. Deterministic fallback gives reasonable scores without LLM.

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
        "data_accuracy":  0.30,
        "visual_quality": 0.25,
        "insight_depth":  0.25,
        "completeness":   0.10,
        "layout_design":  0.10,
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
        bars = {d: "█" * int(s) + "░" * (10 - int(s))
                for d, s in self.scores.items()}
        sep = "═" * 64
        print(f"\n{sep}")
        status = "✅ PASS" if self.passed else "❌ RETRY"
        print(f"  CRITIC SCORE: {self.weighted_score:.2f}/10  {status}")
        print(f"  {self.verdict}")
        print(f"{'─'*64}")
        for d, score in self.scores.items():
            fb = self.feedback.get(d, "")[:55]
            print(f"  {d:<20} {bars.get(d,''):<10} {score:.1f}  {fb}")
        print(f"{'─'*64}")
        if self.priority_fixes:
            print("  Priority fixes:")
            for i, fx in enumerate(self.priority_fixes, 1):
                print(f"    {i}. {fx}")
        if self.slides_to_fix:
            slots = [str(s.get('slot', '?')) for s in self.slides_to_fix]
            print(f"  Slides to patch: {', '.join(slots)}")
        print(f"{sep}\n")


# ══════════════════════════════════════════════════════════════════
#  SLIDE CONTENT EXTRACTOR
# ══════════════════════════════════════════════════════════════════

def _extract_slide_previews(html: str) -> list[dict]:
    previews = []
    for m in re.finditer(r'data-slot="(\d+)"[^>]*>(.*?)</section>', html, re.DOTALL):
        slot = int(m.group(1))
        body = m.group(2)
        text = re.sub(r'<[^>]+>', ' ', body)
        text = re.sub(r'\s+', ' ', text).strip()
        has_chart   = 'new chart(' in body.lower()
        has_svg     = '<svg' in body.lower()
        has_icon    = has_svg and 'viewBox' in body  # inline SVG icon check
        is_short    = len(text.strip()) < 100
        has_stub    = '[[icon:' in body  # unsubstituted placeholder (error)
        previews.append({
            'slot':      slot,
            'preview':   text[:200],
            'char_count': len(text),
            'has_chart': has_chart,
            'has_svg':   has_svg,
            'has_icon':  has_icon,
            'is_short':  is_short,
            'has_stub':  has_stub,
        })
    return previews


# ══════════════════════════════════════════════════════════════════
#  QUICK STRUCTURAL CHECKS
# ══════════════════════════════════════════════════════════════════

def _quick_checks(html: str, plan: dict) -> list[str]:
    issues = []

    # Raw markdown in output
    if re.search(r'\*\*[^<]{1,60}\*\*', html):
        issues.append("Raw **markdown** bold found in HTML — use <strong> tags")

    # Unsubstituted icon placeholders
    if '[[icon:' in html:
        issues.append("Unsubstituted [[icon:...]] placeholders found in HTML")

    # Slide count vs target
    n_slides = html.count('<section')
    target   = config.N_SLIDES
    if n_slides < max(target - 4, 6):
        issues.append(f"Only {n_slides} slides found, expected {target}+")

    # Placeholder text
    if 'lorem ipsum' in html.lower() or 'placeholder' in html.lower():
        issues.append("Placeholder text detected in slides")

    # Key entity coverage
    analysis = plan.get('_analysis', {})
    entities = analysis.get('key_entities', [])
    if entities:
        found = sum(1 for e in entities[:10] if e.lower() in html.lower())
        if found < max(1, len(entities[:10]) // 4):
            issues.append(
                f"Only {found}/{len(entities[:10])} key entities visible in output"
            )

    return issues


# ══════════════════════════════════════════════════════════════════
#  CRITIC PROMPT
# ══════════════════════════════════════════════════════════════════

CRITIC_PROMPT = """You are a strict quality reviewer for professional PDF presentations.
Review this HTML slide report and score it on 5 dimensions (0.0–10.0 each).

REPORT CONTEXT:
  Content type:   {content_type}
  Subject:        {subject}
  Target audience:{audience}
  Data richness:  {data_richness}
  Narrative arc:  {narrative_arc}

SCORING GUIDE:
  9-10 = NotebookLM quality — specific, visual, insightful, publication-ready
  7-8  = Good — mostly specific, minor issues
  5-6  = Mediocre — some generic or placeholder content
  3-4  = Poor — many generic sections, missing real data
  1-2  = Unacceptable — almost no real content

DIMENSIONS:
  data_accuracy  — Are real numbers, names, facts used? No "X items" placeholders?
  visual_quality — Rich visuals? Icons present? Cards with hierarchy? No plain text walls?
                   Inline SVG icons count as good. Chart.js charts count. CSS infographics count.
  insight_depth  — Specific, named insights? Real examples? Or generic overviews?
  completeness   — Cover + analysis + conclusion? Major topics covered?
  layout_design  — Clean spacing? Proper font sizes? Print-ready? No overlapping text?

KEY FACTS TO VERIFY:
{key_facts}

SLIDE PLAN (intended):
{slide_plan_summary}

PER-SLIDE CONTENT PREVIEW:
{slide_previews}

HTML EXCERPT (first 3000 chars):
{html_excerpt}

HTML SIZE: {html_size} chars
SLIDE COUNT: {slide_count}
STRUCTURAL ISSUES DETECTED: {known_issues}

Return ONLY this JSON (no markdown):
{{
  "dimension_scores": {{
    "data_accuracy": 8.5,
    "visual_quality": 7.0,
    "insight_depth": 8.0,
    "completeness": 9.0,
    "layout_design": 7.5
  }},
  "dimension_feedback": {{
    "data_accuracy": "Specific finding",
    "visual_quality": "Specific finding",
    "insight_depth": "Specific finding",
    "completeness": "Specific finding",
    "layout_design": "Specific finding"
  }},
  "priority_fixes": [
    "Most important fix — be specific",
    "Second fix",
    "Third fix"
  ],
  "verdict": "One sentence overall verdict",
  "slides_to_fix": [
    {{
      "slot": 5,
      "problem": "Specific problem description",
      "fix": "Specific actionable fix instruction",
      "prev_content_hint": "What's currently there in 1 sentence"
    }}
  ]
}}

RULES for slides_to_fix:
  - Only list slides genuinely needing fixes (dimension score <7 or structural issue)
  - Maximum 5 slides
  - "problem" must be concrete: "Shows generic bullet points instead of real service names"
  - "fix" must be actionable: "Use the 3 hostnames from the data field to populate host cards"
  - Empty/short slides MUST be listed
  - "prev_content_hint" helps designer understand what to keep and what to change"""


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(html: str, plan: dict) -> CriticResult:
    print("  [Critic] Reviewing report quality...")

    analysis    = plan.get('_analysis', {})
    plan_slides = plan.get('slides', [])

    key_facts_data = {
        'content_type':  analysis.get('content_type', 'unknown'),
        'subject':       analysis.get('subject', ''),
        'key_entities':  analysis.get('key_entities', [])[:12],
        'top_facts':     [f.get('fact', '') for f in analysis.get('key_facts', [])[:12]],
        'data_richness': analysis.get('data_richness', 'unknown'),
    }

    slide_plan_summary = "\n".join(
        f"  Slot {s.get('slot'):2d}: [{s.get('visual_type','?'):22s}] {s.get('title','')[:52]}"
        for s in plan_slides
    )

    slide_previews_data = _extract_slide_previews(html)
    slide_previews_text = "\n".join(
        f"  Slot {p['slot']:2d}: "
        f"{'[SHORT] ' if p['is_short'] else ''}"
        f"{'[NO-ICON] ' if not p['has_icon'] else ''}"
        f"{'[STUB-ICON] ' if p['has_stub'] else ''}"
        f"{'[CHART] ' if p['has_chart'] else ''}"
        f"{p['preview'][:150]}"
        for p in slide_previews_data
    )

    known_issues = _quick_checks(html, plan)

    prompt = CRITIC_PROMPT.format(
        content_type       = analysis.get('content_type', 'unknown'),
        subject            = analysis.get('subject', '')[:200],
        audience           = analysis.get('audience', 'General'),
        data_richness      = analysis.get('data_richness', 'unknown'),
        narrative_arc      = analysis.get('narrative_arc', '')[:200],
        key_facts          = json.dumps(key_facts_data, indent=2)[:1800],
        slide_plan_summary = slide_plan_summary[:3000],
        slide_previews     = slide_previews_text[:4000],
        html_excerpt       = html[:3000],
        html_size          = len(html),
        slide_count        = html.count('<section'),
        known_issues       = "; ".join(known_issues) if known_issues else "None",
    )

    try:
        raw = call_json(prompt, key="critic", max_tokens=3000)
    except Exception as e:
        print(f"  [Critic] LLM failed: {e} — deterministic fallback")
        n   = len(known_issues)
        base = max(4.0, 9.0 - n * 1.5)
        raw = {
            "dimension_scores":   {d: base for d in CriticResult.WEIGHTS},
            "dimension_feedback": {d: "LLM unavailable" for d in CriticResult.WEIGHTS},
            "priority_fixes":     known_issues[:3] or ["Review output manually"],
            "verdict":            f"Deterministic score: {n} structural issues",
            "slides_to_fix":      [],
        }

    # Merge LLM slides_to_fix with deterministic catches
    llm_fixes  = raw.get("slides_to_fix") or []
    llm_slots  = {int(s.get("slot", 0)) for s in llm_fixes}

    for p in slide_previews_data:
        if p['is_short'] and p['slot'] not in llm_slots:
            llm_fixes.append({
                "slot":              p['slot'],
                "problem":           f"Slide {p['slot']} is empty or too short ({p['char_count']} chars of text)",
                "fix":               "Re-render with full visual content and real data from the plan",
                "prev_content_hint": p['preview'][:100],
            })
            llm_slots.add(p['slot'])
        if p['has_stub'] and p['slot'] not in llm_slots:
            llm_fixes.append({
                "slot":              p['slot'],
                "problem":           f"Slide {p['slot']} has unsubstituted [[icon:...]] placeholder text",
                "fix":               "Use the correct [[icon:NAME:SIZE:COLOR]] syntax — Python will substitute it",
                "prev_content_hint": p['preview'][:100],
            })
            llm_slots.add(p['slot'])

    result = CriticResult(
        scores         = raw.get("dimension_scores", {d: 6.0 for d in CriticResult.WEIGHTS}),
        feedback       = raw.get("dimension_feedback", {}),
        priority_fixes = raw.get("priority_fixes", []),
        slides_to_fix  = llm_fixes[:5],
        verdict        = raw.get("verdict", ""),
    )
    result.compute_score()

    # Cap score if structural issues found
    if known_issues:
        cap = 6.5 if len(known_issues) == 1 else 5.5
        result.weighted_score = min(result.weighted_score, cap)
        result.passed         = result.weighted_score >= config.PASS_THRESHOLD
        result.priority_fixes = known_issues + result.priority_fixes

    result.print_report()
    return result