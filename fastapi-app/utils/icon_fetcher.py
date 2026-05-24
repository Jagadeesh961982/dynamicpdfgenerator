# utils/icon_fetcher.py
#
# MULTI-SOURCE ICON FETCHER
# ══════════════════════════
# Fetches SVG icons from multiple free CDNs at runtime and registers
# them in utils/icons.py so the rest of the pipeline can use them.
#
# SOURCE CASCADE (tried in order until one succeeds):
#   1. Built-in library    — utils/icons.py BRAND_ICONS / ICON_PATHS
#   2. Local cache         — icons_cache.json (fetched once, cached forever)
#   3. ICONIFY_SLUGS       — 200k+ icon mapping (emoji, flags, sports, etc.)
#   4. Simple Icons CDN    — 3000+ tech brand logos (cdn.simpleicons.org)
#   5. Iconify CDN direct  — fetch by Iconify prefix:name id
#   6. Iconify Search API  — search by keyword across all 200k+ icons
#
# Iconify (api.iconify.design) covers what Simple Icons can't:
#   • Sports & games (cricket, football, trophy …)  ← twemoji / noto sets
#   • Country flags (India, USA, UK …)              ← circle-flags set
#   • Finance, food, nature, general UI             ← mdi / material-symbols
#   • Tech logos not on Simple Icons                ← logos set
#
# USAGE:
#   from utils.icon_fetcher import fetch_and_register
#   fetch_and_register(["cricket", "india", "trophy"])
#   # Now icon("cricket", 48, "#..") returns the twemoji cricket bat SVG

import json
import re
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

_CACHE_FILE = Path(__file__).parent / "icons_cache.json"

# ══════════════════════════════════════════════════════════════════
#  SOURCE 1: Simple Icons slug map  (tech brands)
#  our_name → simpleicons.org slug
# ══════════════════════════════════════════════════════════════════
SIMPLEICONS_SLUGS: dict[str, str] = {
    "kafka":         "apachekafka",
    "airflow":       "apacheairflow",
    "spark":         "apachespark",
    "rabbitmq":      "rabbitmq",
    "elasticsearch": "elasticsearch",
    "mongodb":       "mongodb",
    "postgresql":    "postgresql",
    "flutter":       "flutter",
    "dart":          "dart",
    "swift":         "swift",
    "kotlin":        "kotlin",
    "rust":          "rust",
    "golang":        "go",
    "typescript":    "typescript",
    "javascript":    "javascript",
    "react":         "react",
    "vue":           "vuedotjs",
    "angular":       "angular",
    "svelte":        "svelte",
    "nextjs":        "nextdotjs",
    "nuxt":          "nuxtdotjs",
    "vite":          "vite",
    "webpack":       "webpack",
    "django":        "django",
    "flask":         "flask",
    "fastapi":       "fastapi",
    "spring":        "spring",
    "spring boot":   "springboot",
    "spring-boot":   "springboot",
    "springboot":    "springboot",
    "quarkus":       "quarkus",
    "micronaut":     "micronaut",
    "gradle":        "gradle",
    "maven":         "apachemaven",
    "rails":         "rubyonrails",
    "laravel":       "laravel",
    "dotnet":        "dotnet",
    "neo4j":         "neo4j",
    "influxdb":      "influxdb",
    "clickhouse":    "clickhouse",
    "snowflake":     "snowflake",
    "databricks":    "databricks",
    "dbt":           "dbt",
    "ansible":       "ansible",
    "puppet":        "puppet",
    "vagrant":       "vagrant",
    "argocd":        "argo",
    "harbor":        "harbor",
    "containerd":    "containerd",
    "cilium":        "cilium",
    "envoy":         "envoyproxy",
    "vault":         "vault",
    "nomad":         "nomad",
    "consul":        "consul",
    "istio":         "istio",
    "nginx":         "nginx",
    "apache":        "apache",
    "graphql":       "graphql",
    "grpc":          "grpc",
    "openapi":       "openapiinitiative",
    "openai":        "openai",
    "huggingface":   "huggingface",
    "anthropic":     "anthropic",
    "github":        "github",
    "gitlab":        "gitlab",
    "bitbucket":     "bitbucket",
    "jenkins":       "jenkins",
    "circleci":      "circleci",
    "travisci":      "travisci",
    "datadog":       "datadog",
    "newrelic":      "newrelic",
    "splunk":        "splunk",
    "pagerduty":     "pagerduty",
    "terraform":     "terraform",
    "pulumi":        "pulumi",
    "cloudflare":    "cloudflare",
    "vercel":        "vercel",
    "netlify":       "netlify",
    "supabase":      "supabase",
    "firebase":      "firebase",
}

SIMPLEICONS_COLORS: dict[str, str] = {
    "apachekafka":  "231F20", "rabbitmq":    "FF6600",
    "elasticsearch":"F04E98", "mongodb":     "4EA94B",
    "postgresql":   "4169E1", "flutter":     "54C5F8",
    "dart":         "00B4AB", "swift":       "F05138",
    "kotlin":       "7F52FF", "rust":        "CE422B",
    "go":           "00ACD7", "typescript":  "3178C6",
    "javascript":   "F7DF1E", "react":       "61DAFB",
    "vuedotjs":     "42B883", "angular":     "DD0031",
    "svelte":       "FF3E00", "nextdotjs":   "000000",
    "vite":         "646CFF", "django":      "092E20",
    "fastapi":      "009688", "spring":      "6DB33F",
    "springboot":   "6DB33F", "quarkus":     "4695EB",
    "gradle":       "02303A", "apachemaven": "C71A36",
    "ansible":      "EE0000", "datadog":     "632CA6",
    "terraform":    "7B42BC", "cloudflare":  "F38020",
    "vercel":       "000000", "firebase":    "FFCA28",
    "openai":       "412991", "huggingface": "FFD21E",
    "github":       "181717", "gitlab":      "FC6D26",
    "jenkins":      "D33833", "nginx":       "009639",
    "graphql":      "E10098", "istio":       "466BB0",
    "consul":       "F24C53", "vault":       "000000",
}

# ══════════════════════════════════════════════════════════════════
#  SOURCE 2: Iconify known slugs  (non-tech domains)
#  our_name → "iconify-prefix:icon-name"
#
#  Key sets used:
#    twemoji        — Twitter emoji (sports, flags, food, objects)
#    noto           — Google Noto emoji (same coverage, more polished)
#    circle-flags   — Round country flag icons
#    mdi            — Material Design Icons (2000+ general purpose)
#    logos          — Brand/tech logos not on Simple Icons
# ══════════════════════════════════════════════════════════════════
ICONIFY_SLUGS: dict[str, str] = {
    # ── Sports & Games ─────────────────────────────────────────────
    "cricket":              "twemoji:cricket-game",
    "cricket bat":          "twemoji:cricket-game",
    "cricket-bat":          "twemoji:cricket-game",
    "cricket ball":         "twemoji:cricket-game",
    "ipl":                  "twemoji:cricket-game",
    "football":             "twemoji:soccer-ball",
    "soccer":               "twemoji:soccer-ball",
    "basketball":           "twemoji:basketball",
    "tennis":               "twemoji:tennis",
    "baseball":             "twemoji:baseball",
    "rugby":                "twemoji:rugby-football",
    "golf":                 "twemoji:golf",
    "badminton":            "twemoji:badminton",
    "volleyball":           "twemoji:volleyball",
    "hockey":               "twemoji:field-hockey",
    "boxing":               "twemoji:boxing-glove",
    "swimming":             "twemoji:person-swimming",
    "running":              "twemoji:person-running",
    "cycling":              "twemoji:person-biking",
    "horse racing":         "twemoji:horse-racing",
    "sports":               "twemoji:sports-medal",
    "trophy":               "twemoji:trophy",
    "medal":                "twemoji:sports-medal",
    "gold medal":           "twemoji:1st-place-medal",
    "silver medal":         "twemoji:2nd-place-medal",
    "bronze medal":         "twemoji:3rd-place-medal",
    "stadium":              "mdi:stadium",
    "pitch":                "mdi:stadium",
    "scoreboard":           "mdi:scoreboard",
    "team":                 "mdi:account-group",
    "player":               "mdi:account-circle",
    "coach":                "mdi:whistle",
    "referee":              "mdi:whistle",
    "bat":                  "twemoji:cricket-game",
    "ball":                 "twemoji:cricket-game",
    "wicket":               "twemoji:cricket-game",
    # ── Country Flags ──────────────────────────────────────────────
    "india":                "circle-flags:in",
    "usa":                  "circle-flags:us",
    "united states":        "circle-flags:us",
    "uk":                   "circle-flags:gb",
    "england":              "circle-flags:gb-eng",
    "australia":            "circle-flags:au",
    "pakistan":             "circle-flags:pk",
    "south africa":         "circle-flags:za",
    "new zealand":          "circle-flags:nz",
    "west indies":          "circle-flags:wi",
    "sri lanka":            "circle-flags:lk",
    "bangladesh":           "circle-flags:bd",
    "afghanistan":          "circle-flags:af",
    "china":                "circle-flags:cn",
    "japan":                "circle-flags:jp",
    "germany":              "circle-flags:de",
    "france":               "circle-flags:fr",
    "brazil":               "circle-flags:br",
    "canada":               "circle-flags:ca",
    "russia":               "circle-flags:ru",
    "uae":                  "circle-flags:ae",
    "netherlands":          "circle-flags:nl",
    "spain":                "circle-flags:es",
    "italy":                "circle-flags:it",
    # ── Finance & Business ─────────────────────────────────────────
    "money":                "twemoji:money-bag",
    "dollar":               "twemoji:dollar-banknote",
    "rupee":                "twemoji:rupee-sign",
    "euro":                 "twemoji:euro-banknote",
    "pound":                "twemoji:pound-banknote",
    "investment":           "twemoji:chart-increasing",
    "revenue":              "twemoji:money-bag",
    "profit":               "twemoji:chart-increasing",
    "loss":                 "twemoji:chart-decreasing",
    "bank":                 "twemoji:bank",
    "coin":                 "twemoji:coin",
    "auction":              "twemoji:hammer",
    "contract":             "twemoji:handshake",
    "deal":                 "twemoji:handshake",
    "sponsor":              "twemoji:handshake",
    # ── Entertainment & Media ──────────────────────────────────────
    "movie":                "twemoji:clapper-board",
    "film":                 "twemoji:clapper-board",
    "music":                "twemoji:musical-notes",
    "gaming":               "twemoji:video-game",
    "game":                 "twemoji:video-game",
    "book":                 "twemoji:books",
    "news":                 "twemoji:newspaper",
    "camera":               "twemoji:camera",
    "microphone":           "twemoji:microphone",
    "tv":                   "twemoji:television",
    "broadcast":            "twemoji:satellite-antenna",
    "streaming":            "twemoji:television",
    # ── Food & Lifestyle ───────────────────────────────────────────
    "food":                 "twemoji:fork-and-knife-with-plate",
    "restaurant":           "twemoji:fork-and-knife-with-plate",
    "coffee":               "twemoji:hot-beverage",
    "health":               "twemoji:green-heart",
    "hospital":             "twemoji:hospital",
    "medicine":             "twemoji:pill",
    "fitness":              "twemoji:person-lifting-weights",
    # ── Nature & Environment ───────────────────────────────────────
    "earth":                "twemoji:earth-globe-asia-australia",
    "globe":                "twemoji:globe-with-meridians",
    "environment":          "twemoji:seedling",
    "tree":                 "twemoji:evergreen-tree",
    "sun":                  "twemoji:sun",
    "water":                "twemoji:droplet",
    "fire":                 "twemoji:fire",
    "lightning":            "twemoji:lightning",
    "snowflake":            "twemoji:snowflake",
    # ── General Purpose (mdi supplements ICON_PATHS) ───────────────
    "email":                "mdi:email",
    "phone":                "mdi:phone",
    "location":             "mdi:map-marker",
    "map":                  "mdi:map",
    "home":                 "mdi:home",
    "person":               "mdi:account",
    "user":                 "mdi:account",
    "group":                "mdi:account-group",
    "building":             "mdi:office-building",
    "city":                 "mdi:city",
    "truck":                "mdi:truck",
    "car":                  "mdi:car",
    "plane":                "mdi:airplane",
    "ship":                 "mdi:ferry",
    "education":            "mdi:school",
    "government":           "mdi:domain",
    "hospital":             "mdi:hospital-building",
    "factory":              "mdi:factory",
    "chart-line":           "mdi:chart-line",
    "chart-bar":            "mdi:chart-bar",
    "chart-pie":            "mdi:chart-pie",
    "api":                  "mdi:api",
    "microservices":        "mdi:hexagon-multiple",
    "certificate":          "mdi:certificate",
    "award":                "mdi:medal",
    "flag":                 "mdi:flag",
    # ── Non-tech brands often referenced ──────────────────────────
    "google":               "logos:google-icon",
    "microsoft":            "logos:microsoft-icon",
    "apple":                "logos:apple",
    "meta":                 "logos:meta",
    "amazon":               "logos:aws",
    "netflix":              "logos:netflix-icon",
    "spotify":              "logos:spotify-icon",
    "uber":                 "logos:uber",
    "tesla":                "logos:tesla",
    "twitter":              "logos:twitter",
    "x":                    "logos:x",
    "linkedin":             "logos:linkedin-icon",
    "youtube":              "logos:youtube-icon",
    "instagram":            "logos:instagram-icon",
    "whatsapp":             "logos:whatsapp-icon",
    "slack":                "logos:slack-icon",
    "zoom":                 "logos:zoom-icon",
}

# Preferred Iconify sets for keyword search (tried in order of quality)
_ICONIFY_SEARCH_PREFIXES = "twemoji,noto,circle-flags,mdi,material-symbols,logos,simple-icons"

# Iconify API base
_ICONIFY_API = "https://api.iconify.design"


# ══════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════

def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        print(f"  [IconFetcher] Warning: could not save cache: {e}")


def _http_get(url: str, timeout: int = 8) -> Optional[str]:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 PDF-Pipeline/1.0",
                "Accept":     "*/*",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_simpleicons_paths(svg_text: str) -> Optional[str]:
    """
    Extract inner SVG content from a Simple Icons SVG.
    Normalises fill to FILL placeholder so the renderer can colorise it.
    """
    inner = re.sub(r'<\?xml[^>]+\?>', '', svg_text)
    inner = re.sub(r'<svg[^>]+>',     '', inner)
    inner = re.sub(r'</svg>',          '', inner)
    inner = re.sub(r'<title>.*?</title>', '', inner, flags=re.DOTALL)
    inner = inner.strip()

    if not inner or '<path' not in inner:
        return None

    inner = re.sub(r'\bfill="[^"]*"',   'fill="FILL"', inner)
    inner = re.sub(r'\bstroke="[^"]*"', '',             inner)
    return inner if len(inner) > 20 else None


def _extract_iconify_content(svg_text: str) -> Optional[tuple[str, str, bool]]:
    """
    Parse an Iconify SVG and return (viewbox, inner_content, is_multicolor).

    is_multicolor=True  → emoji / flag style; colours are embedded, no FILL substitution needed.
    is_multicolor=False → mono icon; fill normalised to FILL placeholder.
    """
    vbox_m = re.search(r'viewBox="([^"]+)"', svg_text)
    vbox   = vbox_m.group(1) if vbox_m else "0 0 24 24"

    inner = re.sub(r'<\?xml[^>]+\?>',       '', svg_text)
    inner = re.sub(r'<svg[^>]+>',            '', inner)
    inner = re.sub(r'</svg>',                '', inner)
    inner = re.sub(r'<title>.*?</title>',    '', inner, flags=re.DOTALL)
    inner = re.sub(r'<defs>.*?</defs>',      '', inner, flags=re.DOTALL)
    inner = inner.strip()

    if not inner:
        return None

    # Detect multi-colour: 2+ distinct non-trivial hex fills → keep as-is
    fills = re.findall(r'fill="(#[0-9A-Fa-f]{3,8})"', inner)
    trivial = {'#000', '#000000', '#fff', '#ffffff', 'none', 'white', 'black'}
    unique  = {f.lower() for f in fills if f.lower() not in trivial}
    is_multicolor = len(unique) >= 2

    if not is_multicolor:
        # Mono: normalise to FILL so the caller can inject any colour
        inner = re.sub(r'fill="currentColor"',        'fill="FILL"', inner)
        inner = re.sub(r'fill="(#000000|#000|black)"', 'fill="FILL"', inner)
        if 'fill=' not in inner:
            inner = re.sub(r'stroke="currentColor"',  'stroke="FILL"', inner)

    return vbox, inner, is_multicolor


def _fetch_from_simpleicons(name_lower: str, timeout: int) -> Optional[tuple[str, str, str]]:
    """Try Simple Icons CDN. Returns (viewbox, paths, hex_color) or None."""
    slug     = SIMPLEICONS_SLUGS.get(name_lower, name_lower.replace(" ", "").replace("-", ""))
    url      = f"https://cdn.simpleicons.org/{slug}"
    svg_text = _http_get(url, timeout)
    if not svg_text:
        return None

    vbox_m   = re.search(r'viewBox="([^"]+)"', svg_text)
    vbox     = vbox_m.group(1) if vbox_m else "0 0 24 24"
    paths    = _extract_simpleicons_paths(svg_text)
    if not paths:
        return None

    raw_color = SIMPLEICONS_COLORS.get(slug, "")
    if not raw_color:
        cm = re.search(r'fill="#([0-9A-Fa-f]{6})"', svg_text)
        raw_color = cm.group(1) if cm else "555555"
    return vbox, paths, "#" + raw_color


def _fetch_from_iconify_direct(icon_id: str, timeout: int) -> Optional[tuple[str, str, str]]:
    """
    Fetch an icon from Iconify CDN by its 'prefix:name' ID.
    Returns (viewbox, inner_content, hex_color) or None.
    For multicolour icons the color is '__embedded__' (no tinting needed).
    """
    if ":" not in icon_id:
        return None
    prefix, name = icon_id.split(":", 1)
    url      = f"{_ICONIFY_API}/{prefix}/{name}.svg"
    svg_text = _http_get(url, timeout)
    if not svg_text or "<svg" not in svg_text:
        return None

    result = _extract_iconify_content(svg_text)
    if not result:
        return None
    vbox, inner, is_multicolor = result
    color = "__embedded__" if is_multicolor else "#555555"
    return vbox, inner, color


def _search_iconify(query: str, timeout: int) -> Optional[str]:
    """
    Search Iconify for the best icon matching `query`.
    Returns the top 'prefix:name' result or None.
    """
    url = (f"{_ICONIFY_API}/search"
           f"?query={urllib.parse.quote(query)}"
           f"&limit=8"
           f"&prefixes={_ICONIFY_SEARCH_PREFIXES}")
    body = _http_get(url, timeout)
    if not body:
        return None
    try:
        data  = json.loads(body)
        icons = data.get("icons", [])
        # Prefer emoji / flag sets for non-tech queries
        for ic in icons:
            prefix = ic.split(":")[0]
            if prefix in ("twemoji", "noto", "circle-flags"):
                return ic
        return icons[0] if icons else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def fetch_and_register(names: list[str], timeout: int = 8) -> dict[str, bool]:
    """
    Fetch SVG icons for each name and register them in BRAND_ICONS.

    Cascade per name:
      1. Already in built-in library           → done
      2. Already in local cache                → restore from cache
      3. ICONIFY_SLUGS known mapping           → fetch from Iconify CDN
      4. Simple Icons CDN (tech brands)        → slug lookup + fetch
      5. Iconify search API (keyword match)    → best result from 200k+ icons
      6. All sources failed                    → letter-badge fallback in icon()

    Returns dict mapping name → True (resolved) | False (all sources failed).
    """
    from utils.icons import BRAND_ICONS, register

    cache   = _load_cache()
    results: dict[str, bool] = {}
    updated = False

    for name in names:
        nl = name.lower().strip()

        # ── 1. Already built in ──────────────────────────────────
        if nl in BRAND_ICONS:
            results[name] = True
            continue

        # ── 2. Local cache ───────────────────────────────────────
        if nl in cache:
            entry = cache[nl]
            if entry.get("paths"):
                color = entry.get("color", "#555555")
                vbox  = entry.get("viewbox", "0 0 24 24")
                register(nl, entry["paths"], color, vbox)
                results[name] = True
                print(f"  [IconFetcher] cache hit  '{name}'")
                continue

        # ── 3. Iconify known slug ────────────────────────────────
        icon_id = ICONIFY_SLUGS.get(nl)
        if icon_id:
            print(f"  [IconFetcher] Iconify known '{name}' -> {icon_id}")
            result = _fetch_from_iconify_direct(icon_id, timeout)
            if result:
                vbox, paths, color = result
                register(nl, paths, color, vbox)
                cache[nl] = {"source": "iconify", "id": icon_id,
                             "paths": paths, "viewbox": vbox, "color": color}
                results[name] = True
                updated = True
                print(f"  [IconFetcher] OK  '{name}'  ({icon_id})")
                continue
            print(f"  [IconFetcher] Iconify fetch failed for {icon_id}, trying Simple Icons...")

        # ── 4. Simple Icons CDN ──────────────────────────────────
        print(f"  [IconFetcher] Simple Icons  '{name}'...")
        result = _fetch_from_simpleicons(nl, timeout)
        if result:
            vbox, paths, color = result
            register(nl, paths, color, vbox)
            cache[nl] = {"source": "simpleicons", "paths": paths,
                         "viewbox": vbox, "color": color}
            results[name] = True
            updated = True
            print(f"  [IconFetcher] OK  '{name}'  (simpleicons)")
            continue

        # ── 5. Iconify keyword search ────────────────────────────
        print(f"  [IconFetcher] Iconify search  '{name}'...")
        best_id = _search_iconify(nl, timeout)
        if best_id:
            result = _fetch_from_iconify_direct(best_id, timeout)
            if result:
                vbox, paths, color = result
                register(nl, paths, color, vbox)
                cache[nl] = {"source": "iconify-search", "id": best_id,
                             "paths": paths, "viewbox": vbox, "color": color}
                results[name] = True
                updated = True
                print(f"  [IconFetcher] OK  '{name}'  via search -> {best_id}")
                continue

        # ── 6. All sources exhausted ─────────────────────────────
        print(f"  [IconFetcher] NOT FOUND  '{name}'  (will use letter badge)")
        results[name] = False

    if updated:
        _save_cache(cache)

    return results


def detect_unknown_brands(entities: list[str]) -> list[str]:
    """
    Given entity names from the analyzer, return those not yet registered
    in the active icon library (BRAND_ICONS or ICON_PATHS or ICON_ALIASES).

    ICONIFY_SLUGS is intentionally NOT in the 'known' set: having a known
    fetch recipe doesn't mean the icon is already registered. Returning such
    names here causes fetch_and_register() to run the cascade and populate
    BRAND_ICONS for the current session (+ cache for future sessions).

    Used by the planner to decide which icons to pre-fetch before design.
    """
    from utils.icons import BRAND_ICONS, ICON_ALIASES, ICON_PATHS

    already_available = (set(BRAND_ICONS.keys())
                         | set(ICON_ALIASES.keys())
                         | set(ICON_PATHS.keys()))
    unknown = []

    for entity in entities:
        clean = entity.lower().strip()
        if len(clean) <= 2 or clean in {"the", "and", "for", "with", "api"}:
            continue
        if clean not in already_available:
            unknown.append(clean)

    return unknown
