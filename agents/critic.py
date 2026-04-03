# agents/critic.py
#
# AGENT 4 — CRITIC
# ══════════════════
# Content-agnostic quality reviewer.
# Reads the assembled HTML + slide plan + content analysis
# Scores on 5 weighted dimensions (0-10 each)
# Returns: weighted score, per-slide feedback, slides_to_fix list
#
# DIMENSIONS (with weights):
#   data_accuracy   0.30  — content matches source facts / is factually correct
#   visual_quality  0.25  — visuals rendered, no raw markdown, no empty slides
#   insight_depth   0.25  — slides tell specific stories, not generic overviews
#   completeness    0.10  — key topics covered, nothing major missing
#   layout_design   0.10  — spacing, readability, visual hierarchy

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
        bars = {d: "█" * int(s) + "░" * (10 - int(s)) for d, s in self.scores.items()}
        print(f"\n{'═'*62}")
        print(f"  CRITIC SCORE: {self.weighted_score:.2f}/10  "
              f"{'✅ PASS' if self.passed else '❌ RETRY'}")
        print(f"  {self.verdict}")
        print(f"{'─'*62}")
        for d, score in self.scores.items():
            fb = self.feedback.get(d, "")[:60]
            print(f"  {d:<20} {bars[d]} {score:.1f}  {fb}")
        print(f"{'─'*62}")
        if self.priority_fixes:
            print("  Priority fixes:")
            for i, f in enumerate(self.priority_fixes, 1):
                print(f"    {i}. {f}")
        if self.slides_to_fix:
            slots = [str(s.get('slot', '?')) for s in self.slides_to_fix]
            print(f"  Slides to patch next: {', '.join(slots)}")
        print(f"{'═'*62}\n")


CRITIC_PROMPT = """You are a strict quality reviewer for professional PDF presentations.
Review this HTML slide report and score it on 5 dimensions (0.0-10.0 each).

REPORT CONTEXT:
  Content type: {content_type}
  Subject: {subject}
  Target audience: {audience}
  Data richness: {data_richness}

SCORING GUIDE:
  9-10 = NotebookLM quality — specific, visual, insightful, publication-ready
  7-8  = Good — mostly specific, minor generic sections
  5-6  = Mediocre — some placeholder/generic content
  3-4  = Poor — many generic sections, missing data
  1-2  = Unacceptable — almost no real content

DIMENSIONS:
  data_accuracy  — Is the content factually correct? Are real numbers, names, facts used?
                   Or just placeholder values like "X items" / "some systems"?
                   For knowledge-based content: are the facts accurate and specific?
  visual_quality — Are visuals actually rendered? Readable charts OR strong infographic layouts
                   (cards, icons, hierarchy, real data in callouts)? No raw **markdown** in text?
                   No empty slides? Chart.js charts must have real data; infographic slides count
                   equally — do not penalize for skipping generic bar charts when layout is rich.
  insight_depth  — Do slides have SPECIFIC, NAMED insights?
                   Do they tell a concrete story with real examples?
                   Or are they generic overviews that could apply to anything?
  completeness   — Are the major topics/themes covered?
                   Is there a cover, detailed analysis, and conclusion/recommendations?
  layout_design  — Clean spacing? Text not overlapping visuals? Print-ready?
                   Proper font sizes (headings 28-48px, body 14-18px)?

KEY FACTS TO VERIFY AGAINST:
{key_facts}

SLIDE PLAN (what was intended):
{slide_plan_summary}

PER-SLIDE CONTENT PREVIEW:
{slide_previews}

HTML EXCERPT (first 4000 chars):
{html_excerpt}

HTML SIZE: {html_size} chars
SLIDE COUNT: {slide_count}
KNOWN ISSUES: {known_issues}

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
    "data_accuracy": "Specific finding about data accuracy",
    "visual_quality": "Specific finding about visuals",
    "insight_depth": "Specific finding about insight depth",
    "completeness": "Specific finding about completeness",
    "layout_design": "Specific finding about layout"
  }},
  "priority_fixes": [
    "Most important fix — be specific",
    "Second most important fix",
    "Third fix"
  ],
  "verdict": "One sentence overall verdict",
  "slides_to_fix": [
    {{"slot": 5, "problem": "Exact description of what is wrong", "fix": "Specific actionable fix"}},
    {{"slot": 10, "problem": "...", "fix": "..."}}
  ]
}}

RULES for slides_to_fix:
- Only list slides genuinely needing fixes (score <7 or broken visuals)
- Maximum 5 slides
- "problem" must be concrete: "Slide shows generic text instead of specific data"
- "fix" must be actionable: "Use exact values from the content analysis"
- Empty/placeholder slides MUST be in slides_to_fix"""


def _extract_slide_previews(html: str) -> list:
    previews = []
    for m in re.finditer(r'data-slot="(\d+)"[^>]*>(.*?)</section>', html, re.DOTALL):
        slot = int(m.group(1))
        text = re.sub(r'<[^>]+>', ' ', m.group(2))
        text = re.sub(r'\s+', ' ', text).strip()[:200]
        has_svg = '<svg' in m.group(2).lower()
        has_chart = 'new chart(' in m.group(2).lower()
        is_short = len(text.strip()) < 80
        previews.append({
            'slot': slot,
            'preview': text[:150],
            'has_svg': has_svg,
            'has_chart': has_chart,
            'is_short': is_short,
        })
    return previews


def _quick_checks(html: str, plan: dict) -> list:
    issues = []
    if re.search(r'\*\*[^<]{1,60}\*\*', html):
        issues.append("Raw **markdown** bold found in HTML output")

    n_slides = html.count('<section')
    target = config.N_SLIDES
    if n_slides < max(target - 4, 6):
        issues.append(f"Only {n_slides} slides found — expected {target}+")

    if 'placeholder' in html.lower() or 'lorem ipsum' in html.lower():
        issues.append("Placeholder text detected")

    analysis = plan.get('_analysis', {})
    entities = analysis.get('key_entities', [])
    if entities:
        found = sum(1 for e in entities[:8] if e.lower() in html.lower())
        if found < len(entities[:8]) // 3:
            issues.append(f"Only {found}/{len(entities[:8])} key entities found in HTML")

    return issues


def run(html: str, plan: dict) -> CriticResult:
    print("  [Critic] Reviewing report quality...")

    analysis = plan.get('_analysis', {})
    plan_slides = plan.get('slides', [])

    key_facts_list = analysis.get('key_facts', [])
    key_facts = json.dumps({
        'content_type': analysis.get('content_type', 'unknown'),
        'subject': analysis.get('subject', ''),
        'key_entities': analysis.get('key_entities', [])[:10],
        'top_facts': [f.get('fact', '') for f in key_facts_list[:10]],
        'data_richness': analysis.get('data_richness', 'unknown'),
    }, indent=2)[:1500]

    slide_plan_summary = "\n".join(
        f"  Slot {s.get('slot'):2d}: [{s.get('visual_type','?'):20s}] {s.get('title','')[:55]}"
        for s in plan_slides
    )

    slide_previews_data = _extract_slide_previews(html)
    slide_previews_text = "\n".join(
        f"  Slot {p['slot']:2d}: {'[NO SVG] ' if not p['has_svg'] else ''}"
        f"{'[SHORT] ' if p['is_short'] else ''}{p['preview'][:120]}"
        for p in slide_previews_data
    )

    known_issues = _quick_checks(html, plan)

    prompt = CRITIC_PROMPT.format(
        content_type       = analysis.get('content_type', 'unknown'),
        subject            = analysis.get('subject', '')[:200],
        audience           = analysis.get('audience', 'General'),
        data_richness      = analysis.get('data_richness', 'unknown'),
        key_facts          = key_facts,
        slide_plan_summary = slide_plan_summary[:1500],
        slide_previews     = slide_previews_text[:2000],
        html_excerpt       = html[:4000],
        html_size          = len(html),
        slide_count        = html.count('<section'),
        known_issues       = "; ".join(known_issues) if known_issues else "None detected",
    )

    try:
        raw = call_json(prompt, key="critic")
    except Exception as e:
        print(f"  [Critic] LLM failed: {e} — using deterministic score")
        n = len(known_issues)
        base = max(4.0, 9.0 - n * 1.5)
        raw = {
            "dimension_scores":   {d: base for d in CriticResult.WEIGHTS},
            "dimension_feedback": {d: "LLM unavailable — deterministic check" for d in CriticResult.WEIGHTS},
            "priority_fixes":     known_issues[:3] or ["Review output manually"],
            "verdict":            f"Deterministic score ({n} issues detected)",
        }

    llm_fixes = raw.get("slides_to_fix") or []
    llm_slots = {int(s.get("slot", 0)) for s in llm_fixes}
    for p in slide_previews_data:
        if p['is_short'] and p['slot'] not in llm_slots:
            llm_fixes.append({
                "slot":    p['slot'],
                "problem": f"Slide {p['slot']} appears empty or too short",
                "fix":     "Re-render with full visual and actual content",
            })
            llm_slots.add(p['slot'])

    result = CriticResult(
        scores         = raw.get("dimension_scores", {}),
        feedback       = raw.get("dimension_feedback", {}),
        priority_fixes = raw.get("priority_fixes", []),
        slides_to_fix  = llm_fixes[:5],
        verdict        = raw.get("verdict", ""),
    )
    result.compute_score()

    if known_issues:
        result.weighted_score = min(result.weighted_score, 6.5)
        result.passed = result.weighted_score >= config.PASS_THRESHOLD
        result.priority_fixes = known_issues + result.priority_fixes

    result.print_report()
    return result
