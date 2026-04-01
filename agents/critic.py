# agents/critic.py
#
# AGENT 4 — CRITIC
# ══════════════════
# Reads the assembled HTML + slide plan + parsed facts
# Scores on 5 weighted dimensions (0-10 each)
# Returns: weighted score, per-slide feedback, slides_to_fix list
#
# DIMENSIONS (with weights):
#   data_accuracy   0.30  — exact numbers match facts, real hostnames, real timestamps
#   visual_quality  0.25  — charts readable, no raw markdown, no empty slides
#   insight_depth   0.25  — slides tell specific stories, not generic overviews
#   completeness    0.10  — key topics covered (not missing major issues)
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


CRITIC_PROMPT = """You are a strict quality reviewer for executive SRE presentations.
Review this HTML slide report and score it on 5 dimensions (0.0–10.0 each).

SCORING GUIDE:
  9-10 = NotebookLM quality — specific, visual, insightful
  7-8  = Good — mostly specific, minor generic sections
  5-6  = Mediocre — some placeholder/generic content
  3-4  = Poor — many generic sections, missing data
  1-2  = Unacceptable — almost no real data used

DIMENSIONS:
  data_accuracy  — Are EXACT numbers from the facts used? Real hostnames? Real timestamps?
                   Or just placeholder values like "X alerts" / "some hosts"?
  visual_quality — Are visuals actually rendered (SVG present)? Readable?
                   No raw **markdown** in text? No empty slides? Charts have real data?
  insight_depth  — Do slides have SPECIFIC, NAMED insights?
                   ("Kafka lag: 785,744 — 157× above threshold") vs generic
                   ("High Kafka lag observed")? Do slides tell a story?
  completeness   — Are the major issues covered (Kafka, disk, CPU, Redis, flapping)?
                   Is there a cover, stats, deep dives, recommendations?
  layout_design  — Clean spacing? Text not overlapping SVG? Print-ready?
                   Proper font sizes (headings 28-48px, body 14-18px)?

PARSED FACTS TO VERIFY AGAINST:
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
- "problem" must be concrete: "Slide shows 'X alerts' instead of exact 342"
- "fix" must be actionable: "Use exact value 342 from facts. Show bar chart with 9 time points."
- Empty/placeholder slides MUST be in slides_to_fix"""


def _extract_slide_previews(html: str) -> list:
    """Extract text preview of each slide to help critic identify issues."""
    previews = []
    for m in re.finditer(r'data-slot="(\d+)"[^>]*>(.*?)</section>', html, re.DOTALL):
        slot = int(m.group(1))
        text = re.sub(r'<[^>]+>', ' ', m.group(2))
        text = re.sub(r'\s+', ' ', text).strip()[:200]
        has_svg = '<svg' in m.group(2).lower()
        is_short = len(text.strip()) < 80
        previews.append({
            'slot': slot,
            'preview': text[:150],
            'has_svg': has_svg,
            'is_short': is_short,
        })
    return previews


def _quick_checks(html: str, facts: dict) -> list:
    """Fast deterministic checks before LLM review."""
    issues = []
    if re.search(r'\*\*[^<]{1,60}\*\*', html):
        issues.append("Raw **markdown** bold found in HTML output")
    if html.count('<section') < 8:
        n = html.count('<section')
        issues.append(f"Only {n} slides found — expected 10+")
    if 'placeholder' in html.lower() or 'lorem ipsum' in html.lower():
        issues.append("Placeholder text detected")
    # Check for actual numbers from facts
    total = facts.get('total_alerts', 0)
    if total and str(total) not in html:
        issues.append(f"Total alert count ({total}) not found in HTML")
    return issues


def run(html: str, plan: dict) -> CriticResult:
    print("  [Critic] Reviewing report quality...")

    facts     = plan.get('_parsed', {})
    plan_slides = plan.get('slides', [])

    key_facts = json.dumps({
        'total_alerts':   facts.get('total'),
        'firing':         facts.get('firing'),
        'kafka_lag_max':  facts.get('kafka_max_lag'),
        'cpu_max':        facts.get('cpu_max'),
        'critical_disk':  facts.get('critical_disk'),
        'redis_nodes':    facts.get('redis_nodes'),
        'duration':       facts.get('duration'),
        'time_start':     facts.get('time_start'),
        'time_end':       facts.get('time_end'),
    }, indent=2)[:1000]

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

    known_issues = _quick_checks(html, facts)

    prompt = CRITIC_PROMPT.format(
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

    # Merge LLM slides_to_fix with deterministically flagged short slides
    llm_fixes   = raw.get("slides_to_fix") or []
    llm_slots   = {int(s.get("slot", 0)) for s in llm_fixes}
    for p in slide_previews_data:
        if p['is_short'] and p['slot'] not in llm_slots:
            llm_fixes.append({
                "slot":    p['slot'],
                "problem": f"Slide {p['slot']} appears empty or too short",
                "fix":     "Re-render with full visual and actual data",
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

    # Hard cap if known deterministic issues found
    if known_issues:
        result.weighted_score = min(result.weighted_score, 6.5)
        result.passed = result.weighted_score >= config.PASS_THRESHOLD
        result.priority_fixes = known_issues + result.priority_fixes

    result.print_report()
    return result
