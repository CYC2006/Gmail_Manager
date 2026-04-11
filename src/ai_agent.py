import json
import os
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
MODEL         = "llama-3.3-70b-versatile"  # full analysis (Pass 2)
SUMMARY_MODEL = "llama-3.1-8b-instant"     # summary only (Pass 3) — separate TPD quota, faster


# ──────────────────────────────────────────────
# Prompt templates (English instructions so LLaMA performs reliably)
# The email body may be written in Chinese — that is fine.
# System prompts are loaded from txt files in src/prompts/
# ──────────────────────────────────────────────

def _load_prompt(filename):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

MOODLE_SYSTEM        = _load_prompt("moodle_analyzer2.txt")
SCHOOL_SYSTEM        = _load_prompt("email_analyzer3.txt")
SUMMARY_SYSTEM       = _load_prompt("summary_only.txt")
SUMMARY_BATCH_SYSTEM = _load_prompt("summary_batch.txt")

SUMMARY_BATCH_SIZE = 5  # emails per batch API call

MOODLE_USER = """Sender: {sender}
Received: {receive_time}

Email body:
{text_to_analyze}"""

SCHOOL_USER = """Sender: {sender}
Received: {receive_time}

Email body:
{text_to_analyze}"""


# ──────────────────────────────────────────────
# Rate limiting
# Groq free tier: 30 RPM — keep at least 2 s between calls to be safe
# ──────────────────────────────────────────────
LAST_API_CALL_TIME = 0.0

MIN_INTERVAL = 2.5  # seconds

import re as _re

def _print_tpd_429(msg):
    """If this is a per-day token 429, print a clean summary line instead of the raw error."""
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
        return True
    return False


def analyze_email_content(clean_text, sender, receive_time, is_moodle=False):
    global LAST_API_CALL_TIME

    text_to_analyze = clean_text[:3000]

    if is_moodle:
        system_prompt = MOODLE_SYSTEM
        user_prompt = MOODLE_USER.format(
            sender=sender,
            receive_time=receive_time,
            text_to_analyze=text_to_analyze
        )
    else:
        system_prompt = SCHOOL_SYSTEM
        user_prompt = SCHOOL_USER.format(
            sender=sender,
            receive_time=receive_time,
            text_to_analyze=text_to_analyze
        )

    # Proactive pacing
    elapsed = time.time() - LAST_API_CALL_TIME
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    max_retries = 4
    base_wait = 10

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=256,
            )

            LAST_API_CALL_TIME = time.time()

            raw = response.choices[0].message.content.strip()
            # Strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()

            result = json.loads(raw)
            result["sender"] = sender
            result["time"] = receive_time
            return result

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                _print_tpd_429(error_msg)
                wait_time = base_wait * (2 ** attempt)
                print(f"[DEBUG] Rate limit — waiting {wait_time}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"[DEBUG] AI analysis failed: {e}")
                break

    return {
        "sender": sender,
        "time": receive_time,
        "category": "⚠️ Analysis Failed",
        "summary": "AI analysis failed, please read manually.",
        "event_time": None,
        "action_required": None,
    }


def get_email_summary(clean_text):
    """Lightweight call that returns only a one-sentence summary string.
    Used for rule-based emails whose category is already known via keywords."""
    global LAST_API_CALL_TIME

    text_to_analyze = clean_text[:3000]

    # Proactive pacing (shares the same rate-limit counter as analyze_email_content)
    elapsed = time.time() - LAST_API_CALL_TIME
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    max_retries = 4
    base_wait = 10

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user",   "content": f"Email body:\n{text_to_analyze}"},
                ],
                temperature=0.1,
                max_tokens=100,
            )

            LAST_API_CALL_TIME = time.time()

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()

            result = json.loads(raw)
            return result.get("summary")

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                _print_tpd_429(error_msg)
                wait_time = base_wait * (2 ** attempt)
                print(f"[DEBUG] Rate limit — waiting {wait_time}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"[DEBUG] Summary failed: {e}")
                break

    return None  # caller keeps the raw subject as fallback


def get_email_summaries_batch(texts):
    """Send up to SUMMARY_BATCH_SIZE email bodies in one API call.
    texts: list of strings (email bodies).
    Returns: dict {index: summary_string} for whichever succeeded."""
    global LAST_API_CALL_TIME

    n = len(texts)
    parts = [f"[Email {i}]\n{text[:1500]}" for i, text in enumerate(texts)]
    user_content = "\n\n---\n\n".join(parts)

    elapsed = time.time() - LAST_API_CALL_TIME
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    max_retries = 4
    base_wait = 10

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARY_BATCH_SYSTEM},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.1,
                max_tokens=60 * n,   # ~60 tokens per summary
            )

            LAST_API_CALL_TIME = time.time()

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()

            result = json.loads(raw)
            # result is a list: [{"i": 0, "summary": "..."}, ...]
            return {item["i"]: item["summary"] for item in result}

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                _print_tpd_429(error_msg)
                wait_time = base_wait * (2 ** attempt)
                print(f"[DEBUG] Rate limit — waiting {wait_time}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"[DEBUG] Batch summary failed: {e}")
                break

    return {}  # empty — caller keeps raw subjects as fallback
