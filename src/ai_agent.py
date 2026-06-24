import json
import os
import re as _re
import threading
import time
from datetime import date
from groq import Groq
from dotenv import load_dotenv

# Load hidden variables in .env (fallback for dev)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
_TPD_STATUS_PATH = os.path.join(ROOT_DIR, 'data', 'tpd_status.json')


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
    """Persist today's exhausted key prefixes to disk."""
    os.makedirs(os.path.dirname(_TPD_STATUS_PATH), exist_ok=True)
    with open(_TPD_STATUS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': str(date.today()), 'exhausted_keys': sorted(exhausted_prefixes)}, f)


def get_tpd_status() -> dict:
    """Return TPD status for the API endpoint: all_exhausted flag + per-key prefix list."""
    today_exhausted = _load_tpd_status()
    return {
        'date': str(date.today()),
        'all_exhausted': TPD_EXHAUSTED,
        'exhausted_keys': sorted(today_exhausted),
    }

MODEL = "llama-3.3-70b-versatile"


def _load_verified_keys() -> list[str]:
    """Load only verified keys from config.json.
    config.json is written exclusively by _verify_all_and_save()
    which filters to verified-only before writing — so every key
    here has passed a live Groq API check.
    """
    try:
        from src.config_manager import get_groq_api_keys
        return get_groq_api_keys()
    except Exception:
        return []


def _load_keys_with_dev_fallback() -> list[str]:
    """For cold startup only: try config first, fall back to .env for dev use."""
    keys = _load_verified_keys()
    if keys:
        return keys
    # dev fallback — .env keys are NOT verified, only used when config is empty
    dev_keys = [os.getenv("key1"), os.getenv("key2"), os.getenv("key3")]
    dev_keys = [k for k in dev_keys if k]
    if dev_keys:
        print("[KEY] Warning: using unverified .env keys. Add verified keys in Settings → API Keys.")
    return dev_keys


# Multi-key support — reloaded on demand via reload_keys()
_AVAILABLE_KEYS: list[str] = _load_keys_with_dev_fallback()
_exhausted_prefixes: set[str] = _load_tpd_status()  # restore today's exhausted state from disk
_exhausted_keys: list[int] = [
    i for i, k in enumerate(_AVAILABLE_KEYS) if (k[:8] if k else '') in _exhausted_prefixes
]
# find first non-exhausted key; default to 0 if all exhausted
_current_key_idx = next(
    (i for i in range(len(_AVAILABLE_KEYS)) if i not in _exhausted_keys), 0
)
_key_lock = threading.Lock()  # guards _AVAILABLE_KEYS, _current_key_idx, TPD_EXHAUSTED, LAST_API_CALL_TIME


def _key_prefix(key: str) -> str:
    return key[:8] if key else ''


def reload_keys():
    """Reload only verified keys from config.json.
    Called after the user saves keys in Settings — guaranteed verified-only.
    Does NOT fall back to .env so unverified keys can never slip in at runtime.
    """
    global _AVAILABLE_KEYS, _current_key_idx, TPD_EXHAUSTED, _exhausted_keys, _exhausted_prefixes
    new_keys = _load_verified_keys()
    today_exhausted = _load_tpd_status()
    # find which indices of the new key list are already exhausted today
    exhausted_idxs = [i for i, k in enumerate(new_keys) if _key_prefix(k) in today_exhausted]
    all_exhausted  = bool(new_keys) and len(exhausted_idxs) == len(new_keys)
    # pick first non-exhausted key as current
    first_ok = next((i for i in range(len(new_keys)) if i not in exhausted_idxs), 0)
    with _key_lock:
        _AVAILABLE_KEYS    = new_keys
        _current_key_idx   = first_ok
        TPD_EXHAUSTED      = all_exhausted
        _exhausted_keys    = exhausted_idxs
        _exhausted_prefixes = today_exhausted
    print(f"[KEY] Reloaded {len(new_keys)} verified API key(s) from config. "
          f"Exhausted today: {len(exhausted_idxs)}/{len(new_keys)}")


def _get_client() -> Groq:
    """Return a Groq client for the currently active key."""
    if not _AVAILABLE_KEYS:
        raise RuntimeError("No API keys available. Please add a key in Settings → API Keys.")
    return Groq(api_key=_AVAILABLE_KEYS[_current_key_idx])

def _try_switch_key() -> bool:
    """Switch to the next available key. Returns True if switched, False if all keys exhausted."""
    global _current_key_idx, TPD_EXHAUSTED, _exhausted_keys
    with _key_lock:
        total    = len(_AVAILABLE_KEYS)
        next_idx = _current_key_idx + 1
        if next_idx < total:
            _current_key_idx = next_idx
            print(f"[KEY] Switching to key {next_idx + 1}/{total}")
            return True
        TPD_EXHAUSTED = True
    print(f"[KEY] All {total} key(s) daily token limit exhausted — AI calls stopped")
    return False


# Prompts — loaded from txt files in src/prompts/
def _extract_json(text: str) -> dict | None:
    """Extract the first complete JSON object from an arbitrary string.
    Iterates through every '{' position so that preamble text containing
    curly braces does not prevent finding the actual JSON payload."""
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

MOODLE_CATEGORIZE     = _load_prompt("moodle_categorize.txt")
EMAIL_CATEGORIZE      = _load_prompt("email_categorize.txt")
EMAIL_DETAIL_ANALYZE  = _load_prompt("email_detail_analyze.txt")
MOODLE_EVENT_EXTRACT  = _load_prompt("moodle_event_extract.txt")


# Rate limiting
# Groq free tier: 30 RPM — keep at least 2 s between calls to be safe
LAST_API_CALL_TIME = 0.0
MIN_INTERVAL = 2.5  # seconds
# Restore TPD state from disk — if all keys were exhausted today before this process started,
# we should not waste time retrying calls we know will fail.
TPD_EXHAUSTED = bool(_AVAILABLE_KEYS) and len(_exhausted_keys) == len(_AVAILABLE_KEYS)

def _print_tpd_429(msg) -> bool:
    """
    If this is a per-day token 429:
      - Print a clear per-key exhaustion notice with usage stats.
      - Attempt to switch to the next API key.
    Returns True if ALL keys are now exhausted (caller should break),
    or False if a new key is available (caller should try the next key).
    Returns False for non-TPD 429s (caller breaks immediately).
    """
    if "tokens per day" not in msg.lower():
        return False
    with _key_lock:
        key_idx = _current_key_idx
        key_no  = key_idx + 1
        total   = len(_AVAILABLE_KEYS)
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
    return not switched  # True = all exhausted (break), False = switched (retry)


def _call_groq(messages: list[dict], max_tokens: int) -> str | None:
    """Execute one Groq API call with rate limiting and key-switching on 429.
    Returns the raw response text, or None on any failure or when TPD exhausted."""
    global LAST_API_CALL_TIME

    # Check TPD and compute rate-limit wait atomically
    with _key_lock:
        if TPD_EXHAUSTED:
            exhausted_snapshot = list(_exhausted_keys)
            total = len(_AVAILABLE_KEYS)
            for idx in exhausted_snapshot:
                print(f"[GROQ] 第 {idx + 1}/{total} 把金鑰已耗盡 — 跳過呼叫")
            if not exhausted_snapshot:
                print(f"[GROQ] 所有金鑰已耗盡 — 跳過呼叫")
            return None
        elapsed = time.time() - LAST_API_CALL_TIME
        wait = MIN_INTERVAL - elapsed
        n_keys = len(_AVAILABLE_KEYS)

    if n_keys == 0:
        print("[GROQ] No API keys available — cannot call Groq")
        return None

    # Sleep outside the lock so other threads are not blocked
    if wait > 0:
        print(f"[GROQ] Rate-limit sleep {wait:.1f}s")
        time.sleep(wait)

    for attempt in range(n_keys):
        try:
            with _key_lock:
                if TPD_EXHAUSTED:
                    break
                key_idx = _current_key_idx
                client  = Groq(api_key=_AVAILABLE_KEYS[key_idx])

            print(f"[GROQ] Calling model={MODEL} max_tokens={max_tokens} key_idx={key_idx}")
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=max_tokens,
            )
            with _key_lock:
                LAST_API_CALL_TIME = time.time()
            text = response.choices[0].message.content.strip()
            print(f"[GROQ] OK — response length {len(text)} chars")
            return text

        except Exception as e:
            error_msg = str(e)
            print(f"[GROQ] Error (attempt {attempt+1}/{n_keys}): {error_msg[:200]}")
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                if _print_tpd_429(error_msg):
                    break  # all keys exhausted
                # per-minute 429: brief wait then retry same key
                time.sleep(MIN_INTERVAL * 2)
            else:
                break

    return None


def categorize_email(email_body, is_moodle=False):
    """Call the AI to categorize one email.
    Non-Moodle: returns category string, or None on failure.
    Moodle: returns (category, display_subject) tuple, or None on failure.
    display_subject is formatted as "課程名稱 - 摘要"."""
    system_prompt = MOODLE_CATEGORIZE if is_moodle else EMAIL_CATEGORIZE
    raw = _call_groq(
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
    """Extract event times from a Moodle email body.
    Returns a list of {"label": str, "time": str} dicts, or [] on failure."""
    raw = _call_groq(
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
    """Run a full structured analysis of one email.
    Returns a dict with summary, action_required, event_times, urls, key_points — or None on failure."""
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
    raw = _call_groq(
        messages=[
            {"role": "system", "content": EMAIL_DETAIL_ANALYZE},
            {"role": "user",   "content": user_content},
        ],
        max_tokens=1500,
    )
    if raw is None:
        print("[DETAIL] _call_groq returned None")
        return None
    print(f"[DETAIL] _call_groq returned {len(raw)} chars; first 200: {raw[:200]!r}")
    obj = _extract_json(raw)
    if obj is None:
        print(f"[DETAIL] _extract_json found no JSON object in response")
    else:
        print(f"[DETAIL] Parsed JSON keys: {list(obj.keys())}")
    return obj


def verify_api_key(key: str) -> str:
    """Test a Groq API key with a 1-token request.

    Returns:
        "verified"   — key accepted by Groq
        "invalid"    — authentication error (wrong/expired key)
        "unverified" — network or unknown error, could not confirm
    """
    if not key or not key.strip():
        return "unverified"
    try:
        client = Groq(api_key=key.strip())
        client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=1,
        )
        return "verified"
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "invalid_api_key" in msg or "authentication" in msg or "api key" in msg:
            return "invalid"
        return "unverified"
