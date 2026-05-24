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

def _chunk_text(raw: str, max_chunk_chars: Optional[int] = None) -> list[str]:
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

DOMAIN KNOWLEDGE GUIDE — when input mentions these topics, ALWAYS use these REAL names in key_facts
and key_entities. NEVER return "Team A", "Venue A", "Player X" or any placeholder:

Cricket / IPL:
  Teams (10): Mumbai Indians (MI), Chennai Super Kings (CSK), Royal Challengers Bengaluru (RCB),
              Sunrisers Hyderabad (SRH), Kolkata Knight Riders (KKR), Delhi Capitals (DC),
              Punjab Kings (PBKS), Rajasthan Royals (RR), Gujarat Titans (GT),
              Lucknow Super Giants (LSG)
  Venues: Wankhede Stadium (Mumbai), MA Chidambaram Stadium (Chennai), Eden Gardens (Kolkata),
          M. Chinnaswamy Stadium (Bengaluru), Narendra Modi Stadium (Ahmedabad),
          Arun Jaitley Stadium (Delhi), Rajiv Gandhi International Stadium (Hyderabad)
  Batters: Rohit Sharma, Virat Kohli, Shubman Gill, KL Rahul, Rishabh Pant,
           Ruturaj Gaikwad, Yashasvi Jaiswal, Abhishek Sharma, Sanju Samson
  Bowlers/All-rounders: Jasprit Bumrah, Hardik Pandya, MS Dhoni, Pat Cummins,
                        Rashid Khan, Sunil Narine, Ravindra Jadeja, Mohammed Shami, Kagiso Rabada

Other sports — always use real team names, real stadium names, real player names.
Finance — use real companies, real indices (Nifty 50, S&P 500), real market names.
ABSOLUTE RULE: "Team A / B / C", "Venue A / B", "Player X / Y" are FORBIDDEN — use actual names.

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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ★ STEP 1 — UNDERSTAND THE DATA FIRST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before assigning any visual_type, reason about what data each slide will hold:

A) DATA TYPE per theme — for each theme in the analysis, identify:
   • Does it have numeric metrics / statistics? → stat_cards_row, big_number_hero, bar_chart_annotated
   • Does it have time-ordered events or trends? → timeline_events, area_chart_gradient
   • Does it compare exactly two things (tools, approaches, before/after)? → comparison_panel
   • Does it describe a sequence of steps or a pipeline? → concept_diagram, domino_chain, funnel_diagram
   • Does it have many items with attributes (tabular)? → matrix_table, priority_table
   • Does it have 2×2 prioritization (risk/effort, impact/value)? → scatter_quadrant
     (risk_impact_matrix is RESERVED for operational content only — see Rule 10)
   • Does it have architecture or topology (nodes, zones, services)? → topology_map
   • Does it have rich descriptive text with a few supporting stats? → two_column_bullets, info_cards_grid
   • Does it have ONE dominant finding or quote? → big_number_hero, callout_hero
   • Is it a cover / intro / conclusion? → cover_hero, priority_table

B) ITEM COUNT — count the natural number of items for each slide:
   • The "data" items count MUST match what the source actually contains.
   • Do NOT pad to reach a "nice" number (e.g., don't add fake 4th card if only 3 items exist).
   • Do NOT truncate real data to fit a fixed template (e.g., don't cut 7 items to 4).
   • 2 items → 2-col layout (comparison_panel or 2-card side-by-side)
   • 3 items → 3-col row
   • 4–6 items → 2×2 or 2×3 grid
   • 7+ items → table/list layout, NOT a card grid

C) VISUAL TYPE SELECTION — rules:
   • visual_type must match the data type you identified in (A)
   • stat_cards_row is for NUMERIC metrics — NOT for descriptive text themes
   • area_chart_gradient only when data has timestamps or sequential numeric series
   • comparison_panel only when data is explicitly binary (A vs B)
   • concept_diagram / domino_chain only when data has ordered steps
   • Use info_cards_grid or two_column_bullets when data is primarily text-based
   • NEVER force numeric chart types on text-only data
   • NEVER force a 4-card grid when the data has 2 or 7 items

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ★ AESTHETIC PERSONAS — assign one per slide
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each slide MUST have an `aesthetic_persona` field. The designer uses this to apply a completely
different visual language to each slide — background, typography, card style, layout structure.

Available personas:
  editorial_dark      — Near-black bg, Playfair Display serif headlines, asymmetric layout, no white cards
  data_dashboard      — Dark bg with subtle grid, all-monospace numbers, KPI-dense, Bloomberg terminal feel
  magazine_spread     — Warm white bg, giant Playfair headlines, left-band accent, editorial structure
  infographic_vibrant — Solid accent color AS background, white card pops, dramatic central focal point
  minimalist_focus    — Pure white, ONE massive focal element (giant number/quote/icon), 70% whitespace
  technical_dense     — Dark blue-gray, ALL monospace text, sharp cards, Tokyo Night color palette
  narrative_warm      — Cream bg, Sora headlines, article-like flowing layout, soft warm cards
  vibrant_split       — Hard left/right split: dark colored panel + white panel, maximum contrast

PERSONA ASSIGNMENT RULES (CRITICAL — enforce strictly):
  1. Slide 1 (cover_hero): always "magazine_spread" or "vibrant_split"
  2. Final slide (takeaways): always "editorial_dark" or "narrative_warm"
  3. NO two adjacent slides may share the same aesthetic_persona
  4. No persona may appear more than ⌈total_slides/4⌉ times in the whole deck
  5. Dark personas (editorial_dark, data_dashboard, technical_dense) must be spaced at least
     2 slides apart from each other
  6. Suggested cycling pattern for 12 slides (warm → dark → accent flow):
     1:magazine_spread, 2:editorial_dark, 3:infographic_vibrant, 4:narrative_warm,
     5:data_dashboard, 6:vibrant_split, 7:minimalist_focus, 8:technical_dense,
     9:magazine_spread, 10:editorial_dark, 11:infographic_vibrant, 12:narrative_warm
     NOTE: Dark personas use DARK NAVY (#0F1629) not pure black — transitions look cohesive.
  7. Adapt the cycle based on content type:
     - Ops/incident content → more data_dashboard + technical_dense
     - Educational content → more magazine_spread + narrative_warm
     - Business reports → more editorial_dark + vibrant_split
     - Data analysis → more data_dashboard + infographic_vibrant

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VISUAL TYPES — with data-adaptive guidance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  cover_hero           → Full-bleed cover. Preview cards = number of key themes (2–4, not always 3).
  big_number_hero      → When ONE dominant numeric stat tells the story. Supporting stats = all available.
  stat_cards_row       → For N numeric metrics (N = actual count, grid adapts: 3-col, 4-col, 2×3).
  bar_chart_annotated  → When ≥3 labeled numeric values need comparison. Bullets = all key findings.
  area_chart_gradient  → ONLY when data has timestamps or sequential numeric series (trend over time).
  timeline_events      → For events with dates/sequence. Event count = actual events in data.
  topology_map         → For infrastructure nodes, services, or concept maps. Node count = data count.
  matrix_table         → For tabular data with 3+ columns. Row count = actual data rows.
  domino_chain         → For cause-effect chains or pipelines. Card count = actual steps in data.
  comparison_panel     → ONLY when comparing exactly 2 things (A vs B). Each panel = one side.
  priority_table       → For ranked/actionable lists. Row count = actual items.
  risk_impact_matrix   → ★ REQUIRED for alerts/logs/incidents/performance_metrics content.
                         Left: 2×2 quadrant grid. Right: Strategic Guidance + Immediate Action.
                         Each quadrant filled with real items from data — none left empty.
  scatter_quadrant     → For 2×2 priority mapping (impact/effort, risk/value). Items = all data items.
  funnel_diagram       → For pipeline stages with counts. Stage count = actual stages.
  info_cards_grid      → For descriptive text themes. Card count = actual topics (not forced to 4).
  concept_diagram      → For step-by-step flows. Step count = actual steps (3–6 ideal, adapt if more).
  two_column_bullets   → Left: key insight + metric badge. Right: bullet list. Bullets = all items.
  callout_hero         → When ONE finding is so important it deserves full-slide treatment.

COLOR MOODS:
  critical_red    → #C0392B accent (urgent, broken, failure)
  warning_amber   → #D4880E accent (degraded, at-risk)
  info_blue       → #2471A3 accent (informational, educational)
  success_green   → #1E8449 accent (achievements, solutions, health)
  neutral_slate   → #4A5568 accent (summary, conclusion, overview)
  deep_purple     → #6B46C1 accent (innovation, AI, future)
  teal_focus      → #0D9488 accent (process, flow, systems)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ★ STEP 2 — RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Slide 1 MUST be cover_hero. Final slide MUST be a conclusion/takeaways slide.
2. Use at LEAST 6 different visual_types across all slides.
3. Titles must be JOURNALISTIC and SPECIFIC — not generic labels.
   BAD: "System Overview" | GOOD: "Why Three Services Went Dark at 3AM"
4. The "data" field must contain ALL values the designer needs to render the slide.
   Include real numbers, real names, real labels — never say "see analysis".
   ★ CONTENT DENSITY — data items must be rich AND match actual content count:
   - Item count in "data" = natural count from the source, NOT a fixed 4 or 6.
   - Each item needs: "title", "value"/"stat" (if numeric), "description" (2-3 full sentences), "icon".
   - Descriptions must explain WHY the metric matters, not just repeat the number.
   - For chart slides: include full data arrays AND key_takeaways (one sentence per insight).
   - For timeline slides: each event needs "date"/"seq", "title", "description" (2 sentences).
   - BAD data: {{"facts": ["High CPU"]}}
   - GOOD data: {{"items": [{{"title": "CPU Saturation on SIDCSAPHRIAPP", "value": "94.3%",
     "description": "Application server CPU peaked at 94.3% sustained for 47 minutes between
     03:12-03:59 IST, triggering thread pool exhaustion and 1,847 queued requests. This directly
     caused the Kafka consumer lag spike and 1,847 queued downstream requests.", "icon": "cpu"}}]}}
   The designer renders EXACTLY what you put in data — thin data = empty-looking slides.
5. story_angle must explain WHY this slide matters to the audience.
6. For "icon" fields in data: use ONLY names from the AVAILABLE ICON NAMES list above.
7. Each slide needs a unique visual_type — minimize repeats.
8. "visual_description" must describe both the layout AND the data, specific enough to render from scratch.
9. If data_richness is "low", use your knowledge to create REAL, ACCURATE data values.
   Each item must have full multi-sentence descriptions with real facts, not placeholder text.
11. ★ ANTI-PLACEHOLDER ENFORCEMENT — this is non-negotiable:
    NEVER write "Team A", "Team B", "Venue A", "Venue B", "Player X", "Player Y",
    "Franchise A", "Company A", "Organization X", or ANY other letter-suffixed placeholder.
    Placeholders make slides look empty and useless. Replace every one with a REAL name.

    Cricket / IPL — use these real names everywhere in "data":
      Teams:   Mumbai Indians (MI), Chennai Super Kings (CSK), Royal Challengers Bengaluru (RCB),
               Sunrisers Hyderabad (SRH), Kolkata Knight Riders (KKR), Delhi Capitals (DC),
               Punjab Kings (PBKS), Rajasthan Royals (RR), Gujarat Titans (GT),
               Lucknow Super Giants (LSG)
      Venues:  Wankhede Stadium (Mumbai), MA Chidambaram Stadium (Chennai),
               Eden Gardens (Kolkata), M. Chinnaswamy Stadium (Bengaluru),
               Narendra Modi Stadium (Ahmedabad), Arun Jaitley Stadium (Delhi),
               Rajiv Gandhi International Stadium (Hyderabad)
      Batters: Rohit Sharma, Virat Kohli, Shubman Gill, KL Rahul, Rishabh Pant,
               Ruturaj Gaikwad, Yashasvi Jaiswal, Abhishek Sharma, Sanju Samson
      Bowlers: Jasprit Bumrah, Hardik Pandya, Pat Cummins, Rashid Khan,
               Sunil Narine, Mohammed Shami, Kagiso Rabada, Ravindra Jadeja

    Other domains — same rule: use real cities, real companies, real product names.
    If exact 2026 figures are unknown, use best known historical data with "(est.)" suffix —
    but NEVER replace the name itself with a letter placeholder.
10. ★ risk_impact_matrix — STRICT GATE:
    • ONLY allowed when content_type is ONE OF:
      infrastructure_alerts, application_logs, incident_report, performance_metrics,
      error_analysis, capacity_analysis, sre_runbook, security_audit
    • FORBIDDEN for all other content types (research_paper, business_report, how_to_guide,
      general_topic, tutorial, educational — and ANY topic where the input is not actual
      operational/log/alert data). DO NOT add it just because a topic mentions "risk".
    • When content_type IS one of the above: MUST include exactly ONE such slide.
    Use this EXACT data schema for that slide:
    {{
      "visual_type": "risk_impact_matrix",
      "data": {{
        "x_axis_label": "IMPACT",
        "y_axis_label": "EFFORT",
        "high_impact_low_effort": [
          {{"name": "Issue/item name", "icon": "icon-name", "stat": "primary metric", "detail": "host/source/context", "severity": "critical"}}
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
    Populate EVERY quadrant with real items — never empty.
    When source has several distinct issues, put 2-4 items per quadrant (not just one).
    Use "detail" for hostname, service, error class, or SLA impact so the matrix is data-dense.

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
      "visual_description": "Detailed visual + data description for the designer",
      "layout_hint": "centered | left_text_right_visual | full_visual | header_plus_grid",
      "color_mood": "neutral_slate",
      "aesthetic_persona": "magazine_spread",
      "data": {{
        "key": "value — real data, real numbers, item count matching actual content"
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
    # Aesthetic persona cycle — cohesive flow: warm → dark navy → accent → warm → dark → accent
    # Dark personas now use navy (#0F1629) not pure black — transitions feel natural not jarring
    ap_cycle = [
        'magazine_spread',    # warm cream opener
        'editorial_dark',     # dark navy
        'infographic_vibrant',# accent pop
        'narrative_warm',     # warm cream
        'data_dashboard',     # dark navy grid
        'vibrant_split',      # accent + warm split
        'minimalist_focus',   # breath — white breathing room
        'technical_dense',    # dark navy closer
    ]
    # Ops/incident content biases toward darker technical aesthetics
    ALERT_TYPES_AP = {
        'infrastructure_alerts', 'application_logs', 'incident_report',
        'performance_metrics', 'error_analysis', 'capacity_analysis',
    }
    if content_type in ALERT_TYPES_AP:
        ap_cycle = [
            'data_dashboard',     # dark grid
            'editorial_dark',     # dark navy editorial
            'technical_dense',    # mono dense
            'infographic_vibrant',# accent pop
            'vibrant_split',      # split
            'data_dashboard',     # back to grid
            'editorial_dark',     # dark
            'technical_dense',    # mono
        ]

    # Determine if this is operational/alert content requiring risk matrix
    ALERT_TYPES = {
        'infrastructure_alerts', 'application_logs', 'incident_report',
        'performance_metrics', 'error_analysis', 'capacity_analysis',
        'sre_runbook', 'security_audit',
    }
    needs_risk_matrix = content_type in ALERT_TYPES

    # Cover: preview cards = actual theme count (up to 4), not hardcoded 3
    cover_themes = themes[:4]
    slides = [{
        'slot': 1,
        'title': title,
        'subtitle': subtitle,
        'story_angle': 'Set the stage with key highlights',
        'key_insight': analysis.get('subject', ''),
        'visual_type': 'cover_hero',
        'visual_description': (
            f'Cover with title "{title}", subtitle, and {len(cover_themes)} preview theme cards '
            f'({", ".join(cover_themes)}).'
        ),
        'layout_hint': 'centered',
        'color_mood': 'neutral_slate',
        'aesthetic_persona': 'magazine_spread',
        'data': {
            'title': title,
            'subtitle': subtitle,
            'preview_cards': [
                {'title': t, 'description': f'Key aspect of this report', 'icon': 'lightbulb'}
                for t in cover_themes
            ],
        },
    }]

    for i, theme in enumerate(themes[:8], 2):
        tf = [f for f in facts if f.get('category', '').lower() == theme.lower()]
        if not tf:
            tf = facts[max(0, i-2):min(i+1, len(facts))]

        # Build items from ALL available facts for this theme — not capped at 6
        items = []
        for j, f in enumerate(tf):
            fact_text = f.get('fact', '') if isinstance(f, dict) else str(f)
            items.append({
                'title': fact_text.split('.')[0].strip() or f'Finding {j+1}',
                'value': f.get('stat', f.get('metric', '')) if isinstance(f, dict) else '',
                'description': fact_text,
                'icon': 'info' if j % 2 == 0 else 'bar-chart-2',
            })
        if not items:
            items = [{'title': f'{theme} insight', 'value': '', 'description': f'Key insights about {theme}.', 'icon': 'info'}]

        # Pick visual_type based on item count and data shape — not just a fixed cycle
        n = len(items)
        has_values = any(item.get('value') for item in items)
        if n == 1:
            vt = 'big_number_hero' if has_values else 'callout_hero'
        elif n == 2:
            vt = 'comparison_panel'
        elif has_values and n <= 6:
            vt = 'stat_cards_row'
        elif has_values and n > 6:
            vt = 'bar_chart_annotated'
        elif n <= 6:
            vt = 'info_cards_grid'
        else:
            vt = vt_cycle[(i - 2) % len(vt_cycle)]

        slides.append({
            'slot': i,
            'title': theme,
            'subtitle': f'Deep dive into {theme}',
            'story_angle': f'Analysis of {theme} — why it matters and what the data shows',
            'key_insight': tf[0].get('fact', f'Key insights about {theme}') if tf else f'Key insights about {theme}',
            'visual_type': vt,
            'visual_description': (
                f'{vt} showing {n} items about {theme} with detailed data.'
            ),
            'layout_hint': 'left_text_right_visual',
            'color_mood': cm_cycle[(i - 2) % len(cm_cycle)],
            'aesthetic_persona': ap_cycle[(i - 2) % len(ap_cycle)],
            'data': {'theme': theme, 'items': items},
        })

    # Add risk_impact_matrix for operational content (guaranteed via Python renderer)
    if needs_risk_matrix:
        # Extract items from facts by importance
        critical = [f.get('fact', '') for f in facts if f.get('importance') == 'high']
        medium   = [f.get('fact', '') for f in facts if f.get('importance') == 'medium']
        low_f    = [f.get('fact', '') for f in facts if f.get('importance') == 'low']
        entities = analysis.get('key_entities', [])

        def _fact_to_item(
            fact_str: str, icon_name: str = 'alert-circle', severity: str = 'high',
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

        hi_lo_items = [_fact_to_item(f, 'zap', 'critical') for f in critical[:4]]
        hi_hi_items = [_fact_to_item(f, 'database', 'high') for f in critical[4:8]]
        lo_lo_items = [_fact_to_item(f, 'settings', 'low') for f in low_f[:4]]
        lo_hi_items = [_fact_to_item(f, 'git-branch', 'medium') for f in medium[:4]]

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
            'aesthetic_persona': 'technical_dense',
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
        'aesthetic_persona': 'editorial_dark',
        'data': {'themes': themes[:6], 'top_facts': [f.get('fact', '') for f in facts[:5]]},
    })

    return {
        'report_title': title,
        'report_subtitle': subtitle,
        'audience': analysis.get('audience', 'General'),
        'slides': slides,
    }


# ══════════════════════════════════════════════════════════════════
#  PLAN QUALITY VALIDATION
# ══════════════════════════════════════════════════════════════════

import re as _re

_PLACEHOLDER_PATTERNS = [
    (r'\bTeam [A-Z]\b',        "team placeholder (e.g. 'Team A')"),
    (r'\bVenue [A-Z]\b',       "venue placeholder (e.g. 'Venue A')"),
    (r'\bPlayer [A-Z]\b',      "player placeholder (e.g. 'Player X')"),
    (r'\bFranchise [A-Z]\b',   "franchise placeholder"),
    (r'\bCompany [A-Z]\b',     "company placeholder"),
    (r'\bOrganization [A-Z]\b',"organization placeholder"),
    (r'\bCity [A-Z]\b',        "city placeholder"),
    (r'\bTeam \d\b',           "numbered team placeholder (e.g. 'Team 1')"),
    (r'\bVenue \d\b',          "numbered venue placeholder (e.g. 'Venue 1')"),
]

def _validate_plan_quality(plan: dict) -> list:
    """Scan plan JSON for placeholder names; return list of warning strings."""
    plan_str = json.dumps(plan)
    warnings = []
    for pattern, description in _PLACEHOLDER_PATTERNS:
        matches = _re.findall(pattern, plan_str)
        if matches:
            unique = list(dict.fromkeys(matches))[:5]
            warnings.append(f"{description}: {unique}")
    return warnings


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def _use_full_document(raw_data: str) -> bool:
    """
    Return True when the active provider supports a large enough context window
    to process the entire document in one pass — no chunking needed.

    Gemma 4 (27B / 12B) has a 256K / 128K token context window.  At ~4 chars/token
    that's ~200K chars before we need to fall back to chunking.  When enabled, the
    analyzer sees the COMPLETE document, which dramatically improves fact recall for
    large CSVs, multi-page PDFs, and log files.
    """
    provider = getattr(config, "PROVIDER", "openrouter")
    use_long = getattr(config, "USE_LONG_CONTEXT", True)
    if not use_long:
        return False
    # Long-context mode is meaningful for Ollama (local Gemma 4) and for OpenRouter
    # when a large-context Gemma 4 model is configured.
    long_ctx_chars = int(getattr(config, "GEMMA4_LONG_CONTEXT_CHARS", 200_000))
    if provider == "ollama":
        return len(raw_data) <= long_ctx_chars
    if provider == "openrouter":
        model_all = (
            getattr(config, "MODEL_ANALYZER", "") or
            getattr(config, "MODEL_PLANNER", "")
        )
        if "gemma-4" in model_all or "gemma4" in model_all:
            return len(raw_data) <= long_ctx_chars
    return False


def run(raw_data: str) -> dict:
    """
    Two-pass pipeline:
      Pass 1: Analyze content
        — Gemma 4 path:    full document in ONE shot (256K context, no chunking)
        — Fallback path:   chunk → summarize each chunk → synthesize
      Pass 2: Plan slide narrative (with design seed for visual variety)
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

    total_chars = len(raw_data)

    if not raw_data.strip():
        print("  [Planner] WARNING: Empty input")
        return {}

    # ── PASS 1A: Prepare document sample for the Analyzer ─────────
    #
    # Gemma 4 long-context path: feed the ENTIRE document directly.
    # No chunking, no summarization, no information loss.
    # The model sees everything in one pass — same as a human reading the whole file.
    #
    # Legacy fallback (non-Gemma-4 providers): chunk → pre-summarize → synthesize.

    chunk_summaries_section = ""

    if _use_full_document(raw_data):
        long_ctx_chars = int(getattr(config, "GEMMA4_LONG_CONTEXT_CHARS", 200_000))
        sample = raw_data[:long_ctx_chars]
        chunks = [sample]
        provider = getattr(config, "PROVIDER", "openrouter")
        model_label = getattr(config, "OLLAMA_MODEL", "gemma4") if provider == "ollama" else "Gemma 4"
        print(
            f"  [Planner] ✨ Gemma 4 long-context mode: full document in one pass "
            f"({len(sample):,} chars, no chunking) — {model_label}"
        )
    else:
        chunks = _chunk_text(raw_data)
        if not chunks:
            print("  [Planner] WARNING: Empty input after chunking")
            return {}

        if len(chunks) > 4:
            print(f"  [Planner] Large input ({len(chunks)} chunks) — pre-summarizing all chunks...")
            summaries = _summarize_chunks(chunks)
            all_facts, all_entities, all_anomalies = [], [], []
            for s in summaries:
                all_facts.extend(s.get('facts', []))
                all_entities.extend(s.get('entities', []))
                all_anomalies.extend(s.get('anomalies', []))
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
            sample = chunks[0][:first_n] + "\n\n---\n\n" + chunks[-1][:last_n]
        else:
            joined = "\n\n---\n\n".join(chunks)
            sample = joined[: min(len(joined), join_max)]

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

    # Warn when the LLM used placeholder names despite instructions
    quality_warnings = _validate_plan_quality(plan)
    if quality_warnings:
        print("  [Planner] WARNING — placeholder names detected in plan output:")
        for w in quality_warnings:
            print(f"    - {w}")
        print("  [Planner] Hint: add more specific real-world names to the prompt topic next time.")

    # Strip risk_impact_matrix slides injected by LLM for non-operational content
    _OPS_TYPES = {
        'infrastructure_alerts', 'application_logs', 'incident_report',
        'performance_metrics', 'error_analysis', 'capacity_analysis',
        'sre_runbook', 'security_audit',
    }
    content_type = analysis.get('content_type', '')
    if content_type not in _OPS_TYPES:
        before = len(plan.get('slides', []))
        plan['slides'] = [
            s for s in plan.get('slides', [])
            if s.get('visual_type') != 'risk_impact_matrix'
        ]
        removed = before - len(plan['slides'])
        if removed:
            print(f"  [Planner] Stripped {removed} risk_impact_matrix slide(s) — content_type={content_type!r} is not operational")
        # Re-number slots after removal
        for idx, s in enumerate(plan['slides'], 1):
            s['slot'] = idx

    # Attach analysis and raw sample for downstream agents
    plan['_analysis']    = analysis
    plan['_raw_sample']  = sample[:raw_sample_max]
    plan['_design_seed'] = config.DESIGN_SEED

    print(f"  [Planner] Done — {len(plan.get('slides', []))} slides planned")
    return plan