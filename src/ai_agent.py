import json
import os
import re as _re
import threading
import time
from groq import Groq
from dotenv import load_dotenv

# Load hidden variables in .env (fallback for dev)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

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
_current_key_idx = 0
_key_lock = threading.Lock()  # guards _AVAILABLE_KEYS, _current_key_idx, TPD_EXHAUSTED, LAST_API_CALL_TIME


def reload_keys():
    """Reload only verified keys from config.json.
    Called after the user saves keys in Settings — guaranteed verified-only.
    Does NOT fall back to .env so unverified keys can never slip in at runtime.
    """
    global _AVAILABLE_KEYS, _current_key_idx, TPD_EXHAUSTED
    new_keys = _load_verified_keys()
    with _key_lock:
        _AVAILABLE_KEYS  = new_keys
        _current_key_idx = 0
        TPD_EXHAUSTED    = False
    print(f"[KEY] Reloaded {len(new_keys)} verified API key(s) from config.")


def _get_client() -> Groq:
    """Return a Groq client for the currently active key."""
    if not _AVAILABLE_KEYS:
        raise RuntimeError("No API keys available. Please add a key in Settings → API Keys.")
    return Groq(api_key=_AVAILABLE_KEYS[_current_key_idx])

def _try_switch_key() -> bool:
    """Switch to the next available key. Returns True if switched, False if all keys exhausted."""
    global _current_key_idx, TPD_EXHAUSTED
    with _key_lock:
        next_idx = _current_key_idx + 1
        if next_idx < len(_AVAILABLE_KEYS):
            _current_key_idx = next_idx
            print(f"[KEY] Switched to API key {_current_key_idx + 1}")
            return True
        TPD_EXHAUSTED = True
    print(f"[KEY] All API key(s) exhausted — stopping AI analysis.")
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
TPD_EXHAUSTED = False  # set True when daily token limit is hit; stops all further AI calls

def _print_tpd_429(msg) -> bool:
    """
    If this is a per-day token 429:
      - Print a clean debug line with usage stats.
      - Attempt to switch to the next API key.
    Returns True if ALL keys are now exhausted (caller should break),
    or False if a new key is available (caller should try the next key).
    Returns False for non-TPD 429s (caller breaks immediately).
    """
    if "tokens per day" not in msg.lower():
        return False
    limit_match = _re.search(r"Limit (\d+)", msg)
    used_match  = _re.search(r"Used (\d+)",  msg)
    reset_match = _re.search(r"try again in (.+?)\.", msg)
    key_label   = f"key{_current_key_idx + 1}"
    if limit_match and used_match:
        limit     = int(limit_match.group(1))
        used      = int(used_match.group(1))
        remaining = limit - used
        pct       = int(used / limit * 100)
        reset     = reset_match.group(1) if reset_match else "unknown"
        print(f"[DEBUG] [{key_label}] Tokens(daily) : {used:,} / {limit:,} used ({pct}%)  •  {remaining:,} remaining (resets in {reset})")
    else:
        print(f"[DEBUG] [{key_label}] Daily token limit hit (could not parse usage).")
    # Try switching to the next key
    switched = _try_switch_key()
    return not switched  # True = all exhausted (break), False = switched (retry)


def _call_groq(messages: list[dict], max_tokens: int) -> str | None:
    """Execute one Groq API call with rate limiting and key-switching on 429.
    Returns the raw response text, or None on any failure or when TPD exhausted."""
    global LAST_API_CALL_TIME

    # Check TPD and compute rate-limit wait atomically
    with _key_lock:
        if TPD_EXHAUSTED:
            return None
        elapsed = time.time() - LAST_API_CALL_TIME
        wait = MIN_INTERVAL - elapsed
        n_keys = len(_AVAILABLE_KEYS)

    # Sleep outside the lock so other threads are not blocked
    if wait > 0:
        time.sleep(wait)

    for _ in range(n_keys):
        try:
            # Snapshot the current key under the lock, then release before the network call
            with _key_lock:
                if TPD_EXHAUSTED:
                    break
                client = Groq(api_key=_AVAILABLE_KEYS[_current_key_idx])

            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=max_tokens,
            )
            with _key_lock:
                LAST_API_CALL_TIME = time.time()
            return response.choices[0].message.content.strip()

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                if _print_tpd_429(error_msg):
                    break  # all keys exhausted
                # key switched → loop continues with next key
            else:
                print(f"[DEBUG] Groq API call failed: {e}")
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
    user_content = f"Email body:\n{email_body[:4000]}"
    if category:
        user_content = f"Email category: {category}\n\n{user_content}"
    raw = _call_groq(
        messages=[
            {"role": "system", "content": EMAIL_DETAIL_ANALYZE},
            {"role": "user",   "content": user_content},
        ],
        max_tokens=1500,  # raised from 1000 — give model more room to close JSON cleanly
    )
    if raw is None:
        return None
    obj = _extract_json(raw)
    if obj is None:
        print(f"[DEBUG] Detail analysis: no JSON object found in response (first 400 chars): {raw[:400]}")
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
