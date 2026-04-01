# utils/llm.py
#
# Unified LLM gateway — supports both OpenRouter and Gemini direct.
# The rest of the pipeline imports call() and call_json() from here.
# Switch providers by changing PROVIDER in config.py.
#
# OpenRouter API is OpenAI-compatible:
#   POST https://openrouter.ai/api/v1/chat/completions
#   Authorization: Bearer <key>
#   Body: { model, messages, response_format, temperature, max_tokens }
#
# The "key" argument maps to a model:
#   key="summarizer" → config.MODEL_SUMMARIZER
#   key="html"       → config.MODEL_HTML_AGENT
#   key="critic"     → config.MODEL_CRITIC
#   key="key1"       → config.MODEL_SUMMARIZER  (backwards-compat)
#   key="key2"       → config.MODEL_CRITIC       (backwards-compat)
#   key="key3"       → config.MODEL_HTML_AGENT   (backwards-compat)

import json, re, time, urllib.request, urllib.error, sys
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


# ── JSON repair (same as before, works for any provider) ─────────

def _repair(text: str) -> str:
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text).strip()
    stack, in_str, esc = [], False, False
    for ch in text:
        if esc:        esc = False; continue
        if ch == '\\' and in_str: esc = True; continue
        if ch == '"':  in_str = not in_str; continue
        if in_str:     continue
        if ch in '{[': stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{': stack.pop()
        elif ch == ']' and stack and stack[-1] == '[': stack.pop()
    if in_str: text += '"'
    text = text.rstrip().rstrip(',')
    for b in reversed(stack):
        text += '}' if b == '{' else ']'
    return text


def _parse(text: str) -> Optional[dict]:
    for t in [text, _repair(text)]:
        try: return json.loads(t)
        except: pass
    s = text.find('{')
    if s >= 0:
        try: return json.loads(_repair(text[s:]))
        except: pass
    return None


# ── Key → model resolution ────────────────────────────────────────

def _resolve_model(key: str) -> str:
    """Map a key string to the configured model name."""
    mapping = {
        # New 4-agent keys
        "planner":   getattr(config, "MODEL_PLANNER",   getattr(config, "MODEL_SUMMARIZER",  "google/gemini-2.5-flash")),
        "designer":  getattr(config, "MODEL_DESIGNER",  getattr(config, "MODEL_HTML_AGENT",  "google/gemini-2.5-flash")),
        "assembler": getattr(config, "MODEL_ASSEMBLER", getattr(config, "MODEL_HTML_AGENT",  "google/gemini-2.5-flash")),
        "critic":    getattr(config, "MODEL_CRITIC",    "google/gemini-2.5-flash"),
        # Old 3-agent keys (backwards-compat)
        "summarizer": getattr(config, "MODEL_SUMMARIZER", getattr(config, "MODEL_PLANNER",  "google/gemini-2.5-flash")),
        "html":       getattr(config, "MODEL_HTML_AGENT", getattr(config, "MODEL_DESIGNER", "google/gemini-2.5-flash")),
        "key1":       getattr(config, "MODEL_PLANNER",   "google/gemini-2.5-flash"),
        "key2":       getattr(config, "MODEL_CRITIC",    "google/gemini-2.5-flash"),
        "key3":       getattr(config, "MODEL_DESIGNER",  "google/gemini-2.5-flash"),
    }
    return mapping.get(key, getattr(config, "MODEL_SUMMARIZER", "google/gemini-2.5-flash"))


# ── OpenRouter call ───────────────────────────────────────────────

def _call_openrouter(prompt: str, model: str,
                     max_tokens: int = 8000, retries: int = 3) -> str:
    api_key = config.OPENROUTER_API_KEY
    if not api_key or "YOUR_" in api_key:
        raise RuntimeError(
            "\n❌  OpenRouter API key not set!\n"
            "   Open config.py and set OPENROUTER_API_KEY.\n"
            "   Get a key at: https://openrouter.ai/keys\n"
        )

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
        # Shown in your OpenRouter dashboard
        "HTTP-Referer":  getattr(config, "OPENROUTER_SITE_URL",  ""),
        "X-Title":       getattr(config, "OPENROUTER_SITE_NAME", "PDF Generator"),
    }
    payload = {
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens":  max_tokens,
        # Ask for JSON output when the model supports it
        # (works for OpenAI, Gemini via OpenRouter, Claude via OpenRouter)
        "response_format": {"type": "json_object"},
    }

    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data, headers)
    last = None

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                result = json.loads(r.read())

            # OpenAI-compatible response shape
            choice  = result["choices"][0]
            content = choice["message"]["content"]

            # Warn on truncation
            if choice.get("finish_reason") == "length":
                print(f"  [warn] response truncated at max_tokens={max_tokens}")

            return content

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")

            if e.code == 429:
                # Rate limited — exponential backoff
                wait = 12 * (2 ** attempt)
                print(f"  [rate limit] waiting {wait}s... (model: {model})")
                time.sleep(wait)
                last = e

            elif e.code == 402:
                raise RuntimeError(
                    f"OpenRouter 402: insufficient credits.\n"
                    f"Top up at https://openrouter.ai/credits\n{body[:200]}"
                )

            elif e.code == 400:
                # Some models don't support response_format=json_object
                # Retry without it
                if '"response_format"' in body or "response_format" in body:
                    print(f"  [info] model {model} doesn't support response_format — retrying without")
                    payload.pop("response_format", None)
                    data = json.dumps(payload).encode()
                    req  = urllib.request.Request(url, data, headers)
                    last = e
                else:
                    raise RuntimeError(f"OpenRouter 400: {body[:300]}")

            else:
                raise RuntimeError(f"OpenRouter HTTP {e.code}: {body[:300]}")

        except RuntimeError:
            raise
        except Exception as e:
            last = e
            if attempt < retries - 1:
                print(f"  [retry {attempt+1}] {e}")
                time.sleep(8)

    raise RuntimeError(f"Failed after {retries} tries: {last}")


# ── Gemini direct call (original, unchanged) ──────────────────────

def _call_gemini(prompt: str, key: str,
                 max_tokens: int = 8000, retries: int = 3) -> str:
    api_key = config.GEMINI_KEY_1 if key in ("key1", "summarizer", "html") else config.GEMINI_KEY_2
    if not api_key or "YOUR_" in api_key:
        raise RuntimeError(
            "\n❌  Gemini API key not set!\n"
            "   Open config.py and fill in GEMINI_KEY_1 / GEMINI_KEY_2.\n"
            "   Get free keys at: https://aistudio.google.com\n"
        )
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent?key={api_key}")
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    req  = urllib.request.Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                result = json.loads(r.read())
            cand = result["candidates"][0]
            if cand.get("finishReason") == "MAX_TOKENS":
                print(f"  [warn] MAX_TOKENS on attempt {attempt+1}")
            return cand["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                wait = 12 * (2 ** attempt)
                print(f"  [rate limit] waiting {wait}s...")
                time.sleep(wait); last = e
            else:
                raise RuntimeError(f"HTTP {e.code}: {body[:200]}")
        except RuntimeError: raise
        except Exception as e:
            last = e
            if attempt < retries - 1:
                print(f"  [retry {attempt+1}] {e}")
                time.sleep(10)
    raise RuntimeError(f"Failed after {retries} tries: {last}")


# ── Public API ────────────────────────────────────────────────────

def call(prompt: str, key: str = "key1",
         max_tokens: int = 8000, retries: int = 3) -> str:
    """
    Make a single LLM call. Returns raw text.

    key: "summarizer" | "html" | "critic"   (semantic names)
         "key1" | "key2" | "key3"           (backwards-compat)
    """
    provider = getattr(config, "PROVIDER", "gemini")

    if provider == "openrouter":
        model = _resolve_model(key)
        return _call_openrouter(prompt, model, max_tokens, retries)
    else:
        return _call_gemini(prompt, key, max_tokens, retries)


def call_json(prompt: str, key: str = "key1",
              max_tokens: int = 8000, retries: int = 3) -> dict:
    """
    Make an LLM call and parse the response as JSON.
    Retries with a stricter prompt if parsing fails.
    """
    last = ""
    for attempt in range(retries):
        try:
            last = call(prompt, key=key, max_tokens=max_tokens)
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(8); continue
            raise

        result = _parse(last)
        if result is not None:
            return result

        print(f"  [json attempt {attempt+1}] parse failed, retrying...")
        prompt = (
            "CRITICAL: Output ONLY valid JSON. No markdown fences. "
            "Keep ALL strings under 120 chars. Keep ALL arrays to max 5 items.\n\n"
            + prompt
        )
        time.sleep(4)

    raise ValueError(f"Could not parse JSON after {retries} attempts:\n{last[:300]}")