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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in .env")

client = Groq(api_key=GROQ_API_KEY)
MODEL = "llama-3.3-70b-versatile"


# ──────────────────────────────────────────────
# Prompts — loaded from txt files in src/prompts/
# ──────────────────────────────────────────────

def _load_prompt(filename):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

MOODLE_CATEGORIZE = _load_prompt("moodle_categorize.txt")
EMAIL_CATEGORIZE  = _load_prompt("email_categorize.txt")


# ──────────────────────────────────────────────
# Rate limiting
# Groq free tier: 30 RPM — keep at least 2 s between calls to be safe
# ──────────────────────────────────────────────
LAST_API_CALL_TIME = 0.0
MIN_INTERVAL = 2.5  # seconds

TPD_EXHAUSTED = False  # set True when daily token limit is hit; stops all further AI calls


def _print_tpd_429(msg):
    """If this is a per-day token 429, print a clean summary line and set TPD_EXHAUSTED."""
    if "tokens per day" not in msg.lower():
        return False
    limit_match = _re.search(r"Limit (\d+)", msg)
    used_match  = _re.search(r"Used (\d+)",  msg)
    reset_match = _re.search(r"try again in (.+?)\.", msg)
    if limit_match and used_match:
        limit     = int(limit_match.group(1))
        used      = int(used_match.group(1))
        remaining = limit - used
        pct       = int(used / limit * 100)
        reset     = reset_match.group(1) if reset_match else "unknown"
        print(f"[DEBUG] Tokens(daily) : {used:,} / {limit:,} used ({pct}%)  •  {remaining:,} remaining (resets in {reset})")
        global TPD_EXHAUSTED
        TPD_EXHAUSTED = True
        return True
    return False


def categorize_email(email_body, is_moodle=False):
    """Call the AI to categorize one email. Returns the category string, or None on failure."""
    global LAST_API_CALL_TIME

    system_prompt = MOODLE_CATEGORIZE if is_moodle else EMAIL_CATEGORIZE
    user_content  = f"Email body:\n{email_body[:3000]}"

    elapsed = time.time() - LAST_API_CALL_TIME
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    max_retries = 4
    base_wait   = 10

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
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
                    break  # daily limit exhausted — no point retrying
                wait_time = base_wait * (2 ** attempt)
                print(f"[DEBUG] Rate limit — waiting {wait_time}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"[DEBUG] Categorization failed: {e}")
                break

    return None
