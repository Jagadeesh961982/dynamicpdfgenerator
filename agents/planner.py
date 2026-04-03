# agents/planner.py
#
# AGENT 0+1 — CONTENT ANALYZER + NARRATIVE PLANNER
# ══════════════════════════════════════════════════
# NotebookLM-style architecture:
#   Step 1 (Python): Chunk raw text (format-agnostic, no regex assumptions)
#   Step 2 (LLM):    Analyze content — understand what it is, extract facts
#   Step 3 (LLM):    Design N slide stories based on the analysis
#
# Works with ANY input: alerts, logs, topics, questions, CSV, docs, etc.
# The LLM does the understanding — Python only does plumbing.

import re, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call_json
import config


# ══════════════════════════════════════════════════════════════════
#  FORMAT-AGNOSTIC TEXT CHUNKER
#  Splits any text into digestible pieces — no format assumptions
# ══════════════════════════════════════════════════════════════════

def _chunk_text(raw: str, max_chunk_chars: int = 3500) -> list:
    raw = raw.strip()
    if not raw:
        return []
    if len(raw) <= max_chunk_chars:
        return [raw]

    blocks = re.split(r'\n\s*\n', raw)
    chunks, current = [], ""
    for block in blocks:
        if len(current) + len(block) > max_chunk_chars and current:
            chunks.append(current.strip())
            current = block
        else:
            current += "\n\n" + block
    if current.strip():
        chunks.append(current.strip())
    return chunks or [raw[:max_chunk_chars]]


# ══════════════════════════════════════════════════════════════════
#  LLM ANALYZER PROMPT
#  The LLM reads raw text and produces a structured understanding.
#  This replaces all regex parsing — works for any content type.
# ══════════════════════════════════════════════════════════════════

ANALYZER_PROMPT = """You are a content analysis expert. Read the following input carefully and produce a structured analysis.

INPUT TEXT (this may be a sample of a larger document):
{text_sample}

TOTAL INPUT SIZE: {total_chars} characters across {chunk_count} sections.

Your job: Understand what this content is about and extract structured facts for a presentation designer.

Determine ALL of the following:

1. content_type: What kind of content is this?
   Examples: "infrastructure_alerts", "application_logs", "technical_topic", "educational_content",
   "business_report", "research_paper", "how_to_guide", "product_documentation",
   "incident_report", "performance_metrics", "general_knowledge_request", etc.

2. subject: What is this about? (2-3 sentence summary)

3. report_title: A compelling, specific title for a PDF report about this content.

4. report_subtitle: A professional subtitle.

5. audience: Who would read a report about this? (e.g. "SRE Leadership", "Engineering Team",
   "Students", "Business Executives", "General Audience")

6. key_entities: Important names, systems, metrics, hosts, tools, concepts found in the data (up to 15).

7. key_facts: The most important findings — quantitative OR qualitative (up to 20).
   For data-rich input: extract exact numbers, percentages, counts, timestamps.
   For topic/question input: generate the key facts from your own knowledge about the subject.

8. themes: 4-8 major themes/categories that presentation slides could be organized around.
   Each theme should be a distinct angle worth a slide or two.

9. tone: What tone should the report use?
   "urgent" — critical issues, immediate action needed
   "analytical" — deep technical analysis
   "educational" — teaching/explaining concepts
   "executive_summary" — high-level business view
   "informational" — neutral, balanced overview

10. data_richness: How much concrete data is in the input?
    "high" — lots of numbers, metrics, timestamps, specific data points
    "medium" — some data points mixed with narrative
    "low" — mostly conceptual, topic-based, or a question. YOU must enrich with your own knowledge.

CRITICAL RULE for data_richness="low":
If the input is a topic or question (like "tell me about Kubernetes" or "explain machine learning"),
you MUST populate key_facts with REAL, ACCURATE facts from your own knowledge. Include real numbers,
real architecture details, real comparisons — as if you were an expert writing a reference document.

Return ONLY valid JSON (no markdown, no fences):
{{
  "content_type": "...",
  "subject": "...",
  "report_title": "...",
  "report_subtitle": "...",
  "audience": "...",
  "key_entities": ["entity1", "entity2", "..."],
  "key_facts": [
    {{"fact": "Concrete fact or data point", "category": "theme it belongs to", "importance": "high"}},
    {{"fact": "Another fact", "category": "...", "importance": "medium"}},
    ...
  ],
  "themes": ["Theme 1", "Theme 2", "Theme 3", "..."],
  "tone": "analytical",
  "data_richness": "high"
}}"""


# ══════════════════════════════════════════════════════════════════
#  LLM PLANNER PROMPT — UNIVERSAL
#  Works for any content type: alerts, logs, topics, docs, etc.
# ══════════════════════════════════════════════════════════════════

PLANNER_PROMPT = """You are an expert presentation architect who creates NotebookLM-quality slide decks.
You have been given a structured analysis of source content.
Design a {n_slides}-slide PDF report that tells a COMPELLING, SPECIFIC story.

CONTENT ANALYSIS:
{analysis}

RAW SOURCE EXCERPT (for additional context and exact quotes):
{raw_excerpt}

STYLE TARGET: Match NotebookLM quality — each slide must have:
  - A unique, journalistic TITLE (not generic like "Overview" or "Introduction")
  - A specific INSIGHT that would surprise or inform the reader
  - A visual that BEST SHOWS that specific insight
  - Real data, real names, real numbers (from the analysis or from your own knowledge)

VISUAL TYPES you can use (pick the best fit per slide):
  - cover_hero           : large title + 3 preview cards (for slide 1 only)
  - big_number_hero      : huge single stat + context
  - bar_chart_annotated  : bar chart with threshold lines and callouts
  - area_chart_gradient  : area/line chart showing trends over time
  - funnel_diagram       : multi-stage breakdown or flow
  - topology_map         : system/concept topology with colored nodes
  - matrix_table         : comparison grid (e.g. teams x impact, features x products)
  - flap_chart           : oscillation/cycle visualization
  - domino_chain         : cascading cause-effect cards with arrows
  - comparison_panel     : side-by-side comparison panels
  - priority_table       : action table with categorized columns
  - scatter_quadrant     : 2x2 quadrant analysis
  - stat_cards_row       : 4 metric/concept cards in a row
  - timeline_events      : horizontal timeline of key events or milestones
  - concept_diagram      : visual explanation of architecture or workflow
  - info_cards_grid      : grid of information cards with icons

LAYOUT OPTIONS:
  - centered             : visual in center, short context below
  - left_text_right_visual : key insight left, custom visual right
  - full_visual          : data visualization fills most of the slide
  - two_panel            : two equal panels side by side
  - header_plus_grid     : heading + grid of cards/items below

COLOR MOODS:
  - critical_red   : #C0392B accent — urgent, broken, immediate action
  - warning_amber  : #D4880E accent — degraded, at-risk, watch closely
  - info_blue      : #2471A3 accent — informational, educational, context
  - neutral        : #555555 accent — conclusion, summary, recommendations
  - success_green  : #1E8449 accent — positive, achievements, solutions

RULES:
1. Slide 1 MUST be a cover slide that sets the stage with title + 3 preview highlights
2. Final slide MUST be a conclusion/recommendations/key-takeaways slide
3. Each slide should use a DIFFERENT visual_type — variety keeps it engaging
4. If the content analysis has data_richness="high", use EXACT numbers from key_facts
5. If data_richness="low", use YOUR OWN KNOWLEDGE to create rich, accurate content.
   Include real facts, real numbers, real architecture details — not placeholder text.
6. Titles must be SPECIFIC and journalistic, not generic
7. visual_description must be detailed enough for another LLM to draw it from scratch
8. Include the actual data values needed in the "data" field for each slide
9. Every slide must have a clear story_angle — WHY does this slide matter?
10. The "data" field should contain all values the visual designer needs to render the slide

Return ONLY valid JSON (no markdown, no fences):
{{
  "report_title": "{report_title}",
  "report_subtitle": "{report_subtitle}",
  "audience": "{audience}",
  "slides": [
    {{
      "slot": 1,
      "title": "Compelling specific title",
      "subtitle": "Contextual subtitle",
      "story_angle": "Why this slide matters",
      "key_insight": "The one thing the reader should take away",
      "visual_type": "cover_hero",
      "visual_description": "Detailed description of what to render visually",
      "layout_hint": "centered",
      "color_mood": "neutral",
      "data": {{
        "relevant_key": "relevant_value"
      }}
    }},
    ... (continue for all {n_slides} slides)
  ]
}}"""


# ══════════════════════════════════════════════════════════════════
#  FALLBACK PLAN — generic, works for any content
# ══════════════════════════════════════════════════════════════════

def _fallback_plan(analysis: dict) -> dict:
    """Build a minimal plan from the analysis when the planner LLM fails."""
    themes = analysis.get('themes', ['Overview', 'Details', 'Analysis'])
    facts  = analysis.get('key_facts', [])
    title  = analysis.get('report_title', 'Report')
    subtitle = analysis.get('report_subtitle', 'Generated Report')

    slides = [
        {
            'slot': 1,
            'title': title,
            'subtitle': subtitle,
            'story_angle': 'Cover slide: set the stage',
            'key_insight': analysis.get('subject', 'Comprehensive analysis'),
            'visual_type': 'cover_hero',
            'layout_hint': 'centered',
            'color_mood': 'neutral',
            'visual_description': f'Cover with title "{title}", subtitle, and 3 preview cards for top themes.',
            'data': {
                'title': title,
                'subtitle': subtitle,
                'preview_items': [
                    {'label': t, 'sub': 'Key topic'} for t in themes[:3]
                ],
            },
        },
        {
            'slot': 2,
            'title': 'Executive Summary',
            'subtitle': '',
            'story_angle': 'Key metrics and findings at a glance',
            'key_insight': analysis.get('subject', ''),
            'visual_type': 'stat_cards_row',
            'layout_hint': 'full_visual',
            'color_mood': 'info_blue',
            'visual_description': 'Four stat cards showing the most important facts or concepts.',
            'data': {
                'cards': [
                    {'label': f.get('fact', '')[:60], 'category': f.get('category', '')}
                    for f in facts[:4]
                ] if facts else [{'label': 'See analysis', 'category': 'Overview'}],
            },
        },
    ]

    visual_types = ['bar_chart_annotated', 'comparison_panel', 'info_cards_grid',
                    'timeline_events', 'topology_map', 'matrix_table']

    for i, theme in enumerate(themes[:6], 3):
        theme_facts = [f for f in facts if f.get('category', '').lower() == theme.lower()]
        if not theme_facts:
            theme_facts = facts[min(i-3, len(facts)-1):min(i-3+3, len(facts))] if facts else []

        slides.append({
            'slot': i,
            'title': f'Deep Dive: {theme}',
            'subtitle': '',
            'story_angle': f'Detailed analysis of {theme}',
            'key_insight': theme_facts[0].get('fact', f'Analysis of {theme}') if theme_facts else f'Analysis of {theme}',
            'visual_type': visual_types[(i - 3) % len(visual_types)],
            'layout_hint': 'left_text_right_visual',
            'color_mood': ['info_blue', 'warning_amber', 'neutral', 'critical_red', 'success_green', 'info_blue'][(i - 3) % 6],
            'visual_description': f'Visual showing key aspects of {theme} with real data.',
            'data': {
                'theme': theme,
                'facts': [f.get('fact', '') for f in theme_facts[:5]],
            },
        })

    slides.append({
        'slot': len(slides) + 1,
        'title': 'Key Takeaways & Recommendations',
        'subtitle': '',
        'story_angle': 'Actionable conclusions',
        'key_insight': 'Summary of findings and next steps',
        'visual_type': 'priority_table',
        'layout_hint': 'full_visual',
        'color_mood': 'neutral',
        'visual_description': 'Table with key findings, recommendations, and action items.',
        'data': {
            'themes': themes[:6],
            'top_facts': [f.get('fact', '') for f in facts[:5]] if facts else [],
        },
    })

    return {
        'report_title': title,
        'report_subtitle': subtitle,
        'audience': analysis.get('audience', 'General'),
        'slides': slides,
    }


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(raw_data: str) -> dict:
    """Analyze any content and plan slides. No format assumptions."""

    # Step 1: Chunk the input (format-agnostic)
    chunks = _chunk_text(raw_data)
    if not chunks:
        print("  [Planner] WARNING: Empty input")
        return {}

    total_chars = len(raw_data)
    # Build a representative sample: first chunks + last chunk for variety
    if len(chunks) <= 3:
        sample = "\n\n---\n\n".join(chunks)
    else:
        sample = "\n\n---\n\n".join(chunks[:2] + [chunks[len(chunks)//2]] + [chunks[-1]])
    sample = sample[:config.MAX_DATA_CHARS]

    # Step 2: LLM Analyzer — understands the content
    print("  [Planner] Step 1/3: LLM analyzing content...")
    try:
        analysis = call_json(
            ANALYZER_PROMPT.format(
                text_sample=sample[:6000],
                total_chars=total_chars,
                chunk_count=len(chunks),
            ),
            key="analyzer",
            max_tokens=3000,
        )
    except Exception as e:
        print(f"    [Analyzer] LLM failed: {e}")
        analysis = {
            "content_type": "unknown",
            "subject": raw_data[:200],
            "report_title": "Content Analysis Report",
            "report_subtitle": "Auto-Generated Report",
            "audience": "General",
            "key_entities": [],
            "key_facts": [],
            "themes": ["Overview", "Details", "Summary"],
            "tone": "informational",
            "data_richness": "low",
        }

    ct = analysis.get('content_type', 'unknown')
    dr = analysis.get('data_richness', 'unknown')
    n_facts = len(analysis.get('key_facts', []))
    n_themes = len(analysis.get('themes', []))
    print(f"    Content type: {ct} | Data richness: {dr}")
    print(f"    {n_facts} facts extracted | {n_themes} themes identified")
    print(f"    Subject: {analysis.get('subject', '')[:80]}")

    # Step 3: LLM Planner — designs the slide narrative
    print("  [Planner] Step 2/3: LLM designing slide narratives...")
    try:
        plan = call_json(
            PLANNER_PROMPT.format(
                analysis=json.dumps(analysis, indent=2)[:5000],
                raw_excerpt=sample[:2500],
                n_slides=config.N_SLIDES,
                report_title=analysis.get('report_title', 'Report'),
                report_subtitle=analysis.get('report_subtitle', 'Generated Report'),
                audience=analysis.get('audience', 'General'),
            ),
            key="planner",
            max_tokens=8000,
        )
    except Exception as e:
        print(f"    [Planner] LLM failed: {e}")
        plan = {}

    if not plan.get('slides'):
        print("    [Planner] Warning: LLM returned no slides — building fallback plan")
        plan = _fallback_plan(analysis)

    # Attach analysis to the plan so downstream agents can use it
    plan['_analysis'] = analysis
    plan['_raw_sample'] = sample[:2000]
    n = len(plan.get('slides', []))
    print(f"  [Planner] Done — {n} slides planned")
    return plan
