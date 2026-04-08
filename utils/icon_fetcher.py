# utils/icon_fetcher.py
#
# OPTIONAL DYNAMIC ICON FETCHER
# ══════════════════════════════
# Fetches brand SVG paths from Simple Icons (simpleicons.org) at runtime
# and registers them permanently in utils/icons.py's BRAND_ICONS.
#
# HOW IT WORKS:
#   1. Analyzer detects brand entities (Kafka, Flutter, Nginx, etc.)
#   2. This module checks if they're already in BRAND_ICONS
#   3. If not, fetches from Simple Icons CDN (3000+ tech brands)
#   4. Saves to local cache file (icons_cache.json) — fetched once, cached forever
#   5. Registers in BRAND_ICONS so the rest of the pipeline uses them
#
# Simple Icons CDN: https://cdn.simpleicons.org/{slug}
# Returns: full SVG. We extract the <path> element.
#
# USAGE:
#   from utils.icon_fetcher import fetch_and_register
#   fetch_and_register(["kafka", "flutter", "mongodb"])
#   # Now icon("kafka", 48, "#231F20") returns the real Kafka logo

import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# Cache file sits next to this module
_CACHE_FILE = Path(__file__).parent / "icons_cache.json"

# Simple Icons brand slug mappings (their slugs differ from common names)
# Format: our_name → simpleicons_slug
SIMPLEICONS_SLUGS: dict[str, str] = {
    # The slug is the brand name lowercased, spaces/symbols removed
    # We list non-obvious ones here; obvious ones auto-map name→name
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

# Simple Icons brand default colors (hex, no #)
SIMPLEICONS_COLORS: dict[str, str] = {
    "apachekafka":     "231F20", "rabbitmq":       "FF6600",
    "elasticsearch":   "F04E98", "mongodb":        "4EA94B",
    "postgresql":      "4169E1", "flutter":        "54C5F8",
    "dart":            "00B4AB", "swift":          "F05138",
    "kotlin":          "7F52FF", "rust":           "CE422B",
    "go":              "00ACD7", "typescript":     "3178C6",
    "javascript":      "F7DF1E", "react":          "61DAFB",
    "vuedotjs":        "42B883", "angular":        "DD0031",
    "svelte":          "FF3E00", "nextdotjs":      "000000",
    "vite":            "646CFF", "django":         "092E20",
    "fastapi":         "009688", "spring":         "6DB33F",
    "ansible":         "EE0000", "datadog":        "632CA6",
    "terraform":       "7B42BC", "cloudflare":     "F38020",
    "vercel":          "000000", "firebase":       "FFCA28",
    "openai":          "412991", "huggingface":    "FFD21E",
    "github":          "181717", "gitlab":         "FC6D26",
    "jenkins":         "D33833", "nginx":          "009639",
    "graphql":         "E10098", "istio":          "466BB0",
    "consul":          "F24C53", "vault":          "000000",
}


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


def _extract_path_from_svg(svg_text: str) -> Optional[str]:
    """Extract the path/shape elements from a Simple Icons SVG."""
    # Remove XML declaration and outer <svg> wrapper
    inner = re.sub(r'<\?xml[^>]+\?>', '', svg_text)
    inner = re.sub(r'<svg[^>]+>', '', inner)
    inner = re.sub(r'</svg>', '', inner)
    inner = inner.strip()

    # Simple Icons use a single <path> with role="img" or title
    # Strip title elements
    inner = re.sub(r'<title>.*?</title>', '', inner, flags=re.DOTALL)
    inner = inner.strip()

    if not inner or '<path' not in inner:
        return None

    # Replace any existing fill with FILL placeholder
    inner = re.sub(r'\bfill="[^"]*"', 'fill="FILL"', inner)
    inner = re.sub(r'\bstroke="[^"]*"', '', inner)

    return inner if len(inner) > 20 else None


def _fetch_svg(slug: str, timeout: int = 8) -> Optional[str]:
    """Fetch SVG from Simple Icons CDN."""
    url = f"https://cdn.simpleicons.org/{slug}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 PDF-Pipeline/1.0",
                "Accept": "image/svg+xml,*/*",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None


def fetch_and_register(names: list[str], timeout: int = 8) -> dict[str, bool]:
    """
    Fetch SVG icons for the given brand names from Simple Icons CDN
    and register them in BRAND_ICONS.

    Args:
        names:   List of brand name strings (e.g. ["kafka", "flutter"])
        timeout: HTTP timeout per request in seconds

    Returns:
        Dict mapping name → True (fetched/cached) | False (failed)

    This function is called by the analyzer when it detects unknown
    brand entities in the content. Cached results are used on retry.
    """
    from utils.icons import BRAND_ICONS, BRAND_COLORS, register

    cache   = _load_cache()
    results = {}
    updated = False

    for name in names:
        name_lower = name.lower().strip()

        # Already in our built-in library
        if name_lower in BRAND_ICONS:
            results[name] = True
            continue

        # Check cache
        if name_lower in cache:
            entry = cache[name_lower]
            if entry.get("paths"):
                slug  = entry.get("slug", name_lower)
                color = "#" + SIMPLEICONS_COLORS.get(slug, "666666")
                vbox  = entry.get("viewbox", "0 0 24 24")
                register(name_lower, entry["paths"], color, vbox)
                results[name] = True
                continue

        # Resolve slug
        slug = SIMPLEICONS_SLUGS.get(name_lower, name_lower)

        print(f"  [IconFetcher] Fetching '{name}' from Simple Icons (slug: {slug})...")
        svg_text = _fetch_svg(slug, timeout)

        if not svg_text:
            print(f"  [IconFetcher] ✗ '{name}' not found")
            results[name] = False
            continue

        # Try to find viewBox
        vbox_m = re.search(r'viewBox="([^"]+)"', svg_text)
        vbox = vbox_m.group(1) if vbox_m else "0 0 24 24"

        paths = _extract_path_from_svg(svg_text)
        if not paths:
            print(f"  [IconFetcher] ✗ '{name}' — SVG parse failed")
            results[name] = False
            continue

        # Determine color
        hex_color = "#" + SIMPLEICONS_COLORS.get(slug, "")
        if hex_color == "#":
            # Try to extract from SVG
            color_m = re.search(r'fill="#([0-9A-Fa-f]{6})"', svg_text)
            hex_color = "#" + color_m.group(1) if color_m else "#555555"

        # Register and cache
        register(name_lower, paths, hex_color, vbox)
        cache[name_lower] = {"slug": slug, "paths": paths, "viewbox": vbox}
        results[name] = True
        updated = True
        print(f"  [IconFetcher] ✓ '{name}' registered ({len(paths)} chars)")

    if updated:
        _save_cache(cache)

    return results


def detect_unknown_brands(entities: list[str]) -> list[str]:
    """
    Given a list of entity names from the analyzer, return those that
    are likely brand icons not yet in our library.

    Used by the planner to decide which icons to pre-fetch.
    """
    from utils.icons import BRAND_ICONS, ICON_ALIASES

    known = set(BRAND_ICONS.keys()) | set(ICON_ALIASES.keys())
    unknown = []

    for entity in entities:
        clean = entity.lower().strip()
        # Skip generic words
        if len(clean) <= 2 or clean in {"the", "and", "for", "with", "api"}:
            continue
        if clean not in known:
            unknown.append(clean)

    return unknown