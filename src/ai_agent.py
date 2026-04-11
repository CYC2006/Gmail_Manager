import json
import os
import re as _re
import time
from groq import Groq
from dotenv import load_dotenv

# Load hidden variables in .env
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

MODEL = "llama-3.3-70b-versatile"


# Multi-key support
_AVAILABLE_KEYS = [
    os.getenv("key1"),
    os.getenv("key2")
]
_AVAILABLE_KEYS = [k for k in _AVAILABLE_KEYS if k]

if not _AVAILABLE_KEYS:
     raise ValueError("no GROQ API KEY found in .env")

_current_key_idx = 0

def _get_client() -> Groq:
    """Return a Groq client for the currently active key."""
    return Groq(api_key=_AVAILABLE_KEYS[_current_key_idx])

def _try_switch_key() -> bool:
    """Switch to the next available key. Returns True if switched, False if all keys exhausted."""
    global _current_key_idx, TPD_EXHAUSTED
    next_idx = _current_key_idx + 1
    if next_idx < len(_AVAILABLE_KEYS):
        _current_key_idx = next_idx
        print(f"[KEY] Switched to API key {_current_key_idx + 1}")
        return True
    TPD_EXHAUSTED = True
    print(f"[KEY] All API key(s) exhausted — stopping AI analysis.")
    return False


# Prompts — loaded from txt files in src/prompts/
def _load_prompt(filename):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

MOODLE_CATEGORIZE = _load_prompt("moodle_categorize.txt")
EMAIL_CATEGORIZE  = _load_prompt("email_categorize.txt")


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


def categorize_email(email_body, is_moodle=False):
    """Call the AI to categorize one email. Returns the category string, or None on failure."""
    global LAST_API_CALL_TIME

    system_prompt = MOODLE_CATEGORIZE if is_moodle else EMAIL_CATEGORIZE
    user_content  = f"Email body:\n{email_body[:3000]}"

    elapsed = time.time() - LAST_API_CALL_TIME
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    # Try once per available key — no retries, no backoff.
    # On 429: switch key and try once more; any other error: stop immediately.
    for _ in range(len(_AVAILABLE_KEYS)):
        try:
            response = _get_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.1,
                max_tokens=20,
            )

            LAST_API_CALL_TIME = time.time()

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()

            result = json.loads(raw)
            return result.get("category")

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                if _print_tpd_429(error_msg):
                    break  # all keys exhausted — stop entirely
                # key switched → loop continues with next key immediately
            else:
                print(f"[DEBUG] Categorization failed: {e}")
                break

    return None
