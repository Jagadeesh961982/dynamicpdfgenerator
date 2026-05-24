# utils/llm.py — Gemma 4 integration note:
# To use Gemma 4 locally (recommended for the DEV.to challenge):
#   1. Install Ollama: https://ollama.ai
#   2. Pull Gemma 4: ollama pull gemma4:27b
#   3. Set PROVIDER=ollama in .env (already the default)
# To use Gemma 4 free via OpenRouter (no GPU needed):
#   Set PROVIDER=openrouter, OPENROUTER_API_KEY=..., MODEL_ALL=google/gemma-4-31b-it:free

# # utils/llm.py
# #
# # Unified LLM gateway — OpenRouter + Gemini direct.
# # All agents import call() and call_json() from here.
# #
# # PROVIDER is set in config.py.
# # Key → model resolution maps semantic names to configured models.

# import json, re, time, urllib.request, urllib.error, sys
# from pathlib import Path
# from typing import Optional
# sys.path.insert(0, str(Path(__file__).parent.parent))
# import config


# # ══════════════════════════════════════════════════════════════════
# #  JSON REPAIR
# # ══════════════════════════════════════════════════════════════════

# def _repair_json(text: str) -> str:
#     """Close unclosed brackets/braces and strip code fences."""
#     text = re.sub(r'^```(?:json)?\s*', '', text.strip())
#     text = re.sub(r'\s*```$', '', text).strip()

#     stack, in_str, esc = [], False, False
#     for ch in text:
#         if esc:
#             esc = False
#             continue
#         if ch == '\\' and in_str:
#             esc = True
#             continue
#         if ch == '"':
#             in_str = not in_str
#             continue
#         if in_str:
#             continue
#         if ch in '{[':
#             stack.append(ch)
#         elif ch == '}' and stack and stack[-1] == '{':
#             stack.pop()
#         elif ch == ']' and stack and stack[-1] == '[':
#             stack.pop()

#     if in_str:
#         text += '"'
#     text = text.rstrip().rstrip(',')
#     for b in reversed(stack):
#         text += '}' if b == '{' else ']'
#     return text


# def _parse_json(text: str) -> Optional[dict]:
#     """Try multiple strategies to parse JSON from LLM output."""
#     for candidate in [text, _repair_json(text)]:
#         try:
#             return json.loads(candidate)
#         except Exception:
#             pass

#     # Try finding the first { ... } block
#     start = text.find('{')
#     if start >= 0:
#         try:
#             return json.loads(_repair_json(text[start:]))
#         except Exception:
#             pass

#     return None


# # ══════════════════════════════════════════════════════════════════
# #  MODEL RESOLUTION
# # ══════════════════════════════════════════════════════════════════

# def _resolve_model(key: str) -> str:
#     mapping = {
#         "analyzer":  getattr(config, "MODEL_ANALYZER",  "google/gemini-2.5-flash"),
#         "planner":   getattr(config, "MODEL_PLANNER",   "google/gemini-2.5-flash"),
#         "designer":  getattr(config, "MODEL_DESIGNER",  "google/gemini-2.5-flash"),
#         "assembler": getattr(config, "MODEL_ASSEMBLER", "google/gemini-2.5-flash"),
#         "critic":    getattr(config, "MODEL_CRITIC",    "google/gemini-2.5-flash"),
#     }
#     return mapping.get(key, "google/gemini-2.5-flash")


# # ══════════════════════════════════════════════════════════════════
# #  NVIDIA NIM (INTEGRATE API) — urllib version
# # ══════════════════════════════════════════════════════════════════

# def _call_nvidia(prompt: str, model: str,
#                  max_tokens: int = 8000,
#                  retries: int = 3,
#                  json_mode: bool = False) -> str:
#     api_key = getattr(config, "NVIDIA_API_KEY", None)
#     if not api_key or "YOUR_" in api_key:
#         raise RuntimeError(
#             "\n❌  NVIDIA API key not configured!\n"
#             "   Set NVIDIA_API_KEY in config.py\n"
#             "   Get key from: https://build.nvidia.com/\n"
#         )

#     url = "https://integrate.api.nvidia.com/v1/chat/completions"

#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {api_key}",
#         "Accept": "application/json"
#     }

#     payload = {
#         "model": model,
#         "messages": [{"role": "user", "content": prompt}],
#         "temperature": 0.3,
#         "max_tokens": max_tokens,
#         "top_p": 1.0,
#         "stream": False
#     }

#     if json_mode:
#         payload["response_format"] = {"type": "json_object"}

#     last_error = None

#     for attempt in range(retries):
#         try:
#             data = json.dumps(payload).encode()
#             req = urllib.request.Request(url, data, headers)

#             with urllib.request.urlopen(req, timeout=180) as r:
#                 result = json.loads(r.read())

#             choice = result["choices"][0]
#             content = choice["message"]["content"]

#             if choice.get("finish_reason") == "length":
#                 print(f"  ⚠ Response truncated at max_tokens={max_tokens}")

#             return content

#         except urllib.error.HTTPError as e:
#             body = e.read().decode("utf-8", errors="replace")

#             if e.code == 429:
#                 wait = 15 * (2 ** attempt)
#                 print(f"  Rate limited — waiting {wait}s (NVIDIA)")
#                 time.sleep(wait)
#                 last_error = e

#             elif e.code == 401:
#                 raise RuntimeError(f"NVIDIA 401 Unauthorized:\n{body[:200]}")

#             elif e.code == 400:
#                 if json_mode and "response_format" in body:
#                     print("  NVIDIA model doesn't support response_format — retrying without")
#                     payload.pop("response_format", None)
#                     last_error = e
#                 else:
#                     raise RuntimeError(f"NVIDIA 400: {body[:300]}")

#             else:
#                 raise RuntimeError(f"NVIDIA HTTP {e.code}: {body[:300]}")

#         except RuntimeError:
#             raise

#         except Exception as e:
#             last_error = e
#             if attempt < retries - 1:
#                 print(f"  Retry {attempt + 1}: {e}")
#                 time.sleep(10)

#     raise RuntimeError(f"NVIDIA failed after {retries} attempts: {last_error}")


# # ══════════════════════════════════════════════════════════════════
# #  OPENROUTER
# # ══════════════════════════════════════════════════════════════════

# def _call_openrouter(prompt: str, model: str,
#                      max_tokens: int = 8000,
#                      retries: int = 3,
#                      json_mode: bool = False) -> str:
#     api_key = config.OPENROUTER_API_KEY
#     if not api_key or "YOUR_" in api_key:
#         raise RuntimeError(
#             "\n❌  OpenRouter API key not configured!\n"
#             "   Set OPENROUTER_API_KEY in config.py\n"
#             "   Get a key at: https://openrouter.ai/keys\n"
#         )

#     url = "https://openrouter.ai/api/v1/chat/completions"
#     headers = {
#         "Content-Type":  "application/json",
#         "Authorization": f"Bearer {api_key}",
#         "HTTP-Referer":  getattr(config, "OPENROUTER_SITE_URL", ""),
#         "X-Title":       getattr(config, "OPENROUTER_SITE_NAME", "PDF Generator"),
#     }
#     payload = {
#         "model":       model,
#         "messages":    [{"role": "user", "content": prompt}],
#         "temperature": 0.3,
#         "max_tokens":  max_tokens,
#     }
#     # json_mode ONLY for call_json — designer needs raw HTML, not forced JSON
#     if json_mode:
#         payload["response_format"] = {"type": "json_object"}

#     last_error = None
#     for attempt in range(retries):
#         try:
#             data = json.dumps(payload).encode()
#             req  = urllib.request.Request(url, data, headers)
#             with urllib.request.urlopen(req, timeout=180) as r:
#                 result = json.loads(r.read())
#             choice  = result["choices"][0]
#             content = choice["message"]["content"]
#             if choice.get("finish_reason") == "length":
#                 print(f"  ⚠ Response truncated at max_tokens={max_tokens}")
#             return content

#         except urllib.error.HTTPError as e:
#             body = e.read().decode("utf-8", errors="replace")
#             if e.code == 429:
#                 wait = 15 * (2 ** attempt)
#                 print(f"  Rate limited — waiting {wait}s (model: {model})")
#                 time.sleep(wait)
#                 last_error = e
#             elif e.code == 402:
#                 raise RuntimeError(f"OpenRouter 402: insufficient credits.\n{body[:200]}")
#             elif e.code == 400:
#                 if json_mode and "response_format" in body:
#                     print(f"  Model {model} doesn't support response_format — retrying without")
#                     payload.pop("response_format", None)
#                     last_error = e
#                 else:
#                     raise RuntimeError(f"OpenRouter 400: {body[:300]}")
#             else:
#                 raise RuntimeError(f"OpenRouter HTTP {e.code}: {body[:300]}")

#         except RuntimeError:
#             raise
#         except Exception as e:
#             last_error = e
#             if attempt < retries - 1:
#                 print(f"  Retry {attempt + 1}: {e}")
#                 time.sleep(10)

#     raise RuntimeError(f"Failed after {retries} attempts: {last_error}")


# # ══════════════════════════════════════════════════════════════════
# #  GEMINI DIRECT
# # ══════════════════════════════════════════════════════════════════

# def _call_gemini(prompt: str, key: str,
#                  max_tokens: int = 8000,
#                  retries: int = 3,
#                  json_mode: bool = False) -> str:
#     api_key = (config.GEMINI_KEY_1
#                if key in ("key1", "analyzer", "planner", "designer")
#                else config.GEMINI_KEY_2)
#     if not api_key or "YOUR_" in api_key:
#         raise RuntimeError(
#             "\n❌  Gemini API key not set!\n"
#             "   Fill GEMINI_KEY_1 / GEMINI_KEY_2 in config.py\n"
#             "   Get free keys at: https://aistudio.google.com\n"
#         )

#     url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
#            f"{config.GEMINI_MODEL}:generateContent?key={api_key}")
#     gen_cfg = {"temperature": 0.3, "maxOutputTokens": max_tokens}
#     if json_mode:
#         gen_cfg["responseMimeType"] = "application/json"

#     payload = {
#         "contents": [{"parts": [{"text": prompt}]}],
#         "generationConfig": gen_cfg,
#     }

#     last_error = None
#     for attempt in range(retries):
#         try:
#             req = urllib.request.Request(
#                 url,
#                 json.dumps(payload).encode(),
#                 {"Content-Type": "application/json"},
#             )
#             with urllib.request.urlopen(req, timeout=180) as r:
#                 result = json.loads(r.read())
#             cand = result["candidates"][0]
#             if cand.get("finishReason") == "MAX_TOKENS":
#                 print(f"  ⚠ MAX_TOKENS on attempt {attempt + 1}")
#             return cand["content"]["parts"][0]["text"]

#         except urllib.error.HTTPError as e:
#             body = e.read().decode("utf-8", errors="replace")
#             if e.code == 429:
#                 wait = 15 * (2 ** attempt)
#                 print(f"  Rate limited — waiting {wait}s")
#                 time.sleep(wait)
#                 last_error = e
#             else:
#                 raise RuntimeError(f"Gemini HTTP {e.code}: {body[:200]}")
#         except RuntimeError:
#             raise
#         except Exception as e:
#             last_error = e
#             if attempt < retries - 1:
#                 print(f"  Retry {attempt + 1}: {e}")
#                 time.sleep(10)

#     raise RuntimeError(f"Failed after {retries} attempts: {last_error}")


# # ══════════════════════════════════════════════════════════════════
# #  PUBLIC API
# # ══════════════════════════════════════════════════════════════════

# def call(prompt: str,
#          key: str = "planner",
#          max_tokens: int = 8000,
#          retries: int = 3,
#          json_mode: bool = False) -> str:
#     """
#     Single LLM call. Returns raw text.
#     Set json_mode=True ONLY for structured JSON agents (planner, critic, analyzer).
#     NEVER for designer — it needs raw HTML output.
#     """
#     provider = getattr(config, "PROVIDER", "openrouter")
#     if provider == "openrouter":
#         model = _resolve_model(key)
#         return _call_openrouter(prompt, model, max_tokens, retries, json_mode)
#     elif provider == "nvidia":
#         model = _resolve_model(key)
#         return _call_nvidia(prompt, model, max_tokens, retries, json_mode)
#     else:
#         return _call_gemini(prompt, key, max_tokens, retries, json_mode)


# def call_json(prompt: str,
#               key: str = "planner",
#               max_tokens: int = 8000,
#               retries: int = 3) -> dict:
#     """
#     LLM call that parses and returns JSON.
#     Retries with stricter instructions on parse failures.
#     """
#     for attempt in range(retries):
#         try:
#             raw = call(prompt, key=key, max_tokens=max_tokens,
#                        retries=retries, json_mode=True)
#         except RuntimeError:
#             raise
#         except Exception as e:
#             if attempt < retries - 1:
#                 time.sleep(8)
#                 continue
#             raise

#         result = _parse_json(raw)
#         if result is not None:
#             return result

#         print(f"  [json attempt {attempt + 1}] Parse failed — retrying with stricter prompt")
#         prompt = (
#             "CRITICAL: Return ONLY valid JSON. No markdown fences. "
#             "No preamble. No explanation. JSON must start with { and end with }.\n\n"
#             + prompt
#         )
#         time.sleep(4)

#     raise ValueError(f"Could not parse JSON after {retries} attempts")




# utils/llm.py
#
# Unified LLM gateway — OpenRouter + Gemini direct.
# All agents import call() and call_json() from here.
#
# PROVIDER is set in config.py.
# Key → model resolution maps semantic names to configured models.

import json, os, re, time, urllib.request, urllib.error, sys
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


# ══════════════════════════════════════════════════════════════════
#  JSON REPAIR
# ══════════════════════════════════════════════════════════════════

def _repair_json(text: str) -> str:
    """Close unclosed brackets/braces and strip code fences."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text).strip()

    stack, in_str, esc = [], False, False
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()

    if in_str:
        text += '"'
    text = text.rstrip().rstrip(',')
    for b in reversed(stack):
        text += '}' if b == '{' else ']'
    return text


def _parse_json(text: str) -> Optional[dict]:
    """Try multiple strategies to parse JSON from LLM output."""
    # Strip ALL markdown fences anywhere in text (Gemma wraps output in prose)
    stripped = re.sub(r'```(?:json)?\s*', '', text)
    stripped = re.sub(r'```', '', stripped).strip()

    for candidate in [text, stripped, _repair_json(text), _repair_json(stripped)]:
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # Walk forward to find the first { ... } block
    for src in (stripped, text):
        start = src.find('{')
        if start >= 0:
            try:
                return json.loads(_repair_json(src[start:]))
            except Exception:
                pass

    # Last resort: find the last [ too (some models return JSON arrays)
    for src in (stripped, text):
        for opener, closer in (('{', '}'), ('[', ']')):
            start = src.find(opener)
            end   = src.rfind(closer)
            if start >= 0 and end > start:
                try:
                    return json.loads(_repair_json(src[start:end + 1]))
                except Exception:
                    pass

    return None


# ══════════════════════════════════════════════════════════════════
#  MODEL RESOLUTION
# ══════════════════════════════════════════════════════════════════

def _resolve_model(key: str) -> str:
    provider = getattr(config, "PROVIDER", "openrouter")
    if provider == "ollama":
        default = getattr(config, "OLLAMA_MODEL", "gemma4:27b")
    else:
        default = "google/gemma-4-27b-it"
    mapping = {
        "analyzer":  getattr(config, "MODEL_ANALYZER",  default),
        "planner":   getattr(config, "MODEL_PLANNER",   default),
        "designer":  getattr(config, "MODEL_DESIGNER",  default),
        "assembler": getattr(config, "MODEL_ASSEMBLER", default),
        "critic":    getattr(config, "MODEL_CRITIC",    default),
    }
    return mapping.get(key, default)


# ══════════════════════════════════════════════════════════════════
#  OPENROUTER
# ══════════════════════════════════════════════════════════════════

def _openrouter_key_list() -> list[str]:
    """Ordered unique keys: primary + OPENROUTER_API_KEYS + env OPENROUTER_API_KEYS."""
    seen: set[str] = set()
    out: list[str] = []

    primary = getattr(config, "OPENROUTER_API_KEY", "") or ""
    primary = primary.strip()
    if primary and "YOUR_" not in primary:
        seen.add(primary)
        out.append(primary)

    extras = getattr(config, "OPENROUTER_API_KEYS", None)
    if extras is None:
        extras = []
    elif isinstance(extras, str):
        extras = [extras]
    for k in extras:
        k = (k or "").strip()
        if not k or "YOUR_" in k or k in seen:
            continue
        seen.add(k)
        out.append(k)

    env_keys = (os.environ.get("OPENROUTER_API_KEYS") or "").strip()
    if env_keys:
        for part in env_keys.split(","):
            k = part.strip()
            if not k or "YOUR_" in k or k in seen:
                continue
            seen.add(k)
            out.append(k)

    if not out:
        raise RuntimeError(
            "\n❌  OpenRouter API key not configured!\n"
            "   Set OPENROUTER_API_KEY (and optional OPENROUTER_API_KEYS) in config.py\n"
            "   Or set env OPENROUTER_API_KEYS to comma-separated keys.\n"
            "   Get a key at: https://openrouter.ai/keys\n"
        )
    return out


def _call_openrouter(prompt: str, model: str,
                     max_tokens: int = 8000,
                     retries: int = 3,
                     json_mode: bool = False) -> str:
    keys = _openrouter_key_list()
    url = "https://openrouter.ai/api/v1/chat/completions"
    base_headers = {
        "Content-Type":  "application/json",
        "HTTP-Referer":  getattr(config, "OPENROUTER_SITE_URL", ""),
        "X-Title":       getattr(config, "OPENROUTER_SITE_NAME", "PDF Generator"),
    }
    payload = {
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens":  max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    failures: list[str] = []

    for key_idx, api_key in enumerate(keys):
        headers = {
            **base_headers,
            "Authorization": f"Bearer {api_key}",
        }
        last_error: Optional[Exception] = None
        switch_key = False

        for attempt in range(retries):
            try:
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data, headers)
                with urllib.request.urlopen(req, timeout=180) as r:
                    result = json.loads(r.read())
                choice = result["choices"][0]
                content = choice["message"]["content"]
                if choice.get("finish_reason") == "length":
                    print(f"  ⚠ Response truncated at max_tokens={max_tokens}")
                return content

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code == 429:
                    wait = 15 * (2 ** attempt)
                    print(
                        f"  Rate limited — waiting {wait}s "
                        f"(model: {model}, key {key_idx + 1}/{len(keys)})"
                    )
                    time.sleep(wait)
                    last_error = e
                    if attempt == retries - 1:
                        failures.append(
                            f"key {key_idx + 1}/{len(keys)}: HTTP 429 after {retries} attempts"
                        )
                        switch_key = True
                    continue
                if e.code in (401, 402, 403):
                    print(
                        f"  OpenRouter HTTP {e.code} — switching key "
                        f"({key_idx + 1}/{len(keys)} → next if available)"
                    )
                    failures.append(
                        f"key {key_idx + 1}/{len(keys)}: HTTP {e.code} {body[:120]}"
                    )
                    switch_key = True
                    break
                if e.code == 400:
                    if json_mode and "response_format" in body:
                        print(f"  Model {model} doesn't support response_format — retrying without")
                        payload.pop("response_format", None)
                        last_error = e
                        continue
                    raise RuntimeError(f"OpenRouter 400: {body[:300]}")
                raise RuntimeError(f"OpenRouter HTTP {e.code}: {body[:300]}")

            except RuntimeError:
                raise
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    print(f"  Retry {attempt + 1}: {e}")
                    time.sleep(10)
                else:
                    failures.append(f"key {key_idx + 1}/{len(keys)}: {e!r}")
                    switch_key = True
                    break

        if switch_key:
            continue

        if last_error is not None:
            failures.append(f"key {key_idx + 1}/{len(keys)}: exhausted retries ({last_error!r})")

    detail = "\n".join(failures) if failures else "(no detail)"
    raise RuntimeError(
        f"All {len(keys)} OpenRouter key(s) failed. Last errors:\n{detail}"
    )


# ══════════════════════════════════════════════════════════════════
#  NVIDIA NIM
# ══════════════════════════════════════════════════════════════════

def _call_nvidia(prompt: str, model: str,
                 max_tokens: int = 8000,
                 retries: int = 3,
                 json_mode: bool = False) -> str:
    api_key = getattr(config, "NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "\n❌  NVIDIA API key not configured!\n"
            "   Set NVIDIA_API_KEY in .env or environment.\n"
            "   Get key from: https://build.nvidia.com/\n"
        )

    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(retries):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data, headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                result = json.loads(r.read())
            choice = result["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                print(f"  ⚠ Response truncated at max_tokens={max_tokens}")
            return content
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                wait = 15 * (2 ** attempt)
                print(f"  Rate limited — waiting {wait}s (NVIDIA)")
                time.sleep(wait)
                last_error = e
            elif e.code == 401:
                raise RuntimeError(f"NVIDIA 401 Unauthorized. Check NVIDIA_API_KEY.")
            elif e.code == 400:
                if json_mode and "response_format" in body:
                    print("  NVIDIA model doesn't support response_format — retrying without")
                    payload.pop("response_format", None)
                    last_error = e
                else:
                    raise RuntimeError(f"NVIDIA 400: {body[:300]}")
            else:
                raise RuntimeError(f"NVIDIA HTTP {e.code}: {body[:300]}")
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                print(f"  Retry {attempt + 1}: {e}")
                time.sleep(10)

    raise RuntimeError(f"NVIDIA failed after {retries} attempts: {last_error}")


# ══════════════════════════════════════════════════════════════════
#  OLLAMA — local Gemma 4 (primary provider)
# ══════════════════════════════════════════════════════════════════

def _call_ollama(prompt: str, model: str,
                 max_tokens: int = 8000,
                 retries: int = 3,
                 json_mode: bool = False) -> str:
    base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    payload: dict = {
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens":  max_tokens,
        "stream":      False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(retries):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                result = json.loads(r.read())
            choice = result["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                print(f"  ⚠ Ollama response truncated at max_tokens={max_tokens}")
            return content

        except urllib.error.URLError as e:
            msg = str(e).lower()
            if "connection refused" in msg or "refused" in msg or "connect" in msg:
                raise RuntimeError(
                    "\n❌  Ollama is not running!\n"
                    "   Start Ollama: ollama serve\n"
                    f"   Pull Gemma 4:  ollama pull {model}\n"
                    "   Or use cloud:  set PROVIDER=openrouter, MODEL_ALL=google/gemma-4-31b-it:free\n"
                ) from e
            last_error = e
            if attempt < retries - 1:
                print(f"  Ollama retry {attempt + 1}: {e}")
                time.sleep(5)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                raise RuntimeError(
                    f"\n❌  Ollama model '{model}' not found!\n"
                    f"   Pull it with: ollama pull {model}\n"
                    f"   List models:  ollama list\n"
                ) from e
            raise RuntimeError(f"Ollama HTTP {e.code}: {body[:300]}") from e

        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                print(f"  Ollama retry {attempt + 1}: {e}")
                time.sleep(5)

    raise RuntimeError(f"Ollama failed after {retries} attempts: {last_error}")


def _call_ollama_messages(messages: list[dict], model: str,
                          max_tokens: int = 4000, retries: int = 3) -> str:
    """Multi-turn conversation via Ollama's OpenAI-compat endpoint."""
    base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": 0.7,
        "max_tokens":  max_tokens,
        "stream":      False,
    }
    last_error = None
    for attempt in range(retries):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                result = json.loads(r.read())
            return result["choices"][0]["message"]["content"]
        except urllib.error.URLError as e:
            msg = str(e).lower()
            if "connection refused" in msg or "refused" in msg:
                raise RuntimeError(
                    "\n❌  Ollama is not running! Start with: ollama serve\n"
                ) from e
            last_error = e
            if attempt < retries - 1:
                time.sleep(5)
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(5)
    raise RuntimeError(f"Ollama chat failed after {retries} attempts: {last_error}")


# ══════════════════════════════════════════════════════════════════
#  GEMINI DIRECT — round-robin key rotation
# ══════════════════════════════════════════════════════════════════

def _gemini_key_list() -> list[str]:
    """Return all configured Gemini keys in order, skipping empty/placeholder values."""
    keys: list[str] = []
    for attr in ("GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3"):
        k = (getattr(config, attr, "") or "").strip()
        if k and "YOUR_" not in k:
            keys.append(k)
    if not keys:
        raise RuntimeError(
            "\n❌  Gemini API key not set!\n"
            "   Fill GEMINI_KEY_1 / GEMINI_KEY_2 / GEMINI_KEY_3 in .env\n"
            "   Get free keys at: https://aistudio.google.com\n"
        )
    return keys


def _call_gemini(prompt: str, key: str,
                 max_tokens: int = 8000,
                 retries: int = 3,
                 json_mode: bool = False) -> str:
    keys = _gemini_key_list()
    model = getattr(config, "GEMINI_MODEL", "gemma-4-31b-it")
    gen_cfg: dict = {"temperature": 0.3, "maxOutputTokens": max_tokens}
    # responseMimeType is only reliable for gemini-* models; gemma-* models ignore it
    # and return verbose text — we rely on _parse_json() to extract JSON instead
    if json_mode and not model.startswith("gemma"):
        gen_cfg["responseMimeType"] = "application/json"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }

    failures: list[str] = []

    for key_idx, api_key in enumerate(keys):
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        last_error: Optional[Exception] = None
        switch_key = False

        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=180) as r:
                    result = json.loads(r.read())
                cand = result["candidates"][0]
                if cand.get("finishReason") == "MAX_TOKENS":
                    print(f"  ⚠ MAX_TOKENS on attempt {attempt + 1}")
                return cand["content"]["parts"][0]["text"]

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code == 429:
                    print(
                        f"  Gemini rate limited "
                        f"(key {key_idx + 1}/{len(keys)}) — switching to next key"
                    )
                    failures.append(f"key {key_idx + 1}/{len(keys)}: HTTP 429 rate limit")
                    switch_key = True
                    break
                elif e.code in (400, 401, 403):
                    failures.append(f"key {key_idx + 1}/{len(keys)}: HTTP {e.code} {body[:120]}")
                    switch_key = True
                    break
                else:
                    raise RuntimeError(f"Gemini HTTP {e.code}: {body[:200]}")
            except RuntimeError:
                raise
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    print(f"  Gemini retry {attempt + 1}: {e}")
                    time.sleep(10)
                else:
                    failures.append(f"key {key_idx + 1}/{len(keys)}: {e!r}")
                    switch_key = True
                    break

        if switch_key:
            continue
        if last_error is not None:
            failures.append(f"key {key_idx + 1}/{len(keys)}: exhausted retries ({last_error!r})")

    detail = "\n".join(failures) if failures else "(no detail)"
    raise RuntimeError(f"All {len(keys)} Gemini key(s) exhausted:\n{detail}")


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def call(prompt: str,
         key: str = "planner",
         max_tokens: int = 8000,
         retries: int = 3,
         json_mode: bool = False) -> str:
    """
    Single LLM call. Returns raw text.
    Set json_mode=True ONLY for structured JSON agents (planner, critic, analyzer).
    NEVER for designer — it needs raw HTML output.
    Provider priority: ollama (local Gemma 4) → openrouter → nvidia → gemini.
    """
    provider = getattr(config, "PROVIDER", "ollama")
    model = _resolve_model(key)
    if provider == "ollama":
        return _call_ollama(prompt, model, max_tokens, retries, json_mode)
    elif provider == "openrouter":
        return _call_openrouter(prompt, model, max_tokens, retries, json_mode)
    elif provider == "nvidia":
        return _call_nvidia(prompt, model, max_tokens, retries, json_mode)
    else:
        return _call_gemini(prompt, key, max_tokens, retries, json_mode)


def call_json(prompt: str,
              key: str = "planner",
              max_tokens: int = 8000,
              retries: int = 3) -> dict:
    """
    LLM call that parses and returns JSON.
    Retries with stricter instructions on parse failures.
    """
    for attempt in range(retries):
        try:
            raw = call(prompt, key=key, max_tokens=max_tokens,
                       retries=retries, json_mode=True)
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(8)
                continue
            raise

        result = _parse_json(raw)
        if result is not None:
            return result

        print(f"  [json attempt {attempt + 1}] Parse failed — retrying with stricter prompt")
        prompt = (
            "CRITICAL: Return ONLY valid JSON. No markdown fences. "
            "No preamble. No explanation. JSON must start with { and end with }.\n\n"
            + prompt
        )
        time.sleep(4)

    raise ValueError(f"Could not parse JSON after {retries} attempts")


def call_vision(
    prompt: str,
    image_b64: str,
    image_mime: str = "image/jpeg",
    key: str = "analyzer",
    max_tokens: int = 4000,
) -> str:
    """
    Multimodal call: text prompt + base64-encoded image.
    Gemma 4's native multimodal capability — processes images, charts, diagrams.
    Supported by Ollama (local) and OpenRouter.
    """
    provider = getattr(config, "PROVIDER", "ollama")
    model = _resolve_model(key)
    data_url = f"data:{image_mime};base64,{image_b64}"
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }]
    payload_base = {
        "model":       model,
        "messages":    messages,
        "temperature": 0.3,
        "max_tokens":  max_tokens,
        "stream":      False,
    }

    if provider == "ollama":
        base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        url = f"{base_url}/v1/chat/completions"
        headers: dict = {"Content-Type": "application/json"}
    elif provider == "openrouter":
        keys = _openrouter_key_list()
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {keys[0]}",
            "HTTP-Referer":  getattr(config, "OPENROUTER_SITE_URL", ""),
            "X-Title":       getattr(config, "OPENROUTER_SITE_NAME", "PDF Generator"),
        }
    else:
        # Gemini / NVIDIA don't support vision in this gateway — fall back to text only
        print("  [Vision] Provider doesn't support vision — using text-only fallback")
        return call(prompt, key=key, max_tokens=max_tokens)

    try:
        data = json.dumps(payload_base).encode()
        req = urllib.request.Request(url, data, headers)
        with urllib.request.urlopen(req, timeout=300) as r:
            result = json.loads(r.read())
        return result["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(f"Vision call failed ({provider}): {e}") from e
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Vision call HTTP {e.code}: {body[:300]}") from e


def call_messages(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 4000,
    retries: int = 3,
) -> str:
    """
    Call LLM with OpenAI-style messages array for multi-turn conversations.
    Used by the chat endpoint. Supports ollama, openrouter, nvidia, and gemini providers.
    """
    provider = getattr(config, "PROVIDER", "ollama")
    if model is None:
        model = _resolve_model("planner")

    if provider == "ollama":
        return _call_ollama_messages(messages, model, max_tokens, retries)

    if provider in ("openrouter", "nvidia"):
        if provider == "nvidia":
            api_key = getattr(config, "NVIDIA_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("NVIDIA_API_KEY not configured. Set it in .env.")
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers: dict = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
        else:
            keys = _openrouter_key_list()
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {keys[0]}",
                "HTTP-Referer": getattr(config, "OPENROUTER_SITE_URL", ""),
                "X-Title": getattr(config, "OPENROUTER_SITE_NAME", "PDF Generator"),
            }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
        }
        last_error = None
        for attempt in range(retries):
            try:
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data, headers)
                with urllib.request.urlopen(req, timeout=120) as r:
                    result = json.loads(r.read())
                return result["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code == 429:
                    wait = 10 * (2 ** attempt)
                    print(f"  Chat rate limited — waiting {wait}s")
                    time.sleep(wait)
                    last_error = e
                else:
                    raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
            except RuntimeError:
                raise
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    time.sleep(5)
        raise RuntimeError(f"call_messages failed after {retries} attempts: {last_error}")

    else:
        # Gemini: flatten messages to a single prompt (multi-turn via text)
        flat = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in messages
        )
        return _call_gemini(flat, "planner", max_tokens, retries)