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
    for candidate in [text, _repair_json(text)]:
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # Try finding the first { ... } block
    start = text.find('{')
    if start >= 0:
        try:
            return json.loads(_repair_json(text[start:]))
        except Exception:
            pass

    return None


# ══════════════════════════════════════════════════════════════════
#  MODEL RESOLUTION
# ══════════════════════════════════════════════════════════════════

def _resolve_model(key: str) -> str:
    mapping = {
        "analyzer":  getattr(config, "MODEL_ANALYZER",  "google/gemini-2.5-flash"),
        "planner":   getattr(config, "MODEL_PLANNER",   "google/gemini-2.5-flash"),
        "designer":  getattr(config, "MODEL_DESIGNER",  "google/gemini-2.5-flash"),
        "assembler": getattr(config, "MODEL_ASSEMBLER", "google/gemini-2.5-flash"),
        "critic":    getattr(config, "MODEL_CRITIC",    "google/gemini-2.5-flash"),
    }
    return mapping.get(key, "google/gemini-2.5-flash")


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
#  GEMINI DIRECT
# ══════════════════════════════════════════════════════════════════

def _call_gemini(prompt: str, key: str,
                 max_tokens: int = 8000,
                 retries: int = 3,
                 json_mode: bool = False) -> str:
    api_key = (config.GEMINI_KEY_1
               if key in ("key1", "analyzer", "planner", "designer")
               else config.GEMINI_KEY_2)
    if not api_key or "YOUR_" in api_key:
        raise RuntimeError(
            "\n❌  Gemini API key not set!\n"
            "   Fill GEMINI_KEY_1 / GEMINI_KEY_2 in config.py\n"
            "   Get free keys at: https://aistudio.google.com\n"
        )

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent?key={api_key}")
    gen_cfg = {"temperature": 0.3, "maxOutputTokens": max_tokens}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }

    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
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
                wait = 15 * (2 ** attempt)
                print(f"  Rate limited — waiting {wait}s")
                time.sleep(wait)
                last_error = e
            else:
                raise RuntimeError(f"Gemini HTTP {e.code}: {body[:200]}")
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                print(f"  Retry {attempt + 1}: {e}")
                time.sleep(10)

    raise RuntimeError(f"Failed after {retries} attempts: {last_error}")


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
    """
    provider = getattr(config, "PROVIDER", "openrouter")
    model = _resolve_model(key)
    if provider == "openrouter":
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


def call_messages(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 4000,
    retries: int = 3,
) -> str:
    """
    Call LLM with OpenAI-style messages array for multi-turn conversations.
    Used by the chat endpoint. Supports openrouter, nvidia, and gemini providers.
    """
    provider = getattr(config, "PROVIDER", "openrouter")
    if model is None:
        model = _resolve_model("planner")

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