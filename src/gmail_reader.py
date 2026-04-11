import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# import other source code
from src.email_parser import get_email_body
from src.ai_agent import analyze_email_content, get_email_summary, get_email_summaries_batch, SUMMARY_BATCH_SIZE
from src.db_manager import init_db, get_cached_result, save_analysis, remove_stale_emails

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
        return "作業死線", False
    # Grade released
    if any(k in subject for k in ["成績", "grade", "Grade", "分數"]):
        return "成績公布", False
    # Submission confirmed
    if any(k in subject for k in ["繳交確認", "submission received", "Submission received"]):
        return "繳交確認", False
    # Class cancelled
    if any(k in subject for k in ["停課", "取消上課", "cancel class", "Cancel class"]):
        return "停課通知", False
    # Exam related
    if any(k in subject for k in ["考試", "期中", "期末", "小考", "quiz", "Quiz", "exam", "Exam", "midterm", "Midterm", "final", "Final"]):
        return "考試相關", False
    # New assignment published
    if any(k in subject for k in ["作業", "homework", "Homework", "assignment", "Assignment", "繳交", "上傳"]):
        return "作業公布", False
    # Fall back to AI for anything else
    return "等待 AI 分類", True


def _classify_school_by_subject(subject):
    """Keyword rules for general NCKU campus email subjects."""
    # Lectures / events (sign-up required)
    if any(k in subject for k in ["講座", "演講", "說明會", "工作坊", "workshop", "Workshop",
                                   "論壇", "研討會", "表演", "音樂會", "競賽", "活動報名"]):
        return "講座活動", False
    # Important announcements affecting student rights
    if any(k in subject for k in ["停電", "停水", "選課", "繳費", "系統維護", "系統停機",
                                   "重要通知", "緊急", "公告", "異動", "停辦"]):
        return "重要公告", False
    # General non-mandatory notices
    if any(k in subject for k in ["問卷", "填寫", "宣導", "通知", "出刊", "電子報", "節能", "防疫"]):
        return "一般宣導", False
    # Uncertain — let AI decide
    return "等待 AI 分類", True


# Route email based on sender and subject to determine AI analysis necessity.
def route_email(sender, subject):
    sender_lower = sender.lower()

    # ── Sender-based hard routes (no AI ever needed) ──
    if "moodle" in sender_lower:
        # Try keyword match first; fall back to AI only when truly ambiguous
        category, needs_ai = _classify_moodle_by_subject(subject)
        return category, needs_ai, True   # third value = is_moodle

    if "消費合作社" in sender:
        return "校園廣告", False, False

    if "coursera" in sender_lower:
        return "外部學習", False, False

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


METADATA_BATCH_SIZE = 10  # Gmail concurrent request limit per user

def _batch_fetch_metadata(service, message_ids):
    """Fetch metadata in chunks of METADATA_BATCH_SIZE to avoid Gmail's concurrent request limit."""
    meta_map = {}

    def handle_response(request_id, response, exception):
        if exception is None:
            meta_map[request_id] = response
        else:
            print(f"[BATCH] Metadata fetch failed for {request_id}: {exception}")

    for i in range(0, len(message_ids), METADATA_BATCH_SIZE):
        chunk = message_ids[i : i + METADATA_BATCH_SIZE]
        batch = service.new_batch_http_request(callback=handle_response)
        for msg_id in chunk:
            batch.add(
                service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ),
                request_id=msg_id
            )
        batch.execute()

    return meta_map


def _parse_meta(msg_meta):
    """Extract sender, subject, receive_time, is_unread, is_starred from a metadata response."""
    label_ids = msg_meta.get("labelIds", [])
    headers = msg_meta.get("payload", {}).get("headers", [])
    sender, subject, receive_time = "Unknown Sender", "No Subject", "Unknown Time"
    for h in headers:
        if h["name"] == "From":
            sender = h["value"].split('<')[0].strip().strip('"').strip('\u201c').strip('\u201d').strip()
        elif h["name"] == "Subject":
            subject = h["value"]
        elif h["name"] == "Date":
            receive_time = h["value"]
    return sender, subject, receive_time, "UNREAD" in label_ids, "STARRED" in label_ids


# Generator version: yields one email dict at a time as each is processed.
# Pass page_token to fetch a specific page (used for background pagination).
# Yields a {"_next_page_token": "..."} sentinel at the end if more pages exist.
#
# Two-pass strategy for speed:
#   Pass 1 — yield cached + rule-based emails immediately (near-instant)
#   Pass 2 — process emails that need AI analysis (slower, but don't block pass 1)
def fetch_and_analyze_emails(service, page_token=None):
    init_db()
    print(f"[SYSTEM] Fetching emails (page_token={page_token or 'first page'})...")

    list_kwargs = {"userId": "me", "q": "is:inbox", "maxResults": MAX_RESULTS}
    if page_token:
        list_kwargs["pageToken"] = page_token

    results = service.users().messages().list(**list_kwargs).execute()
    messages = results.get("messages", [])

    if not messages:
        print("[SYSTEM] No messages found.")
        return

    # Remove DB entries that are no longer in this inbox page
    remove_stale_emails({m["id"] for m in messages})

    # Single batch request replaces N individual metadata API calls
    print(f"[SYSTEM] Batch fetching metadata for {len(messages)} emails...")
    meta_map = _batch_fetch_metadata(service, [m["id"] for m in messages])

    ai_queue      = []  # (index, email_id, sender, subject, receive_time, is_unread, is_starred, is_moodle_mail)
    summary_queue = []  # same tuple — rule-based emails that need a summary-only AI call

    # ── Pass 1: yield cached and rule-classified emails immediately ──
    for i, message in enumerate(messages):
        try:
            email_id = message["id"]
            msg_meta = meta_map.get(email_id)
            if not msg_meta:
                continue

            sender, subject, receive_time, is_unread, is_starred = _parse_meta(msg_meta)
            initial_tag, needs_ai, is_moodle_mail = route_email(sender, subject)

            cached = get_cached_result(email_id)
            if cached:
                print(f"[CACHE] Loaded: {subject[:20]}...")
                yield {
                    "id": email_id, "sender": sender, "time": receive_time[:16],
                    "category": cached.get('category'), "summary": cached.get('summary'),
                    "event_time": cached.get('event_time'),
                    "is_unread": is_unread, "is_starred": is_starred, "_index": i
                }
            elif not needs_ai:
                print(f"[RULES] Classified: {subject[:20]}... → {initial_tag}")
                # Don't save to DB yet — Pass 3 will save once it has the AI summary.
                # Saving here with the raw subject would get cached and block Pass 3 forever.
                yield {
                    "id": email_id, "sender": sender, "time": receive_time[:16],
                    "category": initial_tag, "summary": subject,
                    "event_time": None,
                    "is_unread": is_unread, "is_starred": is_starred, "_index": i
                }
                summary_queue.append((i, email_id, sender, subject, receive_time, is_unread, is_starred, initial_tag))
            else:
                ai_queue.append((i, email_id, sender, subject, receive_time, is_unread, is_starred, is_moodle_mail))

        except Exception as error:
            print(f"[ERROR] Pass 1 failed for {message['id']}: {error}")

    # ── Pass 2: process emails that need AI (yields after each AI call) ──
    for i, email_id, sender, subject, receive_time, is_unread, is_starred, is_moodle_mail in ai_queue:
        try:
            msg_full = service.users().messages().get(userId="me", id=email_id, format="full").execute()
            email_body = get_email_body(msg_full.get("payload", {}))

            final_category, final_summary, final_event_time = "等待 AI 分類", subject, None
            if len(email_body) > 20:
                print(f"[AI] Analyzing: {subject[:20]}...")
                ai_result = analyze_email_content(email_body, sender, receive_time, is_moodle=is_moodle_mail)
                if ai_result.get('category') != "⚠️ Analysis Failed":
                    final_category  = ai_result.get('category')
                    final_summary   = ai_result.get('summary')
                    final_event_time = ai_result.get('event_time')
                    ai_result["sender"] = sender
                    ai_result["time"]   = receive_time
                    save_analysis(email_id, ai_result)
                else:
                    print(f"⚠️ Analysis failed for {email_id}")

            yield {
                "id": email_id, "sender": sender, "time": receive_time[:16],
                "category": final_category, "summary": final_summary,
                "event_time": final_event_time,
                "is_unread": is_unread, "is_starred": is_starred, "_index": i
            }
        except Exception as error:
            print(f"[ERROR] Pass 2 AI failed for {email_id}: {error}")

    # ── Pass 3: batch-summarize rule-based emails (SUMMARY_BATCH_SIZE emails per API call) ──
    for batch_start in range(0, len(summary_queue), SUMMARY_BATCH_SIZE):
        batch = summary_queue[batch_start : batch_start + SUMMARY_BATCH_SIZE]

        # Fetch full bodies for every email in this batch
        bodies = []
        for item in batch:
            i, email_id, sender, subject, receive_time, is_unread, is_starred, category = item
            try:
                msg_full = service.users().messages().get(userId="me", id=email_id, format="full").execute()
                email_body = get_email_body(msg_full.get("payload", {}))
                bodies.append(email_body if len(email_body) > 20 else subject)
            except Exception as error:
                print(f"[ERROR] Pass 3 body fetch failed for {email_id}: {error}")
                bodies.append(subject)  # fallback so index alignment stays intact

        print(f"[AI] Batch summarizing {len(batch)} emails...")
        summaries = get_email_summaries_batch(bodies)

        for j, item in enumerate(batch):
            i, email_id, sender, subject, receive_time, is_unread, is_starred, category = item
            new_summary = summaries.get(j)
            if new_summary:
                save_analysis(email_id, {
                    "sender": sender, "time": receive_time,
                    "category": category, "summary": new_summary,
                    "event_time": None, "action_required": None,
                })
                yield {"_update": True, "id": email_id, "summary": new_summary}

    # If Gmail says there are more pages, yield a sentinel so the caller can chain
    next_token = results.get("nextPageToken")
    if next_token:
        yield {"_next_page_token": next_token}