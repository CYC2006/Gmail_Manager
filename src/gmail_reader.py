import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# import other source code
from src.email_parser import get_email_body
from src.ai_agent import analyze_email_content
from src.db_manager import init_db, get_cached_result, save_analysis

# Upgraded scope for modifying email states (read, archive, trash, star)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Max mail count per page
MAX_RESULTS = 50

# ──────────────────────────────────────────────
# Rule-based keyword classifiers (no AI needed)
# Returns (category_string, needs_ai: bool)
# ──────────────────────────────────────────────

def _classify_moodle_by_subject(subject):
    """Keyword rules for Moodle notification subjects."""
    s = subject.lower()
    # Deadline / due date reminders
    if any(k in subject for k in ["截止", "Due", "due", "期限", "deadline", "Deadline"]):
        return "💀 作業死線", False
    # Grade released
    if any(k in subject for k in ["成績", "grade", "Grade", "分數"]):
        return "💯 成績公布", False
    # Submission confirmed
    if any(k in subject for k in ["繳交確認", "submission received", "Submission received"]):
        return "✅ 繳交確認", False
    # Class cancelled
    if any(k in subject for k in ["停課", "取消上課", "cancel class", "Cancel class"]):
        return "🛑 停課通知", False
    # Exam related
    if any(k in subject for k in ["考試", "期中", "期末", "小考", "quiz", "Quiz", "exam", "Exam", "midterm", "Midterm", "final", "Final"]):
        return "📝 考試相關", False
    # New assignment published
    if any(k in subject for k in ["作業", "homework", "Homework", "assignment", "Assignment", "繳交", "上傳"]):
        return "📝 作業公布", False
    # Fall back to AI for anything else
    return "🔄 等待 AI 分類", True


def _classify_school_by_subject(subject):
    """Keyword rules for general NCKU campus email subjects."""
    # Lectures / events (sign-up required)
    if any(k in subject for k in ["講座", "演講", "說明會", "工作坊", "workshop", "Workshop",
                                   "論壇", "研討會", "表演", "音樂會", "競賽", "活動報名"]):
        return "🎉 講座活動", False
    # Important announcements affecting student rights
    if any(k in subject for k in ["停電", "停水", "選課", "繳費", "系統維護", "系統停機",
                                   "重要通知", "緊急", "公告", "異動", "停辦"]):
        return "📌 重要公告", False
    # General non-mandatory notices
    if any(k in subject for k in ["問卷", "填寫", "宣導", "通知", "出刊", "電子報", "節能", "防疫"]):
        return "📢 一般宣導", False
    # Uncertain — let AI decide
    return "🔄 等待 AI 分類", True


# Route email based on sender and subject to determine AI analysis necessity.
def route_email(sender, subject):
    sender_lower = sender.lower()

    # ── Sender-based hard routes (no AI ever needed) ──
    if "moodle" in sender_lower:
        # Try keyword match first; fall back to AI only when truly ambiguous
        category, needs_ai = _classify_moodle_by_subject(subject)
        return category, needs_ai, True   # third value = is_moodle

    if "消費合作社" in sender:
        return "🗑️ 校園廣告", False, False

    if "coursera" in sender_lower:
        return "💻 外部學習", False, False

    # ── NCKU campus emails ──
    if "ncku.edu.tw" in sender_lower or "處" in sender or "中心" in sender or "館" in sender:
        category, needs_ai = _classify_school_by_subject(subject)
        return category, needs_ai, False

    # ── Everything else — try subject keywords, then AI ──
    category, needs_ai = _classify_school_by_subject(subject)
    return category, needs_ai, False


# Handle OAuth2 authentication and return the Gmail API service instance.
def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as error:
        print(f"Failed to build Gmail service: {error}")
        return None
    

# get Number of mails of INBOX / UNREAD / STARRED
def get_inbox_stats(service):
    try:
        inbox  = service.users().labels().get(userId="me", id="INBOX").execute()
        unread = service.users().labels().get(userId="me", id="UNREAD").execute()
        starred = service.users().labels().get(userId="me", id="STARRED").execute()
        return {
            "inbox":   inbox.get("messagesTotal", 0),
            "unread":  inbox.get("messagesUnread", 0),
            "starred": starred.get("messagesTotal", 0),
        }
    except Exception as e:
        print(f"[ERROR] Failed to get inbox stats: {e}")
        return {"inbox": 0, "unread": 0, "starred": 0}


# Generator version: yields one email dict at a time as each is processed.
# Pass page_token to fetch a specific page (used for background pagination).
# Yields a {"_next_page_token": "..."} sentinel at the end if more pages exist.
def fetch_and_analyze_emails(service, page_token=None):
    init_db()
    print(f"[SYSTEM] Fetching emails (page_token={page_token or 'first page'})...")

    list_kwargs = {"userId": "me", "q": "is:inbox", "maxResults": MAX_RESULTS}
    if page_token:
        list_kwargs["pageToken"] = page_token

    results = service.users().messages().list(**list_kwargs).execute()
    messages = results.get("messages", [])

    if not messages:
        print("[SYSTEM] No unread messages found.")
        return
    
    for message in messages:
        try:
            email_id = message["id"]
            
            msg_meta = service.users().messages().get(
                userId="me", id=email_id, format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            
            label_ids = msg_meta.get("labelIds", [])
            is_unread = "UNREAD" in label_ids
            is_starred = "STARRED" in label_ids

            headers = msg_meta.get("payload", {}).get("headers", [])
            sender = "Unknown Sender"
            subject = "No Subject"
            receive_time = "Unknown Time"
            
            for header in headers:
                if header["name"] == "From":
                    sender = header["value"].split('<')[0].strip().strip('"').strip('\u201c').strip('\u201d').strip()
                elif header["name"] == "Subject":
                    subject = header["value"]
                elif header["name"] == "Date":
                    receive_time = header["value"]

            initial_tag, needs_ai, is_moodle_mail = route_email(sender, subject)
            final_category = initial_tag
            final_summary = subject  # default: use subject when AI is skipped

            # check cache
            cached_result = get_cached_result(email_id)

            if cached_result:
                print(f"[CACHE] Loaded: {subject[:20]}...")
                final_category = cached_result.get('category')
                final_summary = cached_result.get('summary')
            elif needs_ai:
                # Only download full payload when AI analysis is actually needed
                msg_full = service.users().messages().get(userId="me", id=email_id, format="full").execute()
                email_body = get_email_body(msg_full.get("payload", {}))

                if len(email_body) > 20:
                    print(f"[AI] Analyzing: {subject[:20]}...")
                    ai_result = analyze_email_content(email_body, sender, receive_time, is_moodle=is_moodle_mail)

                    if ai_result.get('category') != "⚠️ Analysis Failed":
                        final_category = ai_result.get('category')
                        final_summary = ai_result.get('summary')
                        ai_result["sender"] = sender
                        ai_result["time"] = receive_time
                        save_analysis(email_id, ai_result)
                    else:
                        print(f"⚠️ Analysis failed for {email_id}")
            else:
                print(f"[RULES] Classified: {subject[:20]}... → {initial_tag}")

        except Exception as error:
            print(f"[ERROR] Failed to process email {message['id']}: {error}")
            continue

        yield {
            "id": email_id,
            "sender": sender,
            "time": receive_time[:16],
            "category": final_category,
            "summary": final_summary,
            "is_unread": is_unread,
            "is_starred": is_starred
        }

    # If Gmail says there are more pages, yield a sentinel so the caller can chain
    next_token = results.get("nextPageToken")
    if next_token:
        yield {"_next_page_token": next_token}