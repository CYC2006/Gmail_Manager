import json
import os
import re as _re
import threading
import time
from datetime import date

import httpx
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
_TPD_STATUS_PATH = os.path.join(ROOT_DIR, 'data', 'tpd_status.json')

PROVIDERS = {
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "min_interval": 2.5,  # Groq free tier: 30 RPM
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-8b-instruct",
        "min_interval": 2.0,   # ~30 RPM free tier
    },
    "kimi": {
        "label": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "min_interval": 1.0,
    },
}

MODEL = "llama-3.3-70b-versatile"  # kept for backward compat


def _load_tpd_status() -> set[str]:
    """Return set of key prefixes exhausted today; empty set if file missing or stale."""
    try:
        with open(_TPD_STATUS_PATH, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('date') == str(date.today()):
            return set(data.get('exhausted_keys', []))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return set()


def _save_tpd_status(exhausted_prefixes: set[str]):
    os.makedirs(os.path.dirname(_TPD_STATUS_PATH), exist_ok=True)
    with open(_TPD_STATUS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': str(date.today()), 'exhausted_keys': sorted(exhausted_prefixes)}, f)


def get_tpd_status() -> dict:
    today_exhausted = _load_tpd_status()
    return {
        'date': str(date.today()),
        'all_exhausted': TPD_EXHAUSTED,
        'exhausted_keys': sorted(today_exhausted),
    }


def _key_prefix(entry: dict) -> str:
    key = entry.get("key", "") if isinstance(entry, dict) else (entry or "")
    return key[:8] if key else ""


def _load_verified_keys() -> list[dict]:
    try:
        from src.config_manager import get_api_keys
        return get_api_keys()
    except Exception:
        return []


def _load_keys_with_dev_fallback() -> list[dict]:
    keys = _load_verified_keys()
    if keys:
        return keys
    dev_raw = [os.getenv("key1"), os.getenv("key2"), os.getenv("key3")]
    dev_keys = [{"key": k, "provider": "groq"} for k in dev_raw if k]
    if dev_keys:
        print("[KEY] Warning: using unverified .env keys. Add verified keys in Settings → API Keys.")
    return dev_keys


_AVAILABLE_KEYS: list[dict] = _load_keys_with_dev_fallback()
_exhausted_prefixes: set[str] = _load_tpd_status()
_exhausted_keys: list[int] = [
    i for i, k in enumerate(_AVAILABLE_KEYS) if _key_prefix(k) in _exhausted_prefixes
]
_current_key_idx = next(
    (i for i in range(len(_AVAILABLE_KEYS)) if i not in _exhausted_keys), 0
)
_key_lock = threading.Lock()


def reload_keys():
    global _AVAILABLE_KEYS, _current_key_idx, TPD_EXHAUSTED, _exhausted_keys, _exhausted_prefixes
    new_keys = _load_verified_keys()
    today_exhausted = _load_tpd_status()
    exhausted_idxs = [i for i, k in enumerate(new_keys) if _key_prefix(k) in today_exhausted]
    all_exhausted = bool(new_keys) and len(exhausted_idxs) == len(new_keys)
    first_ok = next((i for i in range(len(new_keys)) if i not in exhausted_idxs), 0)
    with _key_lock:
        _AVAILABLE_KEYS = new_keys
        _current_key_idx = first_ok
        TPD_EXHAUSTED = all_exhausted
        _exhausted_keys = exhausted_idxs
        _exhausted_prefixes = today_exhausted
    print(f"[KEY] Reloaded {len(new_keys)} verified API key(s). "
          f"Exhausted today: {len(exhausted_idxs)}/{len(new_keys)}")


def _try_switch_key() -> bool:
    global _current_key_idx, TPD_EXHAUSTED, _exhausted_keys
    with _key_lock:
        total = len(_AVAILABLE_KEYS)
        next_idx = _current_key_idx + 1
        if next_idx < total:
            _current_key_idx = next_idx
            print(f"[KEY] Switching to key {next_idx + 1}/{total}")
            return True
        TPD_EXHAUSTED = True
    print(f"[KEY] All {total} key(s) daily token limit exhausted — AI calls stopped")
    return False


def _extract_json(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        start = text.find('{', pos)
        if start == -1:
            return None
        try:
            obj, _ = decoder.raw_decode(text, start)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        pos = start + 1


def _load_prompt(filename):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

MOODLE_CATEGORIZE    = _load_prompt("moodle_categorize.txt")
EMAIL_CATEGORIZE     = _load_prompt("email_categorize.txt")
EMAIL_DETAIL_ANALYZE = _load_prompt("email_detail_analyze.txt")
MOODLE_EVENT_EXTRACT = _load_prompt("moodle_event_extract.txt")

_last_call_times: dict[str, float] = {}   # provider → last call timestamp
_rate_lock = threading.Lock()             # guards _last_call_times only
TPD_EXHAUSTED = bool(_AVAILABLE_KEYS) and len(_exhausted_keys) == len(_AVAILABLE_KEYS)


def _print_tpd_429(msg: str) -> bool:
    """Handle a 429 response. Returns True if all keys exhausted, False if switched."""
    if "tokens per day" not in msg.lower():
        return False
    with _key_lock:
        key_idx = _current_key_idx
        key_no = key_idx + 1
        total = len(_AVAILABLE_KEYS)
        if key_idx not in _exhausted_keys:
            _exhausted_keys.append(key_idx)
        prefix = _key_prefix(_AVAILABLE_KEYS[key_idx]) if key_idx < len(_AVAILABLE_KEYS) else ''
        if prefix:
            _exhausted_prefixes.add(prefix)
            _save_tpd_status(_exhausted_prefixes)
    limit_match = _re.search(r"Limit (\d+)", msg)
    used_match  = _re.search(r"Used (\d+)",  msg)
    reset_match = _re.search(r"try again in (.+?)\.", msg)
    reset = reset_match.group(1) if reset_match else "unknown"
    if limit_match and used_match:
        limit = int(limit_match.group(1))
        used  = int(used_match.group(1))
        pct   = int(used / limit * 100)
        print(f"[KEY] 第 {key_no}/{total} 把金鑰已耗盡每日用量: {used:,} / {limit:,} ({pct}%) — 將在 {reset} 後重置")
    else:
        print(f"[KEY] 第 {key_no}/{total} 把金鑰已耗盡每日用量 (用量不明) — 將在 {reset} 後重置")
    switched = _try_switch_key()
    return not switched


def _call_api(messages: list[dict], max_tokens: int) -> str | None:
    with _key_lock:
        if TPD_EXHAUSTED:
            return None
        n_keys = len(_AVAILABLE_KEYS)

    if n_keys == 0:
        print("[API] No API keys available")
        return None

    for attempt in range(n_keys):
        try:
            with _key_lock:
                if TPD_EXHAUSTED:
                    break
                entry   = _AVAILABLE_KEYS[_current_key_idx]
                key_idx = _current_key_idx

            provider     = entry.get("provider", "groq")
            api_key      = entry.get("key", "")
            cfg          = PROVIDERS.get(provider, PROVIDERS["groq"])
            min_interval = cfg.get("min_interval", 0.5)

            # Per-provider rate limiting with atomic slot booking.
            # Each thread claims the next available slot inside the lock so
            # concurrent threads can't all pass the check simultaneously.
            with _rate_lock:
                now = time.time()
                last_scheduled = _last_call_times.get(provider, 0.0)
                next_slot = max(now, last_scheduled + min_interval)
                _last_call_times[provider] = next_slot
                wait = next_slot - now
            if wait > 0:
                print(f"[API] Rate-limit sleep {wait:.1f}s ({provider})")
                time.sleep(wait)

            url = cfg["base_url"] + "/chat/completions"
            print(f"[API] provider={provider} model={cfg['model']} max_tokens={max_tokens} key_idx={key_idx}")
            resp = httpx.post(
                url,
                json={
                    "model": cfg["model"],
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )

            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            print(f"[API] OK — response length {len(text)} chars")
            return text

        except httpx.HTTPStatusError as e:
            error_msg = e.response.text
            print(f"[API] HTTP {e.response.status_code} (attempt {attempt+1}/{n_keys}): {error_msg[:200]}")
            if e.response.status_code == 429:
                if _print_tpd_429(error_msg):
                    break  # daily quota exhausted, all keys tried
                # Per-minute rate limit — back off and retry with same key
                backoff = 15.0
                print(f"[API] RPM 429 — sleeping {backoff}s before retry")
                time.sleep(backoff)
                continue  # retry same key after backoff
            else:
                break
        except Exception as e:
            print(f"[API] Error (attempt {attempt+1}/{n_keys}): {str(e)[:200]}")
            break

    return None


def categorize_email(email_body, is_moodle=False):
    system_prompt = MOODLE_CATEGORIZE if is_moodle else EMAIL_CATEGORIZE
    raw = _call_api(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Email body:\n{email_body[:3000]}"},
        ],
        max_tokens=100 if is_moodle else 20,
    )
    if raw is None:
        return None
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        obj = json.loads(raw)
        category = obj.get("category")
        if is_moodle:
            course_name = (obj.get("course_name") or "").strip()
            brief       = (obj.get("brief")       or "").strip()
            if course_name and brief:
                display_subject = f"{course_name} - {brief}"
            elif course_name:
                display_subject = course_name
            else:
                display_subject = brief
            return category, display_subject
        return category
    except Exception as e:
        print(f"[DEBUG] Categorization JSON parse failed: {e}")
        return None


def extract_moodle_events(email_body):
    raw = _call_api(
        messages=[
            {"role": "system", "content": MOODLE_EVENT_EXTRACT},
            {"role": "user",   "content": f"Email body:\n{email_body[:3000]}"},
        ],
        max_tokens=300,
    )
    if raw is None:
        return []
    obj = _extract_json(raw)
    if obj is None:
        print("[DEBUG] Moodle event extract: no JSON found in response")
        return []
    return obj.get("event_times", [])


def analyze_email_detail(email_body, category=None):
    body_len = len(email_body) if email_body else 0
    with _key_lock:
        n_keys = len(_AVAILABLE_KEYS)
        tpd    = TPD_EXHAUSTED
    print(f"[DETAIL] analyze_email_detail called: body_len={body_len}, n_keys={n_keys}, TPD_EXHAUSTED={tpd}, category={category!r}")

    if not email_body or body_len < 5:
        print("[DETAIL] Email body is empty or too short — skipping AI call")
        return None

    user_content = f"Email body:\n{email_body[:4000]}"
    if category:
        user_content = f"Email category: {category}\n\n{user_content}"
    raw = _call_api(
        messages=[
            {"role": "system", "content": EMAIL_DETAIL_ANALYZE},
            {"role": "user",   "content": user_content},
        ],
        max_tokens=800,
    )
    if raw is None:
        print("[DETAIL] _call_api returned None")
        return None
    print(f"[DETAIL] _call_api returned {len(raw)} chars; first 200: {raw[:200]!r}")
    obj = _extract_json(raw)
    if obj is None:
        print(f"[DETAIL] _extract_json found no JSON object in response")
    else:
        print(f"[DETAIL] Parsed JSON keys: {list(obj.keys())}")
    return obj


def verify_api_key(key: str, provider: str = "groq") -> str:
    """Test an API key with a minimal 1-token request.

    Returns:
        "verified"   — key accepted
        "invalid"    — authentication error
        "unverified" — network or unknown error
    """
    if not key or not key.strip():
        return "unverified"
    cfg = PROVIDERS.get(provider, PROVIDERS["groq"])
    url = cfg["base_url"] + "/chat/completions"
    try:
        resp = httpx.post(
            url,
            json={
                "model": cfg["model"],
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
            headers={
                "Authorization": f"Bearer {key.strip()}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code in (401, 403):
            return "invalid"
        resp.raise_for_status()
        return "verified"
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return "invalid"
        return "unverified"
    except Exception:
        return "unverified"
