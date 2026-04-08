# # agents/planner.py
# #
# # AGENT 0+1 — CONTENT ANALYZER + NARRATIVE PLANNER
# # ══════════════════════════════════════════════════
# # NotebookLM-style: two-pass for large inputs.
# #
# # Pass 1 (Analyzer): LLM reads chunks and extracts structured facts.
# #                    For large files: summarize each chunk, then synthesize.
# #                    For topic/question inputs: LLM enriches from own knowledge.
# #
# # Pass 2 (Planner):  LLM designs N slide narratives from the analysis.
# #                    Uses DESIGN_SEED to vary layouts every run.
# #                    Each run with same data produces a different visual narrative.

# import json, re, sys
# from pathlib import Path
# sys.path.insert(0, str(Path(__file__).parent.parent))
# from utils.llm import call_json
# import config


# # ══════════════════════════════════════════════════════════════════
# #  CHUNKER — format-agnostic, no regex assumptions
# # ══════════════════════════════════════════════════════════════════

# def _chunk_text(raw: str, max_chunk_chars: int = 4000) -> list[str]:
#     raw = raw.strip()
#     if not raw:
#         return []
#     if len(raw) <= max_chunk_chars:
#         return [raw]

#     blocks   = re.split(r'\n\s*\n', raw)
#     chunks, current = [], ""
#     for block in blocks:
#         if len(current) + len(block) > max_chunk_chars and current:
#             chunks.append(current.strip())
#             current = block
#         else:
#             current += "\n\n" + block
#     if current.strip():
#         chunks.append(current.strip())
#     return chunks or [raw[:max_chunk_chars]]


# # ══════════════════════════════════════════════════════════════════
# #  CHUNK SUMMARIZER — condenses large inputs before analysis
# #  FIX: The original only sent 4 chunks to the analyzer.
# #       Now we summarize every chunk and synthesize them all.
# # ══════════════════════════════════════════════════════════════════

# CHUNK_SUMMARY_PROMPT = """You are summarizing a section of a larger document for a presentation designer.
# Extract and list ONLY concrete facts, numbers, names, events, and patterns from this section.
# No prose. No headers. Just a bullet list of facts.

# SECTION:
# {chunk}

# Return JSON:
# {{
#   "facts": ["fact 1", "fact 2", "..."],
#   "entities": ["entity1", "entity2"],
#   "anomalies": ["unusual thing 1"]
# }}"""


# def _summarize_chunks(chunks: list[str]) -> list[dict]:
#     """Summarize each chunk into structured facts. Used for large inputs."""
#     summaries = []
#     for i, chunk in enumerate(chunks):
#         print(f"    Summarizing chunk {i+1}/{len(chunks)}...")
#         try:
#             s = call_json(
#                 CHUNK_SUMMARY_PROMPT.format(chunk=chunk[:3500]),
#                 key="analyzer",
#                 max_tokens=1500,
#             )
#             summaries.append(s)
#         except Exception as e:
#             print(f"    Chunk {i+1} summary failed: {e} — using raw text")
#             summaries.append({
#                 "facts": [chunk[:300]],
#                 "entities": [],
#                 "anomalies": [],
#             })
#     return summaries


# # ══════════════════════════════════════════════════════════════════
# #  ANALYZER PROMPT
# # ══════════════════════════════════════════════════════════════════

# ANALYZER_PROMPT = """You are a world-class content analyst preparing source material for a NotebookLM-quality PDF report.
# Deeply understand the input and extract everything a presentation designer needs.

# INPUT TEXT:
# {text_sample}

# {chunk_summaries_section}

# TOTAL INPUT: {total_chars} characters across {chunk_count} sections.

# Determine ALL of the following with maximum specificity:

# 1. content_type — What kind of content is this?
#    E.g.: "infrastructure_alerts", "application_logs", "kubernetes_tutorial",
#    "aws_architecture", "incident_report", "performance_metrics",
#    "research_paper", "business_report", "how_to_guide", "general_topic"

# 2. subject — 2-3 sentence summary of exactly what this content is about.

# 3. report_title — A compelling, specific, journalistic title (NOT generic).
#    BAD: "Kubernetes Overview"
#    GOOD: "Kubernetes at Scale: Architecture, Failures & Recovery Patterns"

# 4. report_subtitle — A professional subtitle with context (audience, date range, etc.)

# 5. audience — Who reads this? Be specific.
#    E.g.: "Senior SRE Team", "Platform Engineering Leads", "Kubernetes Beginners",
#    "Cloud Architecture Decision Makers", "DevOps Engineers"

# 6. key_entities — Named items found: hosts, services, tools, concepts, companies (up to 20).

# 7. key_facts — The most important facts. MUST include exact numbers when available.
#    For data-rich input (logs/alerts/metrics): extract REAL values, timestamps, counts.
#    For topic/educational input: generate REAL authoritative facts from your knowledge.
#    BAD: "Many errors occurred"
#    GOOD: "1,847 critical alerts fired between 03:00-07:00 UTC, 73% from storage cluster"
#    BAD: "Kubernetes manages containers"
#    GOOD: "Kubernetes orchestrates containers via 3 control plane components: API server, etcd, scheduler. etcd stores all cluster state as key-value pairs."

# 8. themes — 5-8 distinct angles/chapters for the presentation. Each should be a specific
#    story arc, not a generic category.
#    BAD: ["Overview", "Details", "Conclusion"]
#    GOOD: ["The 3AM Cascading Failure Chain", "etcd Saturation as Root Cause",
#           "Cross-Zone Dependency Mapping", "Recovery Playbook"]

# 9. tone — "urgent" | "analytical" | "educational" | "executive_summary" | "informational"

# 10. data_richness — "high" | "medium" | "low"
#     high = real numbers, real timestamps, real names throughout
#     low  = topic/question input — YOU must fill key_facts with real authoritative knowledge

# 11. narrative_arc — One sentence describing the story this report tells.
#     E.g.: "A cascading storage failure that started as a misconfiguration and escalated into a 4-hour outage affecting 3 services."

# CRITICAL for data_richness="low":
# If the input is a question or topic (e.g. "explain AWS", "make a PDF on ML"),
# you MUST populate key_facts with 15-20 REAL, ACCURATE, SPECIFIC facts from your knowledge.
# Include real numbers, real names, real architecture details. Be an expert, not a generalist.

# Return ONLY valid JSON:
# {{
#   "content_type": "...",
#   "subject": "...",
#   "report_title": "...",
#   "report_subtitle": "...",
#   "audience": "...",
#   "key_entities": ["entity1", ...],
#   "key_facts": [
#     {{"fact": "Specific fact with real data", "category": "theme it belongs to", "importance": "high"}},
#     ...
#   ],
#   "themes": ["Theme 1", "Theme 2", ...],
#   "tone": "analytical",
#   "data_richness": "high",
#   "narrative_arc": "..."
# }}"""


# # ══════════════════════════════════════════════════════════════════
# #  PLANNER PROMPT — uses DESIGN_SEED for visual variety
# # ══════════════════════════════════════════════════════════════════

# PLANNER_PROMPT = """You are an expert presentation architect creating a NotebookLM-quality PDF.
# Design {n_slides} slides that tell a SPECIFIC, VISUAL, COMPELLING story.

# DESIGN SEED: {design_seed}
# Use this seed to make creative layout and color choices. Different seeds = different aesthetics.
# High seed (>5000): bold, asymmetric, dramatic. Low seed (<3000): refined, structured, minimal.
# Mid seed: balanced editorial. Vary your visual type choices based on this seed.

# CONTENT ANALYSIS:
# {analysis}

# RAW SOURCE EXCERPT (for additional context):
# {raw_excerpt}

# AVAILABLE ICON NAMES (use ONLY these exact names in the "icon" fields):
# {icon_list}

# VISUAL TYPES — choose the best fit, vary them across slides:
#   cover_hero           → Full-bleed cover: giant title + 3 preview insight cards
#   big_number_hero      → One massive stat fills the slide (text-9xl, context below)
#   stat_cards_row       → 4 equal metric/concept cards in a grid
#   bar_chart_annotated  → Chart.js bar chart with callout annotations
#   area_chart_gradient  → Chart.js area/line chart showing trend over time
#   timeline_events      → Horizontal timeline of key events with milestones
#   topology_map         → CSS node/card diagram — system architecture or concept map
#   matrix_table         → HTML comparison table (teams × dimensions, options × criteria)
#   domino_chain         → Horizontal cause-effect cards with arrows between them
#   comparison_panel     → Two equal panels, each with chart or stats inside
#   priority_table       → Styled action table: Item | Priority | Action columns
#   scatter_quadrant     → 2×2 grid (Impact vs Effort, Risk vs Value, etc.)
#   funnel_diagram       → Funnel/pipeline showing stages with counts
#   info_cards_grid      → 2×2 or 3×2 grid of rich content cards with icons
#   concept_diagram      → 3-6 step workflow with connectors (architecture, process)
#   two_column_bullets   → Left: key insight panel; Right: bullet list with icons
#   callout_hero         → Large pull-quote or key finding with supporting stats below

# COLOR MOODS:
#   critical_red    → #C0392B accent (urgent, broken, failure)
#   warning_amber   → #D4880E accent (degraded, at-risk)
#   info_blue       → #2471A3 accent (informational, educational)
#   success_green   → #1E8449 accent (achievements, solutions, health)
#   neutral_slate   → #4A5568 accent (summary, conclusion, overview)
#   deep_purple     → #6B46C1 accent (innovation, AI, future)
#   teal_focus      → #0D9488 accent (process, flow, systems)

# RULES — read carefully:
# 1. Slide 1 MUST be cover_hero. Final slide MUST be a conclusion/takeaways slide.
# 2. Use at LEAST 6 different visual_types across all slides.
# 3. Titles must be JOURNALISTIC and SPECIFIC — not generic labels.
#    BAD: "System Overview" | GOOD: "Why Three Services Went Dark at 3AM"
# 4. The "data" field must contain ALL values the designer needs to render the slide.
#    Include real numbers, real names, real labels — never say "see analysis".
# 5. story_angle must explain WHY this slide matters to the audience.
# 6. For "icon" fields in data: use ONLY names from the AVAILABLE ICON NAMES list above.
# 7. Each slide needs a unique visual_type — minimize repeats.
# 8. "visual_description" must be detailed enough for a designer to render from scratch.
# 9. If data_richness is "low", use your knowledge to create REAL data values in the data field.

# Return ONLY valid JSON:
# {{
#   "report_title": "...",
#   "report_subtitle": "...",
#   "audience": "...",
#   "slides": [
#     {{
#       "slot": 1,
#       "title": "Compelling specific title",
#       "subtitle": "Contextual subtitle",
#       "story_angle": "Why this slide matters",
#       "key_insight": "The one thing the reader takes away",
#       "visual_type": "cover_hero",
#       "visual_description": "Detailed visual description",
#       "layout_hint": "centered | left_text_right_visual | full_visual | header_plus_grid",
#       "color_mood": "neutral_slate",
#       "data": {{
#         "key": "value — real data, real numbers"
#       }}
#     }}
#   ]
# }}"""


# # ══════════════════════════════════════════════════════════════════
# #  FALLBACK PLAN
# # ══════════════════════════════════════════════════════════════════

# def _fallback_plan(analysis: dict) -> dict:
#     themes = analysis.get('themes', ['Overview', 'Details', 'Analysis', 'Summary'])
#     facts  = analysis.get('key_facts', [])
#     title  = analysis.get('report_title', 'Report')
#     subtitle = analysis.get('report_subtitle', 'Generated Report')

#     vt_cycle = [
#         'stat_cards_row', 'bar_chart_annotated', 'info_cards_grid',
#         'timeline_events', 'topology_map', 'concept_diagram', 'priority_table',
#     ]
#     cm_cycle = [
#         'info_blue', 'warning_amber', 'neutral_slate',
#         'critical_red', 'success_green', 'deep_purple', 'teal_focus',
#     ]

#     slides = [{
#         'slot': 1,
#         'title': title,
#         'subtitle': subtitle,
#         'story_angle': 'Set the stage with key highlights',
#         'key_insight': analysis.get('subject', ''),
#         'visual_type': 'cover_hero',
#         'visual_description': f'Cover with title "{title}", subtitle, and 3 preview theme cards.',
#         'layout_hint': 'centered',
#         'color_mood': 'neutral_slate',
#         'data': {
#             'title': title,
#             'subtitle': subtitle,
#             'preview_cards': [
#                 {'title': t, 'description': 'Key topic', 'icon': 'lightbulb'}
#                 for t in themes[:3]
#             ],
#         },
#     }]

#     for i, theme in enumerate(themes[:8], 2):
#         tf = [f for f in facts if f.get('category', '').lower() == theme.lower()]
#         if not tf:
#             tf = facts[max(0, i-2):min(i+1, len(facts))]
#         slides.append({
#             'slot': i,
#             'title': theme,
#             'subtitle': '',
#             'story_angle': f'Analysis of {theme}',
#             'key_insight': tf[0].get('fact', f'Key insights about {theme}') if tf else f'Key insights about {theme}',
#             'visual_type': vt_cycle[(i - 2) % len(vt_cycle)],
#             'visual_description': f'Visual showing key aspects of {theme} with real data.',
#             'layout_hint': 'left_text_right_visual',
#             'color_mood': cm_cycle[(i - 2) % len(cm_cycle)],
#             'data': {'theme': theme, 'facts': [f.get('fact', '') for f in tf[:5]]},
#         })

#     slides.append({
#         'slot': len(slides) + 1,
#         'title': 'Key Takeaways & Next Steps',
#         'subtitle': '',
#         'story_angle': 'Actionable conclusions',
#         'key_insight': 'Summary of findings and recommended actions',
#         'visual_type': 'priority_table',
#         'visual_description': 'Action table with key findings and next steps.',
#         'layout_hint': 'full_visual',
#         'color_mood': 'neutral_slate',
#         'data': {'themes': themes[:6], 'top_facts': [f.get('fact', '') for f in facts[:5]]},
#     })

#     return {
#         'report_title': title,
#         'report_subtitle': subtitle,
#         'audience': analysis.get('audience', 'General'),
#         'slides': slides,
#     }


# # ══════════════════════════════════════════════════════════════════
# #  PUBLIC API
# # ══════════════════════════════════════════════════════════════════

# def run(raw_data: str) -> dict:
#     """
#     Two-pass pipeline:
#       Pass 1: Analyze content (with chunk summarization for large inputs)
#       Pass 2: Plan slide narrative (with design seed for variety)
#     """
#     from utils.icons import get_all_icon_names, suggest_icons_for_topic

#     chunks      = _chunk_text(raw_data)
#     total_chars = len(raw_data)

#     if not chunks:
#         print("  [Planner] WARNING: Empty input")
#         return {}

#     # ── PASS 1A: For large inputs, pre-summarize each chunk ───────
#     chunk_summaries_section = ""
#     if len(chunks) > 4:
#         print(f"  [Planner] Large input ({len(chunks)} chunks) — pre-summarizing all chunks...")
#         summaries = _summarize_chunks(chunks)
#         all_facts    = []
#         all_entities = []
#         all_anomalies = []
#         for s in summaries:
#             all_facts.extend(s.get('facts', []))
#             all_entities.extend(s.get('entities', []))
#             all_anomalies.extend(s.get('anomalies', []))
#         # Deduplicate
#         all_entities = list(dict.fromkeys(all_entities))[:30]
#         chunk_summaries_section = (
#             f"\nCHUNK SUMMARIES (from {len(chunks)} sections of the full document):\n"
#             + json.dumps({
#                 "total_facts_extracted": len(all_facts),
#                 "sample_facts": all_facts[:40],
#                 "all_entities": all_entities[:25],
#                 "anomalies": all_anomalies[:15],
#             }, indent=2)[:4000]
#         )
#         # Use first + last chunk as text sample; summaries carry the rest
#         sample = chunks[0][:3000] + "\n\n---\n\n" + chunks[-1][:2000]
#     else:
#         # Small input: just send all chunks directly
#         sample = "\n\n---\n\n".join(chunks)[:6000]
#         chunk_summaries_section = ""

#     # ── PASS 1B: LLM Analyzer ────────────────────────────────────
#     print("  [Planner] Step 1/2: Analyzing content...")
#     try:
#         analysis = call_json(
#             ANALYZER_PROMPT.format(
#                 text_sample=sample,
#                 chunk_summaries_section=chunk_summaries_section,
#                 total_chars=total_chars,
#                 chunk_count=len(chunks),
#             ),
#             key="analyzer",
#             max_tokens=4000,
#         )
#     except Exception as e:
#         print(f"  [Analyzer] Failed: {e} — using minimal analysis")
#         analysis = {
#             "content_type": "general_topic",
#             "subject": raw_data[:200],
#             "report_title": "Content Analysis Report",
#             "report_subtitle": "Auto-Generated Report",
#             "audience": "General Audience",
#             "key_entities": [],
#             "key_facts": [],
#             "themes": ["Overview", "Key Points", "Analysis", "Conclusions"],
#             "tone": "informational",
#             "data_richness": "low",
#             "narrative_arc": "A comprehensive analysis of the provided content.",
#         }

#     ct = analysis.get('content_type', 'unknown')
#     dr = analysis.get('data_richness', 'unknown')
#     print(f"    Content type: {ct} | Data richness: {dr}")
#     print(f"    {len(analysis.get('key_facts', []))} facts | {len(analysis.get('themes', []))} themes")
#     print(f"    Subject: {analysis.get('subject', '')[:80]}")

#     # ── PASS 2: LLM Planner with design seed ─────────────────────
#     print(f"  [Planner] Step 2/2: Designing slides (seed={config.DESIGN_SEED})...")

#     # Build icon list: topic-specific icons FIRST, then generic fill
#     subject_text = (
#         analysis.get('subject', '') + ' ' +
#         ' '.join(analysis.get('key_entities', [])[:10]) + ' ' +
#         analysis.get('content_type', '')
#     )
#     topic_icons   = suggest_icons_for_topic(subject_text)
#     all_icons     = get_all_icon_names()
#     # Deduplicate: topic icons first (LLM will use them first), then rest
#     seen = set(topic_icons)
#     remaining = [n for n in sorted(all_icons) if n not in seen]
#     available_icons = ", ".join(topic_icons + remaining)[:800]

#     if topic_icons:
#         print(f"    Topic icons injected: {topic_icons[:8]}")

#     try:
#         plan = call_json(
#             PLANNER_PROMPT.format(
#                 n_slides=config.N_SLIDES,
#                 design_seed=config.DESIGN_SEED,
#                 analysis=json.dumps(analysis, indent=2)[:5000],
#                 raw_excerpt=sample[:2500],
#                 icon_list=available_icons,
#             ),
#             key="planner",
#             max_tokens=8000,
#         )
#     except Exception as e:
#         print(f"  [Planner] LLM failed: {e} — using fallback plan")
#         plan = {}

#     if not plan.get('slides'):
#         print("  [Planner] No slides returned — using fallback plan")
#         plan = _fallback_plan(analysis)

#     # Attach analysis and raw sample for downstream agents
#     plan['_analysis']    = analysis
#     plan['_raw_sample']  = sample[:2000]
#     plan['_design_seed'] = config.DESIGN_SEED

#     print(f"  [Planner] Done — {len(plan.get('slides', []))} slides planned")
#     return plan



# # agents/planner.py
# #
# # AGENT 0+1 — CONTENT ANALYZER + NARRATIVE PLANNER
# # ══════════════════════════════════════════════════
# # NotebookLM-style: two-pass for large inputs.
# #
# # Pass 1 (Analyzer): LLM reads chunks and extracts structured facts.
# #                    For large files: summarize each chunk, then synthesize.
# #                    For topic/question inputs: LLM enriches from own knowledge.
# #
# # Pass 2 (Planner):  LLM designs N slide narratives from the analysis.
# #                    Uses DESIGN_SEED to vary layouts every run.
# #                    Each run with same data produces a different visual narrative.

# import json, re, sys
# from pathlib import Path
# from typing import Optional
# sys.path.insert(0, str(Path(__file__).parent.parent))
# from utils.llm import call_json
# import config


# # ══════════════════════════════════════════════════════════════════
# #  CHUNKER — format-agnostic, no regex assumptions
# # ══════════════════════════════════════════════════════════════════

# def _chunk_text(raw: str, max_chunk_chars: Optional[int] = None) -> list[str]:
#     if max_chunk_chars is None:
#         max_chunk_chars = int(getattr(config, "CHUNK_MAX_CHARS", 8000))
#     raw = raw.strip()
#     if not raw:
#         return []
#     if len(raw) <= max_chunk_chars:
#         return [raw]

#     blocks   = re.split(r'\n\s*\n', raw)
#     chunks, current = [], ""
#     for block in blocks:
#         if len(current) + len(block) > max_chunk_chars and current:
#             chunks.append(current.strip())
#             current = block
#         else:
#             current += "\n\n" + block
#     if current.strip():
#         chunks.append(current.strip())
#     return chunks or [raw[:max_chunk_chars]]


# # ══════════════════════════════════════════════════════════════════
# #  CHUNK SUMMARIZER — condenses large inputs before analysis
# #  FIX: The original only sent 4 chunks to the analyzer.
# #       Now we summarize every chunk and synthesize them all.
# # ══════════════════════════════════════════════════════════════════

# CHUNK_SUMMARY_PROMPT = """You are summarizing a section of a larger document for a presentation designer.
# Extract and list ONLY concrete facts, numbers, names, events, and patterns from this section.
# No prose. No headers. Just a bullet list of facts.

# SECTION:
# {chunk}

# Return JSON:
# {{
#   "facts": ["fact 1", "fact 2", "..."],
#   "entities": ["entity1", "entity2"],
#   "anomalies": ["unusual thing 1"]
# }}"""


# def _summarize_chunks(chunks: list[str]) -> list[dict]:
#     """Summarize each chunk into structured facts. Used for large inputs."""
#     cap = int(getattr(config, "CHUNK_MAX_CHARS", 8000))
#     summary_tokens = int(getattr(config, "CHUNK_SUMMARY_MAX_TOKENS", 2500))
#     summaries = []
#     for i, chunk in enumerate(chunks):
#         print(f"    Summarizing chunk {i+1}/{len(chunks)}...")
#         section = chunk[:cap]
#         try:
#             s = call_json(
#                 CHUNK_SUMMARY_PROMPT.format(chunk=section),
#                 key="analyzer",
#                 max_tokens=summary_tokens,
#             )
#             summaries.append(s)
#         except Exception as e:
#             print(f"    Chunk {i+1} summary failed: {e} — using raw text")
#             summaries.append({
#                 "facts": [section[:cap]],
#                 "entities": [],
#                 "anomalies": [],
#             })
#     return summaries


# # ══════════════════════════════════════════════════════════════════
# #  ANALYZER PROMPT
# # ══════════════════════════════════════════════════════════════════

# ANALYZER_PROMPT = """You are a world-class content analyst preparing source material for a NotebookLM-quality PDF report.
# Deeply understand the input and extract everything a presentation designer needs.

# INPUT TEXT:
# {text_sample}

# {chunk_summaries_section}

# TOTAL INPUT: {total_chars} characters across {chunk_count} sections.

# Determine ALL of the following with maximum specificity:

# 1. content_type — What kind of content is this?
#    E.g.: "infrastructure_alerts", "application_logs", "kubernetes_tutorial",
#    "aws_architecture", "incident_report", "performance_metrics",
#    "research_paper", "business_report", "how_to_guide", "general_topic"

# 2. subject — 2-3 sentence summary of exactly what this content is about.

# 3. report_title — A compelling, specific, journalistic title (NOT generic).
#    BAD: "Kubernetes Overview"
#    GOOD: "Kubernetes at Scale: Architecture, Failures & Recovery Patterns"

# 4. report_subtitle — A professional subtitle with context (audience, date range, etc.)

# 5. audience — Who reads this? Be specific.
#    E.g.: "Senior SRE Team", "Platform Engineering Leads", "Kubernetes Beginners",
#    "Cloud Architecture Decision Makers", "DevOps Engineers"

# 6. key_entities — Named items found: hosts, services, tools, concepts, companies (up to 20).

# 7. key_facts — The most important facts. MUST include exact numbers when available.
#    For data-rich input (logs/alerts/metrics): extract REAL values, timestamps, counts.
#    For topic/educational input: generate REAL authoritative facts from your knowledge.
#    BAD: "Many errors occurred"
#    GOOD: "1,847 critical alerts fired between 03:00-07:00 UTC, 73% from storage cluster"
#    BAD: "Kubernetes manages containers"
#    GOOD: "Kubernetes orchestrates containers via 3 control plane components: API server, etcd, scheduler. etcd stores all cluster state as key-value pairs."

# 8. themes — 5-8 distinct angles/chapters for the presentation. Each should be a specific
#    story arc, not a generic category.
#    BAD: ["Overview", "Details", "Conclusion"]
#    GOOD: ["The 3AM Cascading Failure Chain", "etcd Saturation as Root Cause",
#           "Cross-Zone Dependency Mapping", "Recovery Playbook"]

# 9. tone — "urgent" | "analytical" | "educational" | "executive_summary" | "informational"

# 10. data_richness — "high" | "medium" | "low"
#     high = real numbers, real timestamps, real names throughout
#     low  = topic/question input — YOU must fill key_facts with real authoritative knowledge

# 11. narrative_arc — One sentence describing the story this report tells.
#     E.g.: "A cascading storage failure that started as a misconfiguration and escalated into a 4-hour outage affecting 3 services."

# CRITICAL for data_richness="low":
# If the input is a question or topic (e.g. "explain AWS", "make a PDF on ML"),
# you MUST populate key_facts with 15-20 REAL, ACCURATE, SPECIFIC facts from your knowledge.
# Include real numbers, real names, real architecture details. Be an expert, not a generalist.

# Return ONLY valid JSON:
# {{
#   "content_type": "...",
#   "subject": "...",
#   "report_title": "...",
#   "report_subtitle": "...",
#   "audience": "...",
#   "key_entities": ["entity1", ...],
#   "key_facts": [
#     {{"fact": "Specific fact with real data", "category": "theme it belongs to", "importance": "high"}},
#     ...
#   ],
#   "themes": ["Theme 1", "Theme 2", ...],
#   "tone": "analytical",
#   "data_richness": "high",
#   "narrative_arc": "..."
# }}"""


# # ══════════════════════════════════════════════════════════════════
# #  PLANNER PROMPT — uses DESIGN_SEED for visual variety
# # ══════════════════════════════════════════════════════════════════

# PLANNER_PROMPT = """You are an expert presentation architect creating a NotebookLM-quality PDF.
# Design {n_slides} slides that tell a SPECIFIC, VISUAL, COMPELLING story.

# DESIGN SEED: {design_seed}
# Use this seed to make creative layout and color choices. Different seeds = different aesthetics.
# High seed (>5000): bold, asymmetric, dramatic. Low seed (<3000): refined, structured, minimal.
# Mid seed: balanced editorial. Vary your visual type choices based on this seed.

# CONTENT ANALYSIS:
# {analysis}

# RAW SOURCE EXCERPT (for additional context):
# {raw_excerpt}

# AVAILABLE ICON NAMES (use ONLY these exact names in the "icon" fields):
# {icon_list}

# VISUAL TYPES — choose the best fit, vary them across slides:
#   cover_hero           → Full-bleed cover: giant title + 3 preview insight cards
#   big_number_hero      → One massive stat fills the slide (text-9xl, context below)
#   stat_cards_row       → 4 equal metric/concept cards in a grid
#   bar_chart_annotated  → Chart.js bar chart with callout annotations
#   area_chart_gradient  → Chart.js area/line chart showing trend over time
#   timeline_events      → Horizontal timeline of key events with milestones
#   topology_map         → CSS node/card diagram — system architecture or concept map
#   matrix_table         → HTML comparison table (teams × dimensions, options × criteria)
#   domino_chain         → Horizontal cause-effect cards with arrows between them
#   comparison_panel     → Two equal panels, each with chart or stats inside
#   priority_table       → Styled action table: Item | Priority | Action columns
#   scatter_quadrant     → 2×2 grid (Impact vs Effort, Risk vs Value, etc.)
#   funnel_diagram       → Funnel/pipeline showing stages with counts
#   info_cards_grid      → 2×2 or 3×2 grid of rich content cards with icons
#   concept_diagram      → 3-6 step workflow with connectors (architecture, process)
#   two_column_bullets   → Left: key insight panel; Right: bullet list with icons
#   callout_hero         → Large pull-quote or key finding with supporting stats below

# COLOR MOODS:
#   critical_red    → #C0392B accent (urgent, broken, failure)
#   warning_amber   → #D4880E accent (degraded, at-risk)
#   info_blue       → #2471A3 accent (informational, educational)
#   success_green   → #1E8449 accent (achievements, solutions, health)
#   neutral_slate   → #4A5568 accent (summary, conclusion, overview)
#   deep_purple     → #6B46C1 accent (innovation, AI, future)
#   teal_focus      → #0D9488 accent (process, flow, systems)

# RULES — read carefully:
# 1. Slide 1 MUST be cover_hero. Final slide MUST be a conclusion/takeaways slide.
# 2. Use at LEAST 6 different visual_types across all slides.
# 3. Titles must be JOURNALISTIC and SPECIFIC — not generic labels.
#    BAD: "System Overview" | GOOD: "Why Three Services Went Dark at 3AM"
# 4. The "data" field must contain ALL values the designer needs to render the slide.
#    Include real numbers, real names, real labels — never say "see analysis".
# 5. story_angle must explain WHY this slide matters to the audience.
# 6. For "icon" fields in data: use ONLY names from the AVAILABLE ICON NAMES list above.
# 7. Each slide needs a unique visual_type — minimize repeats.
# 8. "visual_description" must be detailed enough for a designer to render from scratch.
# 9. If data_richness is "low", use your knowledge to create REAL data values in the data field.

# Return ONLY valid JSON:
# {{
#   "report_title": "...",
#   "report_subtitle": "...",
#   "audience": "...",
#   "slides": [
#     {{
#       "slot": 1,
#       "title": "Compelling specific title",
#       "subtitle": "Contextual subtitle",
#       "story_angle": "Why this slide matters",
#       "key_insight": "The one thing the reader takes away",
#       "visual_type": "cover_hero",
#       "visual_description": "Detailed visual description",
#       "layout_hint": "centered | left_text_right_visual | full_visual | header_plus_grid",
#       "color_mood": "neutral_slate",
#       "data": {{
#         "key": "value — real data, real numbers"
#       }}
#     }}
#   ]
# }}"""


# # ══════════════════════════════════════════════════════════════════
# #  FALLBACK PLAN
# # ══════════════════════════════════════════════════════════════════

# def _fallback_plan(analysis: dict) -> dict:
#     themes = analysis.get('themes', ['Overview', 'Details', 'Analysis', 'Summary'])
#     facts  = analysis.get('key_facts', [])
#     title  = analysis.get('report_title', 'Report')
#     subtitle = analysis.get('report_subtitle', 'Generated Report')

#     vt_cycle = [
#         'stat_cards_row', 'bar_chart_annotated', 'info_cards_grid',
#         'timeline_events', 'topology_map', 'concept_diagram', 'priority_table',
#     ]
#     cm_cycle = [
#         'info_blue', 'warning_amber', 'neutral_slate',
#         'critical_red', 'success_green', 'deep_purple', 'teal_focus',
#     ]

#     slides = [{
#         'slot': 1,
#         'title': title,
#         'subtitle': subtitle,
#         'story_angle': 'Set the stage with key highlights',
#         'key_insight': analysis.get('subject', ''),
#         'visual_type': 'cover_hero',
#         'visual_description': f'Cover with title "{title}", subtitle, and 3 preview theme cards.',
#         'layout_hint': 'centered',
#         'color_mood': 'neutral_slate',
#         'data': {
#             'title': title,
#             'subtitle': subtitle,
#             'preview_cards': [
#                 {'title': t, 'description': 'Key topic', 'icon': 'lightbulb'}
#                 for t in themes[:3]
#             ],
#         },
#     }]

#     for i, theme in enumerate(themes[:8], 2):
#         tf = [f for f in facts if f.get('category', '').lower() == theme.lower()]
#         if not tf:
#             tf = facts[max(0, i-2):min(i+1, len(facts))]
#         slides.append({
#             'slot': i,
#             'title': theme,
#             'subtitle': '',
#             'story_angle': f'Analysis of {theme}',
#             'key_insight': tf[0].get('fact', f'Key insights about {theme}') if tf else f'Key insights about {theme}',
#             'visual_type': vt_cycle[(i - 2) % len(vt_cycle)],
#             'visual_description': f'Visual showing key aspects of {theme} with real data.',
#             'layout_hint': 'left_text_right_visual',
#             'color_mood': cm_cycle[(i - 2) % len(cm_cycle)],
#             'data': {'theme': theme, 'facts': [f.get('fact', '') for f in tf[:5]]},
#         })

#     slides.append({
#         'slot': len(slides) + 1,
#         'title': 'Key Takeaways & Next Steps',
#         'subtitle': '',
#         'story_angle': 'Actionable conclusions',
#         'key_insight': 'Summary of findings and recommended actions',
#         'visual_type': 'priority_table',
#         'visual_description': 'Action table with key findings and next steps.',
#         'layout_hint': 'full_visual',
#         'color_mood': 'neutral_slate',
#         'data': {'themes': themes[:6], 'top_facts': [f.get('fact', '') for f in facts[:5]]},
#     })

#     return {
#         'report_title': title,
#         'report_subtitle': subtitle,
#         'audience': analysis.get('audience', 'General'),
#         'slides': slides,
#     }


# # ══════════════════════════════════════════════════════════════════
# #  PUBLIC API
# # ══════════════════════════════════════════════════════════════════

# def run(raw_data: str) -> dict:
#     """
#     Two-pass pipeline:
#       Pass 1: Analyze content (with chunk summarization for large inputs)
#       Pass 2: Plan slide narrative (with design seed for variety)
#     """
#     from utils.icons import get_all_icon_names, suggest_icons_for_topic
#     from utils.icon_fetcher import fetch_and_register, detect_unknown_brands

#     join_max = int(getattr(config, "ANALYZER_JOIN_MAX_CHARS", 48_000))
#     first_n = int(getattr(config, "ANALYZER_FIRST_CHUNK_CHARS", 6000))
#     last_n = int(getattr(config, "ANALYZER_LAST_CHUNK_CHARS", 4000))
#     summaries_json_max = int(getattr(config, "ANALYZER_CHUNK_SUMMARIES_JSON_MAX_CHARS", 12_000))
#     raw_excerpt_max = int(getattr(config, "PLANNER_RAW_EXCERPT_CHARS", 5000))
#     raw_sample_max = int(getattr(config, "PLANNER_RAW_SAMPLE_STORE_CHARS", 4000))
#     analysis_json_max = int(getattr(config, "PLANNER_ANALYSIS_JSON_MAX_CHARS", 8000))

#     chunks      = _chunk_text(raw_data)
#     total_chars = len(raw_data)

#     if not chunks:
#         print("  [Planner] WARNING: Empty input")
#         return {}

#     # ── PASS 1A: For large inputs, pre-summarize each chunk ───────
#     chunk_summaries_section = ""
#     if len(chunks) > 4:
#         print(f"  [Planner] Large input ({len(chunks)} chunks) — pre-summarizing all chunks...")
#         summaries = _summarize_chunks(chunks)
#         all_facts    = []
#         all_entities = []
#         all_anomalies = []
#         for s in summaries:
#             all_facts.extend(s.get('facts', []))
#             all_entities.extend(s.get('entities', []))
#             all_anomalies.extend(s.get('anomalies', []))
#         # Deduplicate
#         all_entities = list(dict.fromkeys(all_entities))[:30]
#         chunk_summaries_section = (
#             f"\nCHUNK SUMMARIES (from {len(chunks)} sections of the full document):\n"
#             + json.dumps({
#                 "total_facts_extracted": len(all_facts),
#                 "sample_facts": all_facts[:40],
#                 "all_entities": all_entities[:25],
#                 "anomalies": all_anomalies[:15],
#             }, indent=2)[:summaries_json_max]
#         )
#         # Use first + last chunk as text sample; summaries carry the rest
#         sample = chunks[0][:first_n] + "\n\n---\n\n" + chunks[-1][:last_n]
#     else:
#         # Small input: stitch chunks up to ANALYZER_JOIN_MAX_CHARS
#         joined = "\n\n---\n\n".join(chunks)
#         sample = joined[: min(len(joined), join_max)]
#         chunk_summaries_section = ""

#     # ── PASS 1B: LLM Analyzer ────────────────────────────────────
#     print("  [Planner] Step 1/2: Analyzing content...")
#     try:
#         analysis = call_json(
#             ANALYZER_PROMPT.format(
#                 text_sample=sample,
#                 chunk_summaries_section=chunk_summaries_section,
#                 total_chars=total_chars,
#                 chunk_count=len(chunks),
#             ),
#             key="analyzer",
#             max_tokens=4000,
#         )
#     except Exception as e:
#         print(f"  [Analyzer] Failed: {e} — using minimal analysis")
#         analysis = {
#             "content_type": "general_topic",
#             "subject": raw_data[:200],
#             "report_title": "Content Analysis Report",
#             "report_subtitle": "Auto-Generated Report",
#             "audience": "General Audience",
#             "key_entities": [],
#             "key_facts": [],
#             "themes": ["Overview", "Key Points", "Analysis", "Conclusions"],
#             "tone": "informational",
#             "data_richness": "low",
#             "narrative_arc": "A comprehensive analysis of the provided content.",
#         }

#     ct = analysis.get('content_type', 'unknown')
#     dr = analysis.get('data_richness', 'unknown')
#     print(f"    Content type: {ct} | Data richness: {dr}")
#     print(f"    {len(analysis.get('key_facts', []))} facts | {len(analysis.get('themes', []))} themes")
#     print(f"    Subject: {analysis.get('subject', '')[:80]}")

#     # ── PASS 2: LLM Planner with design seed ─────────────────────
#     print(f"  [Planner] Step 2/2: Designing slides (seed={config.DESIGN_SEED})...")

#     # Build icon list: topic-specific icons FIRST, then generic fill
#     subject_text = (
#         analysis.get('subject', '') + ' ' +
#         ' '.join(analysis.get('key_entities', [])[:10]) + ' ' +
#         analysis.get('content_type', '')
#     )

#     # Attempt to fetch brand icons for any entities we don't recognize
#     # This runs BEFORE building the icon list so fetched icons appear in the prompt
#     entities = analysis.get('key_entities', [])
#     unknown_brands = detect_unknown_brands(entities)
#     if unknown_brands:
#         print(f"  [Planner] Detected unknown brands: {unknown_brands[:6]}")
#         try:
#             fetch_results = fetch_and_register(unknown_brands[:8])
#             fetched = [k for k, v in fetch_results.items() if v]
#             if fetched:
#                 print(f"  [Planner] Fetched new brand icons: {fetched}")
#         except Exception as e:
#             print(f"  [Planner] Icon fetch failed (offline?): {e} — using letter badges")
#     topic_icons   = suggest_icons_for_topic(subject_text)
#     all_icons     = get_all_icon_names()
#     # Deduplicate: topic icons first (LLM will use them first), then rest
#     seen = set(topic_icons)
#     remaining = [n for n in sorted(all_icons) if n not in seen]
#     available_icons = ", ".join(topic_icons + remaining)[:800]

#     if topic_icons:
#         print(f"    Topic icons injected: {topic_icons[:8]}")

#     try:
#         plan = call_json(
#             PLANNER_PROMPT.format(
#                 n_slides=config.N_SLIDES,
#                 design_seed=config.DESIGN_SEED,
#                 analysis=json.dumps(analysis, indent=2)[:analysis_json_max],
#                 raw_excerpt=sample[:raw_excerpt_max],
#                 icon_list=available_icons,
#             ),
#             key="planner",
#             max_tokens=8000,
#         )
#     except Exception as e:
#         print(f"  [Planner] LLM failed: {e} — using fallback plan")
#         plan = {}

#     if not plan.get('slides'):
#         print("  [Planner] No slides returned — using fallback plan")
#         plan = _fallback_plan(analysis)

#     # Attach analysis and raw sample for downstream agents
#     plan['_analysis']    = analysis
#     plan['_raw_sample']  = sample[:raw_sample_max]
#     plan['_design_seed'] = config.DESIGN_SEED

#     print(f"  [Planner] Done — {len(plan.get('slides', []))} slides planned")
#     return plan


# agents/planner.py
#
# AGENT 0+1 — CONTENT ANALYZER + NARRATIVE PLANNER
# ══════════════════════════════════════════════════
# NotebookLM-style: two-pass for large inputs.
#
# Pass 1 (Analyzer): LLM reads chunks and extracts structured facts.
#                    For large files: summarize each chunk, then synthesize.
#                    For topic/question inputs: LLM enriches from own knowledge.
#
# Pass 2 (Planner):  LLM designs N slide narratives from the analysis.
#                    Uses DESIGN_SEED to vary layouts every run.
#                    Each run with same data produces a different visual narrative.

import json, re, sys
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call_json
import config


# ══════════════════════════════════════════════════════════════════
#  CHUNKER — format-agnostic, no regex assumptions
# ══════════════════════════════════════════════════════════════════

def _chunk_text(raw: str, max_chunk_chars: Optional | None = None) -> list[str]:
    if max_chunk_chars is None:
        max_chunk_chars = int(getattr(config, "CHUNK_MAX_CHARS", 8000))
    raw = raw.strip()
    if not raw:
        return []
    if len(raw) <= max_chunk_chars:
        return [raw]

    blocks   = re.split(r'\n\s*\n', raw)
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
#  CHUNK SUMMARIZER — condenses large inputs before analysis
#  FIX: The original only sent 4 chunks to the analyzer.
#       Now we summarize every chunk and synthesize them all.
# ══════════════════════════════════════════════════════════════════

CHUNK_SUMMARY_PROMPT = """You are summarizing a section of a larger document for a presentation designer.
Extract and list ONLY concrete facts, numbers, names, events, and patterns from this section.
No prose. No headers. Just a bullet list of facts.

SECTION:
{chunk}

Return JSON:
{{
  "facts": ["fact 1", "fact 2", "..."],
  "entities": ["entity1", "entity2"],
  "anomalies": ["unusual thing 1"]
}}"""


def _summarize_chunks(chunks: list[str]) -> list[dict]:
    """Summarize each chunk into structured facts. Used for large inputs."""
    cap = int(getattr(config, "CHUNK_MAX_CHARS", 8000))
    summary_tokens = int(getattr(config, "CHUNK_SUMMARY_MAX_TOKENS", 2500))
    summaries = []
    for i, chunk in enumerate(chunks):
        print(f"    Summarizing chunk {i+1}/{len(chunks)}...")
        section = chunk[:cap]
        try:
            s = call_json(
                CHUNK_SUMMARY_PROMPT.format(chunk=section),
                key="analyzer",
                max_tokens=summary_tokens,
            )
            summaries.append(s)
        except Exception as e:
            print(f"    Chunk {i+1} summary failed: {e} — using raw text")
            summaries.append({
                "facts": [section[:cap]],
                "entities": [],
                "anomalies": [],
            })
    return summaries


# ══════════════════════════════════════════════════════════════════
#  ANALYZER PROMPT
# ══════════════════════════════════════════════════════════════════

ANALYZER_PROMPT = """You are a world-class content analyst preparing source material for a NotebookLM-quality PDF report.
Deeply understand the input and extract everything a presentation designer needs.

INPUT TEXT:
{text_sample}

{chunk_summaries_section}

TOTAL INPUT: {total_chars} characters across {chunk_count} sections.

Determine ALL of the following with maximum specificity:

1. content_type — What kind of content is this?
   E.g.: "infrastructure_alerts", "application_logs", "kubernetes_tutorial",
   "aws_architecture", "incident_report", "performance_metrics",
   "sre_runbook", "capacity_analysis", "error_analysis", "security_audit",
   "research_paper", "business_report", "how_to_guide", "general_topic"

   IMPORTANT: Use "infrastructure_alerts", "application_logs", "incident_report",
   "performance_metrics", "error_analysis", or "capacity_analysis" when the input
   contains log lines, alert messages, error counts, latency metrics, or system events.
   These content types REQUIRE a risk_impact_matrix slide (see Rule 10 below).

2. subject — 2-3 sentence summary of exactly what this content is about.

3. report_title — A compelling, specific, journalistic title (NOT generic).
   BAD: "Kubernetes Overview"
   GOOD: "Kubernetes at Scale: Architecture, Failures & Recovery Patterns"

4. report_subtitle — A professional subtitle with context (audience, date range, etc.)

5. audience — Who reads this? Be specific.
   E.g.: "Senior SRE Team", "Platform Engineering Leads", "Kubernetes Beginners",
   "Cloud Architecture Decision Makers", "DevOps Engineers"

6. key_entities — Named items found: hosts, services, tools, concepts, companies (up to 20).

7. key_facts — The most important facts. MUST include exact numbers when available.
   For data-rich input (logs/alerts/metrics): extract REAL values, timestamps, counts.
   For topic/educational input: generate REAL authoritative facts from your knowledge.
   BAD: "Many errors occurred"
   GOOD: "1,847 critical alerts fired between 03:00-07:00 IST, 73% from storage cluster"
   BAD: "Kubernetes manages containers"
   GOOD: "Kubernetes orchestrates containers via 3 control plane components: API server, etcd, scheduler. etcd stores all cluster state as key-value pairs."

8. themes — 5-8 distinct angles/chapters for the presentation. Each should be a specific
   story arc, not a generic category.
   BAD: ["Overview", "Details", "Conclusion"]
   GOOD: ["The 3AM Cascading Failure Chain", "etcd Saturation as Root Cause",
          "Cross-Zone Dependency Mapping", "Recovery Playbook"]

9. tone — "urgent" | "analytical" | "educational" | "executive_summary" | "informational"

10. data_richness — "high" | "medium" | "low"
    high = real numbers, real timestamps, real names throughout
    low  = topic/question input — YOU must fill key_facts with real authoritative knowledge

11. narrative_arc — One sentence describing the story this report tells.
    E.g.: "A cascading storage failure that started as a misconfiguration and escalated into a 4-hour outage affecting 3 services."

CRITICAL for data_richness="low":
If the input is a question or topic (e.g. "explain AWS", "make a PDF on ML"),
you MUST populate key_facts with 15-20 REAL, ACCURATE, SPECIFIC facts from your knowledge.
Include real numbers, real names, real architecture details. Be an expert, not a generalist.

Return ONLY valid JSON:
{{
  "content_type": "...",
  "subject": "...",
  "report_title": "...",
  "report_subtitle": "...",
  "audience": "...",
  "key_entities": ["entity1", ...],
  "key_facts": [
    {{"fact": "Specific fact with real data", "category": "theme it belongs to", "importance": "high"}},
    ...
  ],
  "themes": ["Theme 1", "Theme 2", ...],
  "tone": "analytical",
  "data_richness": "high",
  "narrative_arc": "..."
}}"""


# ══════════════════════════════════════════════════════════════════
#  PLANNER PROMPT — uses DESIGN_SEED for visual variety
# ══════════════════════════════════════════════════════════════════

PLANNER_PROMPT = """You are an expert presentation architect creating a NotebookLM-quality PDF.
Design {n_slides} slides that tell a SPECIFIC, VISUAL, COMPELLING story.

DESIGN SEED: {design_seed}
Use this seed to make creative layout and color choices. Different seeds = different aesthetics.
High seed (>5000): bold, asymmetric, dramatic. Low seed (<3000): refined, structured, minimal.
Mid seed: balanced editorial. Vary your visual type choices based on this seed.

CONTENT ANALYSIS:
{analysis}

RAW SOURCE EXCERPT (for additional context):
{raw_excerpt}

AVAILABLE ICON NAMES (use ONLY these exact names in the "icon" fields):
{icon_list}

VISUAL TYPES — choose the best fit, vary them across slides:
  cover_hero           → Full-bleed cover: giant title + 3 preview insight cards
  big_number_hero      → One massive stat fills the slide (text-9xl, context below)
  stat_cards_row       → 4 equal metric/concept cards in a grid
  bar_chart_annotated  → Chart.js bar chart with callout annotations
  area_chart_gradient  → Chart.js area/line chart showing trend over time
  timeline_events      → Horizontal timeline of key events with milestones
  topology_map         → CSS node/card diagram — system architecture or concept map
  matrix_table         → HTML comparison table (teams × dimensions, options × criteria)
  domino_chain         → Horizontal cause-effect cards with arrows between them
  comparison_panel     → Two equal panels, each with chart or stats inside
  priority_table       → Styled action table: Item | Priority | Action columns
  risk_impact_matrix   → ★ 2×2 Risk/Impact quadrant — REQUIRED for alerts/logs/incidents
                         Left 65%: four quadrants (High/Low Impact × High/Low Effort)
                         Each quadrant has real items from the data with icon + stat
                         Right 35%: Strategic Guidance + Immediate Action callout
  scatter_quadrant     → 2×2 grid (Impact vs Effort, Risk vs Value, etc.)
  funnel_diagram       → Funnel/pipeline showing stages with counts
  info_cards_grid      → 2×2 or 3×2 grid of rich content cards with icons
  concept_diagram      → 3-6 step workflow with connectors (architecture, process)
  two_column_bullets   → Left: key insight panel; Right: bullet list with icons
  callout_hero         → Large pull-quote or key finding with supporting stats below

COLOR MOODS:
  critical_red    → #C0392B accent (urgent, broken, failure)
  warning_amber   → #D4880E accent (degraded, at-risk)
  info_blue       → #2471A3 accent (informational, educational)
  success_green   → #1E8449 accent (achievements, solutions, health)
  neutral_slate   → #4A5568 accent (summary, conclusion, overview)
  deep_purple     → #6B46C1 accent (innovation, AI, future)
  teal_focus      → #0D9488 accent (process, flow, systems)

RULES — read carefully:
1. Slide 1 MUST be cover_hero. Final slide MUST be a conclusion/takeaways slide.
2. Use at LEAST 6 different visual_types across all slides.
3. Titles must be JOURNALISTIC and SPECIFIC — not generic labels.
   BAD: "System Overview" | GOOD: "Why Three Services Went Dark at 3AM"
4. The "data" field must contain ALL values the designer needs to render the slide.
   Include real numbers, real names, real labels — never say "see analysis".
5. story_angle must explain WHY this slide matters to the audience.
6. For "icon" fields in data: use ONLY names from the AVAILABLE ICON NAMES list above.
7. Each slide needs a unique visual_type — minimize repeats.
8. "visual_description" must be detailed enough for a designer to render from scratch.
9. If data_richness is "low", use your knowledge to create REAL data values in the data field.
10. ★ MANDATORY for content_type=alerts/logs/incidents/performance_metrics:
    MUST include exactly ONE slide with visual_type="risk_impact_matrix".
    Use this EXACT data schema for that slide:
    {{
      "visual_type": "risk_impact_matrix",
      "data": {{
        "x_axis_label": "IMPACT",
        "y_axis_label": "EFFORT",
        "high_impact_low_effort": [
          {{"name": "Issue/item name", "icon": "icon-name", "stat": "primary metric", "detail": "host/source/context (optional)", "severity": "critical"}}
        ],
        "high_impact_high_effort": [
          {{"name": "Issue/item name", "icon": "icon-name", "stat": "primary metric", "detail": "optional context", "severity": "high"}}
        ],
        "low_impact_low_effort": [
          {{"name": "Quick win item", "icon": "icon-name", "stat": "metric", "detail": "optional", "severity": "low"}}
        ],
        "low_impact_high_effort": [
          {{"name": "Deprioritize item", "icon": "icon-name", "stat": "metric", "detail": "optional", "severity": "medium"}}
        ],
        "strategic_guidance": "2-3 sentence guidance on where to focus first and why",
        "immediate_action": "One concrete action required now (specific, not generic)",
        "system_health": "Nominal | Degraded | Critical",
        "last_sync": "timestamp or data freshness label"
      }}
    }}
    Populate EVERY quadrant with real items from the analysis — never empty.
    When source data lists several distinct issues, put 2-4 items per quadrant (not just one).
    Use "detail" for hostname, service, error class, or SLA impact so the matrix looks data-dense.

Return ONLY valid JSON:
{{
  "report_title": "...",
  "report_subtitle": "...",
  "audience": "...",
  "slides": [
    {{
      "slot": 1,
      "title": "Compelling specific title",
      "subtitle": "Contextual subtitle",
      "story_angle": "Why this slide matters",
      "key_insight": "The one thing the reader takes away",
      "visual_type": "cover_hero",
      "visual_description": "Detailed visual description",
      "layout_hint": "centered | left_text_right_visual | full_visual | header_plus_grid",
      "color_mood": "neutral_slate",
      "data": {{
        "key": "value — real data, real numbers"
      }}
    }}
  ]
}}"""


# ══════════════════════════════════════════════════════════════════
#  FALLBACK PLAN
# ══════════════════════════════════════════════════════════════════

def _fallback_plan(analysis: dict) -> dict:
    themes      = analysis.get('themes', ['Overview', 'Details', 'Analysis', 'Summary'])
    facts       = analysis.get('key_facts', [])
    title       = analysis.get('report_title', 'Report')
    subtitle    = analysis.get('report_subtitle', 'Generated Report')
    content_type = analysis.get('content_type', 'general_topic')

    vt_cycle = [
        'stat_cards_row', 'bar_chart_annotated', 'info_cards_grid',
        'timeline_events', 'topology_map', 'concept_diagram', 'priority_table',
    ]
    cm_cycle = [
        'info_blue', 'warning_amber', 'neutral_slate',
        'critical_red', 'success_green', 'deep_purple', 'teal_focus',
    ]

    # Determine if this is operational/alert content requiring risk matrix
    ALERT_TYPES = {
        'infrastructure_alerts', 'application_logs', 'incident_report',
        'performance_metrics', 'error_analysis', 'capacity_analysis',
        'sre_runbook', 'security_audit',
    }
    needs_risk_matrix = content_type in ALERT_TYPES

    slides = [{
        'slot': 1,
        'title': title,
        'subtitle': subtitle,
        'story_angle': 'Set the stage with key highlights',
        'key_insight': analysis.get('subject', ''),
        'visual_type': 'cover_hero',
        'visual_description': f'Cover with title "{title}", subtitle, and 3 preview theme cards.',
        'layout_hint': 'centered',
        'color_mood': 'neutral_slate',
        'data': {
            'title': title,
            'subtitle': subtitle,
            'preview_cards': [
                {'title': t, 'description': 'Key topic', 'icon': 'lightbulb'}
                for t in themes[:3]
            ],
        },
    }]

    for i, theme in enumerate(themes[:8], 2):
        tf = [f for f in facts if f.get('category', '').lower() == theme.lower()]
        if not tf:
            tf = facts[max(0, i-2):min(i+1, len(facts))]
        slides.append({
            'slot': i,
            'title': theme,
            'subtitle': '',
            'story_angle': f'Analysis of {theme}',
            'key_insight': tf[0].get('fact', f'Key insights about {theme}') if tf else f'Key insights about {theme}',
            'visual_type': vt_cycle[(i - 2) % len(vt_cycle)],
            'visual_description': f'Visual showing key aspects of {theme} with real data.',
            'layout_hint': 'left_text_right_visual',
            'color_mood': cm_cycle[(i - 2) % len(cm_cycle)],
            'data': {'theme': theme, 'facts': [f.get('fact', '') for f in tf[:5]]},
        })

    # Add risk_impact_matrix for operational content (guaranteed via Python renderer)
    if needs_risk_matrix:
        # Extract items from facts by importance
        critical = [f.get('fact', '') for f in facts if f.get('importance') == 'high']
        medium   = [f.get('fact', '') for f in facts if f.get('importance') == 'medium']
        low_f    = [f.get('fact', '') for f in facts if f.get('importance') == 'low']
        entities = analysis.get('key_entities', [])

        def _fact_to_item(
            fact_str: str, idx: int, icon_name: str = 'alert-circle', severity: str = 'high',
        ) -> dict:
            s = (fact_str or '').strip()
            if not s:
                return {'name': 'Item', 'icon': icon_name, 'stat': '', 'detail': '', 'severity': severity}
            parts = s.split(':', 1)
            if len(parts) > 1:
                name = parts[0].strip()[:52]
                rest = parts[1].strip()
            else:
                name = s[:52]
                rest = ''
            stat = rest[:56].strip()
            detail = rest[56:200].strip() if len(rest) > 56 else ""
            return {
                'name': name, 'icon': icon_name, 'stat': stat, 'detail': detail,
                'severity': severity,
            }

        hi_lo_items = [_fact_to_item(f, i, 'zap', 'critical') for i, f in enumerate(critical[:4])]
        hi_hi_items = [_fact_to_item(f, i, 'database', 'high') for i, f in enumerate(critical[4:8])]
        lo_lo_items = [_fact_to_item(f, i, 'settings', 'low') for i, f in enumerate(low_f[:4])]
        lo_hi_items = [_fact_to_item(f, i, 'git-branch', 'medium') for i, f in enumerate(medium[:4])]

        # Ensure no empty quadrants
        if not hi_lo_items:
            hi_lo_items = [{'name': 'Primary Alert', 'icon': 'alert-triangle', 'stat': 'See analysis', 'detail': '', 'severity': 'critical'}]
        if not hi_hi_items:
            hi_hi_items = [{'name': 'Complex Issue', 'icon': 'layers', 'stat': 'Needs planning', 'detail': '', 'severity': 'high'}]
        if not lo_lo_items:
            lo_lo_items = [{'name': 'Minor Items', 'icon': 'info', 'stat': 'Low priority', 'detail': '', 'severity': 'low'}]
        if not lo_hi_items:
            lo_hi_items = [{'name': 'Tech Debt', 'icon': 'clock', 'stat': 'Deferred', 'detail': '', 'severity': 'medium'}]

        slides.append({
            'slot': len(slides) + 1,
            'title': 'Risk vs. Impact Analysis',
            'subtitle': 'Prioritizing remediation efforts for operational stability',
            'story_angle': 'Which issues should we fix first to maximize system reliability?',
            'key_insight': 'Address High Impact / Low Effort items immediately to restore stability',
            'visual_type': 'risk_impact_matrix',
            'visual_description': '2×2 risk/impact matrix with remediation guidance and system health status',
            'layout_hint': 'full_visual',
            'color_mood': 'critical_red',
            'data': {
                'x_axis_label': 'IMPACT',
                'y_axis_label': 'EFFORT',
                'high_impact_low_effort': hi_lo_items,
                'high_impact_high_effort': hi_hi_items,
                'low_impact_low_effort': lo_lo_items,
                'low_impact_high_effort': lo_hi_items,
                'strategic_guidance': (
                    f'Focus remediation on the High Impact quadrant first. '
                    f'{"Key entities " + ", ".join(entities[:3]) + " " if entities else ""}'
                    f'represent critical architectural bottlenecks directly correlating to downtime. '
                    f'Address High Impact / Low Effort items before tackling complex systemic issues.'
                ),
                'immediate_action': (
                    critical[0] if critical
                    else 'Review all critical alerts and escalate to on-call team immediately.'
                ),
                'system_health': 'Critical' if critical else 'Degraded',
                'last_sync': 'Analysis timestamp',
            },
        })

    slides.append({
        'slot': len(slides) + 1,
        'title': 'Key Takeaways & Next Steps',
        'subtitle': '',
        'story_angle': 'Actionable conclusions',
        'key_insight': 'Summary of findings and recommended actions',
        'visual_type': 'priority_table',
        'visual_description': 'Action table with key findings and next steps.',
        'layout_hint': 'full_visual',
        'color_mood': 'neutral_slate',
        'data': {'themes': themes[:6], 'top_facts': [f.get('fact', '') for f in facts[:5]]},
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
    """
    Two-pass pipeline:
      Pass 1: Analyze content (with chunk summarization for large inputs)
      Pass 2: Plan slide narrative (with design seed for variety)
    """
    from utils.icons import get_all_icon_names, suggest_icons_for_topic
    from utils.icon_fetcher import fetch_and_register, detect_unknown_brands

    join_max = int(getattr(config, "ANALYZER_JOIN_MAX_CHARS", 48_000))
    first_n = int(getattr(config, "ANALYZER_FIRST_CHUNK_CHARS", 6000))
    last_n = int(getattr(config, "ANALYZER_LAST_CHUNK_CHARS", 4000))
    summaries_json_max = int(getattr(config, "ANALYZER_CHUNK_SUMMARIES_JSON_MAX_CHARS", 12_000))
    raw_excerpt_max = int(getattr(config, "PLANNER_RAW_EXCERPT_CHARS", 5000))
    raw_sample_max = int(getattr(config, "PLANNER_RAW_SAMPLE_STORE_CHARS", 4000))
    analysis_json_max = int(getattr(config, "PLANNER_ANALYSIS_JSON_MAX_CHARS", 8000))

    chunks      = _chunk_text(raw_data)
    total_chars = len(raw_data)

    if not chunks:
        print("  [Planner] WARNING: Empty input")
        return {}

    # ── PASS 1A: For large inputs, pre-summarize each chunk ───────
    chunk_summaries_section = ""
    if len(chunks) > 4:
        print(f"  [Planner] Large input ({len(chunks)} chunks) — pre-summarizing all chunks...")
        summaries = _summarize_chunks(chunks)
        all_facts    = []
        all_entities = []
        all_anomalies = []
        for s in summaries:
            all_facts.extend(s.get('facts', []))
            all_entities.extend(s.get('entities', []))
            all_anomalies.extend(s.get('anomalies', []))
        # Deduplicate
        all_entities = list(dict.fromkeys(all_entities))[:30]
        chunk_summaries_section = (
            f"\nCHUNK SUMMARIES (from {len(chunks)} sections of the full document):\n"
            + json.dumps({
                "total_facts_extracted": len(all_facts),
                "sample_facts": all_facts[:40],
                "all_entities": all_entities[:25],
                "anomalies": all_anomalies[:15],
            }, indent=2)[:summaries_json_max]
        )
        # Use first + last chunk as text sample; summaries carry the rest
        sample = chunks[0][:first_n] + "\n\n---\n\n" + chunks[-1][:last_n]
    else:
        # Small input: stitch chunks up to ANALYZER_JOIN_MAX_CHARS
        joined = "\n\n---\n\n".join(chunks)
        sample = joined[: min(len(joined), join_max)]
        chunk_summaries_section = ""

    # ── PASS 1B: LLM Analyzer ────────────────────────────────────
    print("  [Planner] Step 1/2: Analyzing content...")
    try:
        analysis = call_json(
            ANALYZER_PROMPT.format(
                text_sample=sample,
                chunk_summaries_section=chunk_summaries_section,
                total_chars=total_chars,
                chunk_count=len(chunks),
            ),
            key="analyzer",
            max_tokens=8000,
        )
    except Exception as e:
        print(f"  [Analyzer] Failed: {e} — using minimal analysis")
        analysis = {
            "content_type": "general_topic",
            "subject": raw_data[:200],
            "report_title": "Content Analysis Report",
            "report_subtitle": "Auto-Generated Report",
            "audience": "General Audience",
            "key_entities": [],
            "key_facts": [],
            "themes": ["Overview", "Key Points", "Analysis", "Conclusions"],
            "tone": "informational",
            "data_richness": "low",
            "narrative_arc": "A comprehensive analysis of the provided content.",
        }

    ct = analysis.get('content_type', 'unknown')
    dr = analysis.get('data_richness', 'unknown')
    print(f"    Content type: {ct} | Data richness: {dr}")
    print(f"    {len(analysis.get('key_facts', []))} facts | {len(analysis.get('themes', []))} themes")
    print(f"    Subject: {analysis.get('subject', '')[:80]}")

    # ── PASS 2: LLM Planner with design seed ─────────────────────
    print(f"  [Planner] Step 2/2: Designing slides (seed={config.DESIGN_SEED})...")

    # Build icon list: topic-specific icons FIRST, then generic fill
    subject_text = (
        analysis.get('subject', '') + ' ' +
        ' '.join(analysis.get('key_entities', [])[:10]) + ' ' +
        analysis.get('content_type', '')
    )

    # Attempt to fetch brand icons for any entities we don't recognize
    # This runs BEFORE building the icon list so fetched icons appear in the prompt
    entities = analysis.get('key_entities', [])
    unknown_brands = detect_unknown_brands(entities)
    if unknown_brands:
        print(f"  [Planner] Detected unknown brands: {unknown_brands[:6]}")
        try:
            fetch_results = fetch_and_register(unknown_brands[:8])
            fetched = [k for k, v in fetch_results.items() if v]
            if fetched:
                print(f"  [Planner] Fetched new brand icons: {fetched}")
        except Exception as e:
            print(f"  [Planner] Icon fetch failed (offline?): {e} — using letter badges")
    topic_icons   = suggest_icons_for_topic(subject_text)
    all_icons     = get_all_icon_names()
    # Deduplicate: topic icons first (LLM will use them first), then rest
    seen = set(topic_icons)
    remaining = [n for n in sorted(all_icons) if n not in seen]
    available_icons = ", ".join(topic_icons + remaining)[:800]

    if topic_icons:
        print(f"    Topic icons injected: {topic_icons[:8]}")

    try:
        plan = call_json(
            PLANNER_PROMPT.format(
                n_slides=config.N_SLIDES,
                design_seed=config.DESIGN_SEED,
                analysis=json.dumps(analysis, indent=2)[:analysis_json_max],
                raw_excerpt=sample[:raw_excerpt_max],
                icon_list=available_icons,
            ),
            key="planner",
            max_tokens=8000,
        )
    except Exception as e:
        print(f"  [Planner] LLM failed: {e} — using fallback plan")
        plan = {}

    if not plan.get('slides'):
        print("  [Planner] No slides returned — using fallback plan")
        plan = _fallback_plan(analysis)

    # Attach analysis and raw sample for downstream agents
    plan['_analysis']    = analysis
    plan['_raw_sample']  = sample[:raw_sample_max]
    plan['_design_seed'] = config.DESIGN_SEED

    print(f"  [Planner] Done — {len(plan.get('slides', []))} slides planned")
    return plan