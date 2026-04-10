import json
import os
import time
from groq import Groq
from dotenv import load_dotenv

# Load hidden variables in .env
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in .env")

client = Groq(api_key=GROQ_API_KEY)
MODEL = "llama-3.3-70b-versatile"


# ──────────────────────────────────────────────
# Prompt templates (English instructions so LLaMA performs reliably)
# The email body may be written in Chinese — that is fine.
# ──────────────────────────────────────────────

MOODLE_SYSTEM = """You are a university student's smart email assistant.
You will receive a Moodle system notification email. The content may be in Chinese.
Internally translate the content to English if needed, then analyse it.

You MUST respond with valid JSON only — no markdown, no extra text.

Pick exactly ONE category from this list (copy the label exactly as written):
  "📝 作業公布"  (New assignment published)
  "💀 作業死線"  (Assignment deadline reminder)
  "💯 成績公布"  (Grade released)
  "✅ 繳交確認"  (Submission confirmed)
  "🛑 停課通知"  (Class cancelled)
  "📝 考試相關"  (Exam related)
  "❓ 其他郵件"  (Other)

Return this JSON schema:
{
  "category": "<exact label from the list above>",
  "summary": "<one concise English sentence: which course + what happened, e.g. 'Data Structures: HW3 deadline reminder'>",
  "event_time": "<deadline or exam time in YYYY-MM-DD_HH:MM format, or null>",
  "action_required": "<what the student should do, in English, or null>"
}"""

MOODLE_USER = """Sender: {sender}
Received: {receive_time}

Email body:
{text_to_analyze}"""


SCHOOL_SYSTEM = """You are a university student's smart email assistant.
You will receive a campus/school email. The content may be in Chinese.
Internally translate the content to English if needed, then analyse it.

You MUST respond with valid JSON only — no markdown, no extra text.

Pick exactly ONE category from this list (copy the label exactly as written):
  "📌 重要公告"  (Important announcement: power outage, course registration, payment, system maintenance, etc.)
  "🎉 講座活動"  (Lecture / event: talk, workshop, company info session, performance — usually requires sign-up or attendance)
  "📢 一般宣導"  (General notice: surveys, campaigns, newsletters — non-mandatory)
  "❓ 其他郵件"  (Other / cannot be classified)

Return this JSON schema:
{
  "category": "<exact label from the list above>",
  "summary": "<one concise English sentence describing the topic, e.g. 'Rock-climbing fitness workshop series'>",
  "event_time": "<event time in YYYY-MM-DD_HH:MM format, or a range YYYY-MM-DD_HH:MM ~ YYYY-MM-DD_HH:MM, or null>",
  "action_required": "<what the student should do, in English, or null>"
}"""

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
            print(f"\n[DEBUG] Groq API error: {error_msg}\n")

            if "429" in error_msg or "rate_limit" in error_msg.lower():
                wait_time = base_wait * (2 ** attempt)
                print(f"🚦 Rate limit hit! Waiting {wait_time}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"❌ AI analysis failed: {e}")
                break

    return {
        "sender": sender,
        "time": receive_time,
        "category": "⚠️ Analysis Failed",
        "summary": "AI analysis failed, please read manually.",
        "event_time": None,
        "action_required": None,
    }
