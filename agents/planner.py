# agents/planner.py
#
# AGENT 1 — NARRATIVE PLANNER
# ════════════════════════════
# Step 1 (Python): Parse raw data → exact counts, time series, patterns
# Step 2 (LLM):    Given parsed facts → design 12 slide STORIES
#                  Each story has: a unique angle/title, the key insight,
#                  what visual would best tell that story, and the data to use.
#
# OUTPUT: slide_plan.json  — list of 12 slide dicts, each with:
#   {
#     "slot": 1,
#     "title": "The Kafka Backlog: 785,744 Messages Waiting",
#     "subtitle": "Executive SRE Diagnostic Report",
#     "story_angle": "Show the scale of the problem with a single shocking number",
#     "key_insight": "Consumer lag grew 8% over 24h, data pipeline SLA at risk",
#     "data": { ... only the relevant data for this slide ... },
#     "visual_type": "big_number_hero | bar_chart | topology | funnel | timeline | etc.",
#     "visual_description": "A large 785,744 in red center, with a small bottle-neck SVG",
#     "layout_hint": "centered | left_text_right_visual | full_visual | two_col",
#     "color_mood": "critical_red | warning_amber | info_blue | neutral",
#   }

import re, sys, json
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call_json
import config


# ══════════════════════════════════════════════════════════════════
#  PYTHON PARSER  (token-free, handles any volume)
# ══════════════════════════════════════════════════════════════════

def _classify(subject: str) -> str:
    s = subject
    if 'Kafka_Consumer_Lag' in s or 'Kafka Consumer Lag' in s: return 'Kafka Consumer Lag'
    if 'DatasourceError' in s:    return 'Datasource Error'
    if 'PNC_POD CPU' in s or 'pod cpu' in s.lower(): return 'Kubernetes Pod CPU'
    if 'Windows Disk' in s:       return 'Windows Disk Space'
    if 'Windows Memory' in s:     return 'Windows Memory'
    if 'Linux_High_Disk' in s or 'Linux HighDisk' in s or 'HighDiskSpace' in s:
                                   return 'Linux Disk Space'
    if 'Average_DNS_Lookup' in s or 'DNS_Lookup' in s: return 'DNS Lookup Latency'
    if 'Http_Response_Time' in s: return 'HTTP Response Time'
    if 'Http_Status_Code' in s:   return 'HTTP Status Code'
    if 'hit rate' in s.lower():   return 'Redis Cache Hit Rate'
    if 'MongoDB' in s or 'clients currently' in s: return 'MongoDB Connections'
    return 'Other'


def _parse_raw(raw: str) -> dict:
    """Parse every alert block. Return rich structured facts."""
    blocks = [b.strip() for b in raw.split('========== ALERT ==========') if b.strip()]
    alerts = []
    for b in blocks:
        def g(f, _b=b):
            m = re.search(rf'{f}\s*:\s*(.+)', _b)
            return m.group(1).strip() if m else ''
        alerts.append({
            'subject':     g('Subject'),
            'description': g('Description'),
            'status':      g('Status'),
            'time':        g('Time'),
            'date':        g('Date'),
            'agent':       g('Agent'),
            'raw':         b,
        })
    if not alerts:
        return {}

    # ── Time range ──────────────────────────────────────────────
    times = []
    for a in alerts:
        try:
            times.append(datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M:%S"))
        except: pass
    times.sort()
    t0, t1 = (times[0] if times else None), (times[-1] if times else None)

    # ── Counts ──────────────────────────────────────────────────
    type_counts = Counter(_classify(a['subject']) for a in alerts)
    total       = len(alerts)
    firing      = sum(1 for a in alerts if 'Firing'   in a['status'])
    resolved    = sum(1 for a in alerts if 'Resolved' in a['status'])

    # ── Hosts ────────────────────────────────────────────────────
    hosts = Counter()
    host_types = defaultdict(set)
    for a in alerts:
        ag = a['agent'].strip()
        if ag and ag.lower() != 'nan':
            hosts[ag] += 1
            host_types[ag].add(_classify(a['subject']))

    # ── Series: Kafka lag ─────────────────────────────────────────
    kafka_series = []
    for a in alerts:
        if 'Kafka' in _classify(a['subject']):
            m = re.search(r'current lag count (\d+)', a['description'])
            if m:
                try:
                    dt = datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M:%S")
                    kafka_series.append((dt, int(m.group(1))))
                except: pass
    kafka_series.sort()

    # ── Series: CPU ───────────────────────────────────────────────
    cpu_series = []
    for a in alerts:
        if 'Kubernetes Pod CPU' in _classify(a['subject']):
            m = re.search(r'current utilization is ([\d.]+)%', a['description'])
            if m:
                try:
                    dt = datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M:%S")
                    cpu_series.append((dt, float(m.group(1))))
                except: pass
    cpu_series.sort()

    # ── Critical disk hosts ───────────────────────────────────────
    critical_disk = {}
    for a in alerts:
        if 'Disk' in _classify(a['subject']):
            m = re.search(r'([\d.]+)%', a['description'])
            ag = a['agent'].strip()
            if m and ag and ag.lower() != 'nan':
                pct = float(m.group(1))
                if ag not in critical_disk or pct > critical_disk[ag]:
                    critical_disk[ag] = pct

    # ── Redis nodes ───────────────────────────────────────────────
    redis_nodes = {}
    for a in alerts:
        if 'Redis' in _classify(a['subject']):
            m = re.search(r'Redis Node (\S+)', a['description'])
            if m:
                node = m.group(1)
                hr = re.search(r'hit rate[:\s]*([\d.]+)%', a['description'], re.I)
                redis_nodes[node] = float(hr.group(1)) if hr else 0.0

    # ── MongoDB connections ───────────────────────────────────────
    mongo_connections = {}
    for a in alerts:
        if 'MongoDB' in _classify(a['subject']):
            m = re.search(r'(\d+) clients currently', a['description'])
            ag = a['agent'].strip()
            if m and ag and ag.lower() != 'nan':
                mongo_connections[ag] = max(mongo_connections.get(ag, 0), int(m.group(1)))

    # ── DNS / HTTP details ────────────────────────────────────────
    dns_projects = set()
    for a in alerts:
        if 'DNS' in _classify(a['subject']):
            m = re.search(r'project[:\s]+([^\n,]+)', a['description'], re.I)
            if m: dns_projects.add(m.group(1).strip()[:60])
    http_hosts = set()
    for a in alerts:
        if 'HTTP' in _classify(a['subject']):
            m = re.search(r'url[:\s]+(\S+)', a['description'], re.I)
            if m: http_hosts.add(m.group(1).strip()[:60])

    # ── Flapping detection ────────────────────────────────────────
    fr = defaultdict(lambda: {'fire': 0, 'resolve': 0, 'times': []})
    for a in alerts:
        key = re.sub(r'\[(FIRING|RESOLVED)[^\]]*\]\s*', '', a['subject']).strip()[:80]
        try:
            t = datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M:%S")
            fr[key]['times'].append(t)
        except: pass
        if 'Firing'   in a['status']: fr[key]['fire']    += 1
        if 'Resolved' in a['status']: fr[key]['resolve'] += 1

    flapping = []
    for k, v in sorted(fr.items(), key=lambda x: x[1]['fire'] + x[1]['resolve'], reverse=True):
        if v['fire'] > 1 and v['resolve'] > 0:
            name = re.sub(r'\[[^\]]+\]', '', k).strip()
            name = re.sub(r'\s+', ' ', name).strip()
            flapping.append({
                'name':     name[:65],
                'fires':    v['fire'],
                'resolves': v['resolve'],
                'density':  min(0.95, v['fire'] / max(v['fire'] + v['resolve'], 1)),
                'type':     _classify(k),
            })
    flapping = flapping[:6]

    # ── Duration & time labels ────────────────────────────────────
    if t0 and t1:
        delta  = t1 - t0
        total_h = int(delta.total_seconds() // 3600)
        total_m = int((delta.total_seconds() % 3600) // 60)
        dur    = f"{total_h}h {total_m}min" if total_h else f"{total_m} minutes"
        span_h = delta.total_seconds() / 3600
        step_m = 180 if span_h > 12 else (60 if span_h > 6 else 30)
        labels = []
        cur = t0
        while cur <= t1 and len(labels) < 9:
            labels.append(cur.strftime('%Y-%m-%d %H:%M'))
            cur += timedelta(minutes=step_m)
        if not labels or labels[-1] != t1.strftime('%Y-%m-%d %H:%M'):
            labels.append(t1.strftime('%Y-%m-%d %H:%M'))
    else:
        dur = "unknown"; labels = []

    # ── Sample series helper ──────────────────────────────────────
    def _sample(series, n=8):
        if not series: return []
        step = max(1, len(series) // n)
        pts  = series[::step][:n]
        return [{'label': dt.strftime('%H:%M'), 'value': round(v, 1)} for dt, v in pts]

    # ── Team mapping ──────────────────────────────────────────────
    team_map = defaultdict(set)
    for a in alerts:
        s = a['subject']
        t = _classify(s)
        if 'DevOps'    in s: team_map['DevOps'].add(t)
        if 'IT Ops'    in s: team_map['IT Ops'].add(t)
        if 'DBA'       in s: team_map['DBA Team'].add(t)
        if 'Developer' in s: team_map['Developers'].add(t)

    # ── Top offenders ─────────────────────────────────────────────
    top_offenders = [
        {
            'host': h,
            'alert_types': sorted(host_types.get(h, {'?'}))[:3],
            'count': c,
        }
        for h, c in hosts.most_common(6)
    ]

    return {
        'total': total, 'firing': firing, 'resolved': resolved,
        'type_counts': dict(type_counts),
        'hosts': dict(hosts.most_common(8)),
        'host_types': {k: list(v) for k, v in host_types.items()},
        'kafka_max_lag': max((v for _, v in kafka_series), default=0),
        'kafka_min_lag': min((v for _, v in kafka_series), default=0),
        'kafka_series':  _sample(kafka_series),
        'cpu_max':       max((v for _, v in cpu_series), default=0),
        'cpu_series':    _sample(cpu_series),
        'critical_disk': critical_disk,   # {host: pct}
        'redis_nodes':   redis_nodes,     # {node: hit_rate}
        'mongo_connections': mongo_connections,
        'dns_projects':  list(dns_projects)[:4],
        'http_hosts':    list(http_hosts)[:4],
        'flapping':      flapping,
        'top_offenders': top_offenders,
        'time_start':    t0.strftime('%Y-%m-%d %H:%M') if t0 else '',
        'time_end':      t1.strftime('%Y-%m-%d %H:%M') if t1 else '',
        'date_start':    t0.date().isoformat() if t0 else '',
        'date_end':      t1.date().isoformat() if t1 else '',
        'duration':      dur,
        'time_labels':   labels,
        'team_map':      {k: list(v) for k, v in team_map.items()},
    }


# ══════════════════════════════════════════════════════════════════
#  LLM PROMPT: NARRATIVE PLANNER
#  Given exact parsed facts → design 12 bespoke slide stories
# ══════════════════════════════════════════════════════════════════

PLANNER_PROMPT = """You are an elite SRE presentation architect at a top tech company.
You have been given EXACT pre-parsed infrastructure alert data.
Design a {n_slides}-slide executive PDF report that tells a COMPELLING, SPECIFIC story.

STYLE TARGET: Match the quality of NotebookLM reports — each slide must have:
  - A unique, journalistic TITLE (not generic like "Alert Overview")
  - A specific INSIGHT that would surprise or inform an executive
  - A visual that BEST SHOWS that specific insight (not just "a chart")
  - Data from the parsed facts (exact numbers, real hostnames, real timestamps)

VISUAL TYPES you can use (pick the best fit per slide):
  - big_number_hero      : huge single stat + context (e.g. "785,744 messages")
  - bar_chart_annotated  : bar chart with threshold lines and callouts
  - area_chart_gradient  : area/line chart showing trends over time
  - funnel_diagram       : alert storm → categories → root causes
  - topology_map         : system topology with colored severity dots
  - matrix_table         : teams × impact grid
  - flap_chart           : firing/resolved cycle visualization with actual threshold line
  - domino_chain         : cascading failure cards with arrows
  - comparison_panel     : side-by-side comparison panels
  - priority_table       : action table with system, fix, tuning columns
  - scatter_quadrant     : risk (y) vs frequency (x) quadrant chart
  - stat_cards_row       : 4 metric cards in a row
  - timeline_events      : horizontal timeline of key events
  - cover_hero           : large title + 3 preview cards (for slide 1 only)

LAYOUT OPTIONS:
  - centered             : visual in center, short context below
  - left_text_right_visual : key insight left, custom visual right
  - full_visual          : data visualization fills most of the slide
  - two_panel            : two equal panels side by side
  - header_plus_grid     : heading + grid of cards/items below

COLOR MOODS (use consistently per slide):
  - critical_red   : #C0392B accent — urgent, broken, immediate action
  - warning_amber  : #D4880E accent — degraded, at-risk, watch closely
  - info_blue      : #2471A3 accent — informational, monitoring, context
  - neutral        : #555555 accent — conclusion, recommendations, summary

EXACT PARSED FACTS:
{facts}

RULES:
1. Slide 1 MUST be a cover with date range and 3 preview-card highlights
2. Final slide MUST be action-oriented recommendations
3. Each slide must use DIFFERENT visual_type — no two slides the same
4. Use EXACT numbers from the facts — never make up values
5. Titles must be SPECIFIC like "Kafka Backlog: 785K Messages" not "Queue Issues"
6. visual_description must be detailed enough for an LLM to draw it from scratch
7. Include the actual data values needed in the "data" field for each slide
8. Every slide must have a clear story_angle — WHY does this slide matter?

Return ONLY valid JSON (no markdown, no fences):
{{
  "report_title": "Specific report title with dates",
  "report_subtitle": "Executive SRE Diagnostic Report",
  "environment": "RIL Core Infrastructure",
  "audience": "SRE / Engineering Leadership",
  "slides": [
    {{
      "slot": 1,
      "title": "Observability Diagnostics: March 23-24 System Telemetry Review",
      "subtitle": "Separating Signal from Noise in Enterprise Infrastructure",
      "story_angle": "Cover slide: set the stage with 3 key preview insights",
      "key_insight": "342 alerts condensed to 6 actionable root causes",
      "visual_type": "cover_hero",
      "visual_description": "Three preview cards showing: (1) Kafka 785K lag backlog diagram, (2) Storage 99.9% critical bar, (3) flapping 80% threshold chart. Date badge at top center. Title large bold. Subtitle line. Three target badges at bottom.",
      "layout_hint": "centered",
      "color_mood": "neutral",
      "data": {{
        "date_range": "March 23-24, 2026",
        "total_alerts": 342,
        "preview_items": [
          {{"label": "System Telemetry Review", "sub": "Key metrics and system performance indicators"}},
          {{"label": "Alert Tuning & Noise Reduction", "sub": "Optimize critical thresholds, separate incidents from noise"}},
          {{"label": "Resource Exhaustion Analysis", "sub": "Identify infrastructure health, bottlenecks, capacity limits"}}
        ]
      }}
    }},
    ... (continue for all {n_slides} slides)
  ]
}}"""


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(raw_data: str) -> dict:
    print("  [Planner] Step 1/2: Python parsing every alert block...")
    p = _parse_raw(raw_data)
    if not p:
        print("  [Planner] WARNING: No alerts parsed — check input format")
        return {}

    print(f"    {p['total']} alerts | {len(p['type_counts'])} types | span: {p['duration']}")
    print(f"    flapping: {len(p['flapping'])} | critical disk: {list(p['critical_disk'].keys())}")
    print(f"    kafka lag: {p['kafka_min_lag']:,} → {p['kafka_max_lag']:,} | cpu_max: {p['cpu_max']}%")

    # Build compact facts JSON for the LLM (only numbers and strings, no raw text)
    facts = json.dumps({
        'total_alerts':         p['total'],
        'firing':               p['firing'],
        'resolved':             p['resolved'],
        'duration':             p['duration'],
        'time_start':           p['time_start'],
        'time_end':             p['time_end'],
        'alert_type_counts':    p['type_counts'],
        'top_6_hosts_by_count': dict(list(p['hosts'].items())[:6]),
        'kafka_lag_min':        p['kafka_min_lag'],
        'kafka_lag_max':        p['kafka_max_lag'],
        'kafka_series':         p['kafka_series'],
        'cpu_max_pct':          p['cpu_max'],
        'cpu_series':           p['cpu_series'],
        'disk_utilization':     p['critical_disk'],
        'redis_hit_rates':      p['redis_nodes'],
        'mongo_connections':    p['mongo_connections'],
        'dns_projects':         p['dns_projects'],
        'http_problem_hosts':   p['http_hosts'],
        'flapping_top6':        [
            {'name': f['name'], 'fires': f['fires'], 'resolves': f['resolves'], 'type': f['type']}
            for f in p['flapping']
        ],
        'top_offenders':        p['top_offenders'],
        'teams_affected':       p['team_map'],
        'time_labels':          p['time_labels'],
    }, indent=2)[:4000]

    print("  [Planner] Step 2/2: LLM designing slide narratives...")
    try:
        plan = call_json(
            PLANNER_PROMPT.format(facts=facts, n_slides=config.N_SLIDES),
            key="planner",
            max_tokens=8000
        )
    except Exception as e:
        print(f"    [Planner] LLM failed: {e}")
        plan = {}

    if not plan.get('slides'):
        print("    [Planner] Warning: LLM returned no slides — building fallback plan")
        plan = _fallback_plan(p)

    # Attach parsed data to the plan so agents 2+3 can access raw values
    plan['_parsed'] = p
    plan['_facts_json'] = facts
    n = len(plan.get('slides', []))
    print(f"  [Planner] Done — {n} slides planned")
    return plan


def _fallback_plan(p: dict) -> dict:
    """Minimal fallback if LLM completely fails."""
    tc = p['type_counts']
    top3 = sorted(tc.items(), key=lambda x: -x[1])[:3]
    slides = [
        {
            'slot': 1, 'title': f"Infrastructure Alert Analysis: {p['date_start']} to {p['date_end']}",
            'subtitle': 'Executive SRE Diagnostic Report',
            'story_angle': 'Cover', 'key_insight': f"{p['total']} alerts over {p['duration']}",
            'visual_type': 'cover_hero', 'layout_hint': 'centered', 'color_mood': 'neutral',
            'visual_description': 'Cover with title, date, and key stats',
            'data': {'total': p['total'], 'duration': p['duration'],
                     'time_start': p['time_start'], 'time_end': p['time_end']},
        },
        {
            'slot': 2, 'title': 'Executive Snapshot: Alert Volume',
            'subtitle': '', 'story_angle': 'Key metrics at a glance',
            'key_insight': f"{p['firing']} still firing, {p['resolved']} resolved",
            'visual_type': 'stat_cards_row', 'layout_hint': 'full_visual', 'color_mood': 'critical_red',
            'visual_description': '4 stat cards: total, firing, kafka lag, cpu max',
            'data': {'total': p['total'], 'firing': p['firing'], 'resolved': p['resolved'],
                     'kafka_max': p['kafka_max_lag'], 'cpu_max': p['cpu_max']},
        },
    ]
    for i, (itype, cnt) in enumerate(top3, 3):
        slides.append({
            'slot': i, 'title': f"Deep Dive: {itype}",
            'subtitle': '', 'story_angle': f"Analysis of {itype}",
            'key_insight': f"{cnt} alerts ({round(cnt/p['total']*100)}% of total)",
            'visual_type': 'bar_chart_annotated', 'layout_hint': 'left_text_right_visual',
            'color_mood': ['critical_red','warning_amber','info_blue'][i-3],
            'visual_description': f"Bar chart showing {itype} alert count over time",
            'data': {'name': itype, 'count': cnt},
        })

    slides.append({
        'slot': len(slides)+1, 'title': 'Recommendations & Next Steps',
        'subtitle': '', 'story_angle': 'Actionable fixes',
        'key_insight': 'Three priority actions to reduce alert noise',
        'visual_type': 'priority_table', 'layout_hint': 'full_visual', 'color_mood': 'neutral',
        'visual_description': 'Table with system, fix, tune columns',
        'data': {'top_issues': [t for t, _ in top3]},
    })

    return {
        'report_title': f"Infrastructure Alert Analysis: {p['date_start']} to {p['date_end']}",
        'report_subtitle': 'Executive SRE Diagnostic Report',
        'environment': 'Core Infrastructure',
        'audience': 'SRE / Engineering Leadership',
        'slides': slides,
    }
