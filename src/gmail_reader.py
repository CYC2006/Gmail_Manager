import os.path
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# import other source code
from src.email_parser import get_email_body
from src.ai_agent import categorize_email, extract_moodle_events
import src.ai_agent as _ai_agent
from src.db_manager import init_db, get_cached_result, save_analysis, save_matched_prefs
from src.preference_matcher import match_preferences
from src.calendar_db import init_calendar_db, add_event
from src.categories import CAL_WORTHY, OTHER

# Upgraded scope for modifying email states (read, archive, trash, star)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Max mail count per page
MAX_RESULTS = 50


# Handle OAuth2 authentication and return the Gmail API service instance.
def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Token has been revoked or expired beyond silent refresh.
                # Delete the stale token file and fall through to browser re-auth.
                print("[AUTH] Token expired/revoked — launching browser re-authentication.")
                if os.path.exists("token.json"):
                    os.remove("token.json")
                creds = None

        if not creds or not creds.valid:
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


def build_action_service():
    """Build a FRESH, independent Gmail service from existing valid credentials.

    Call this for every user-initiated action (delete, archive, star, mark-read)
    so each action gets its own httplib2.Http connection pool and never shares an
    SSL socket with the background email-fetch service.  httplib2.Http is NOT
    thread-safe across concurrent operations, and sharing one instance between
    the streaming fetch thread and an action thread causes TLS memory corruption
    (libmalloc EXC_BREAKPOINT / SIGTRAP on macOS ARM64).

    Cost: reads token.json (~1 KB) + checks expiry (no network) + builds from
    the locally-cached discovery document — typically < 5 ms.
    """
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            if creds and creds.valid:
                return build("gmail", "v1", credentials=creds)
        except Exception:
            pass
    # Fallback: full auth flow (handles expired / missing token)
    return get_gmail_service()


# get Number of mails of INBOX / UNREAD / STARRED (inbox-scoped)
def get_inbox_stats(service):
    try:
        inbox = service.users().labels().get(userId="me", id="INBOX").execute()
        # inbox-scoped starred: messages.list gives resultSizeEstimate quickly
        starred_result = service.users().messages().list(
            userId="me", q="is:starred is:inbox", maxResults=1
        ).execute()
        return {
            "inbox":   inbox.get("messagesTotal", 0),
            "unread":  inbox.get("messagesUnread", 0),
            "starred": starred_result.get("resultSizeEstimate", 0),
        }
    except Exception as e:
        print(f"[ERROR] Failed to get inbox stats: {e}")
        return {"inbox": 0, "unread": 0, "starred": 0}


def get_all_mail_stats(service):
    """Return total / unread / starred counts for All Mail (excludes Trash and Spam)."""
    try:
        total_result  = service.users().messages().list(
            userId="me", q="-in:trash -in:spam", maxResults=1
        ).execute()
        unread_label  = service.users().labels().get(userId="me", id="UNREAD").execute()
        starred_label = service.users().labels().get(userId="me", id="STARRED").execute()
        return {
            "total":   total_result.get("resultSizeEstimate", 0),
            "unread":  unread_label.get("messagesTotal", 0),
            "starred": starred_label.get("messagesTotal", 0),
        }
    except Exception as e:
        print(f"[ERROR] Failed to get all mail stats: {e}")
        return {"total": 0, "unread": 0, "starred": 0}


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
    headers   = msg_meta.get("payload", {}).get("headers", [])
    sender, subject, receive_time = "Unknown Sender", "No Subject", "Unknown Time"
    for h in headers:
        if h["name"] == "From":
            sender = h["value"].split('<')[0].strip().strip('"').strip('\u201c').strip('\u201d').strip()
        elif h["name"] == "Subject":
            subject = h["value"]
        elif h["name"] == "Date":
            receive_time = h["value"]
    return sender, subject, receive_time, "UNREAD" in label_ids, "STARRED" in label_ids


# Generator: yields one email dict at a time as each is processed.
# Pass page_token to fetch a specific page (used for background pagination).
# Yields a {"_next_page_token": "..."} sentinel at the end if more pages exist.
#
# Two-pass strategy:
#   Pass 1 — yield cached emails immediately (near-instant)
#   Pass 2 — AI categorizes uncached emails one by one (slower)
#
# query defaults to All Mail (inbox + archived, excludes trash/spam).
# Inbox is a filtered view of All Mail in the UI layer (is_in_inbox flag).
def fetch_and_analyze_emails(service, page_token=None, page_offset=0,
                              query="-in:trash -in:spam"):
    init_db()
    init_calendar_db()
    print(f"[SYSTEM] Fetching emails (page_token={page_token or 'first page'})...")

    list_kwargs = {"userId": "me", "q": query, "maxResults": MAX_RESULTS}
    if page_token:
        list_kwargs["pageToken"] = page_token

    results  = service.users().messages().list(**list_kwargs).execute()
    messages = results.get("messages", [])

    if not messages:
        print("[SYSTEM] No messages found.")
        return

    print(f"[SYSTEM] Batch fetching metadata for {len(messages)} emails...")
    meta_map = _batch_fetch_metadata(service, [m["id"] for m in messages])

    # (index, email_id, sender, subject, receive_time, is_unread, is_starred, is_moodle, is_in_inbox)
    ai_queue = []

    # ── Pass 1: yield cached emails immediately ──
    for i, message in enumerate(messages):
        try:
            email_id = message["id"]
            msg_meta = meta_map.get(email_id)
            if not msg_meta:
                continue

            sender, subject, receive_time, is_unread, is_starred = _parse_meta(msg_meta)
            label_ids  = msg_meta.get("labelIds", [])
            is_in_inbox = "INBOX" in label_ids
            is_moodle  = "moodle" in sender.lower()

            cached = get_cached_result(email_id)
            if cached:
                print(f"[CACHE] Loaded: {subject[:30]}...")
                matched_prefs = cached.get("matched_prefs")
                if matched_prefs is None:
                    # old cache entry — run a quick subject-only match and persist
                    matched_prefs = match_preferences(subject, "", cached.get("category", ""))
                    save_matched_prefs(email_id, matched_prefs)
                yield {
                    "id": email_id, "sender": sender, "time": receive_time[:16],
                    "category": cached.get("category"), "subject": subject,
                    "is_unread": is_unread, "is_starred": is_starred,
                    "is_in_inbox": is_in_inbox, "_index": i + page_offset,
                    "matched_prefs": matched_prefs,
                }
            else:
                ai_queue.append((i, email_id, sender, subject, receive_time,
                                 is_unread, is_starred, is_moodle, is_in_inbox))

        except Exception as error:
            print(f"[ERROR] Pass 1 failed for {message['id']}: {error}")

    # ── Pass 2: AI categorize uncached emails ──
    tpd_logged = False
    for i, email_id, sender, subject, receive_time, is_unread, is_starred, is_moodle, is_in_inbox in ai_queue:
        if _ai_agent.TPD_EXHAUSTED:
            if not tpd_logged:
                print("[SYSTEM] Daily token limit exhausted — remaining emails shown uncategorized.")
                tpd_logged = True
            yield {
                "id": email_id, "sender": sender, "time": receive_time[:16],
                "category": OTHER, "subject": subject,
                "is_unread": is_unread, "is_starred": is_starred,
                "is_in_inbox": is_in_inbox, "_index": i + page_offset,
                "matched_prefs": [],
            }
            continue

        try:
            msg_full   = service.users().messages().get(userId="me", id=email_id, format="full").execute()
            email_body = get_email_body(msg_full.get("payload", {}))

            category      = OTHER
            matched_prefs = []
            if len(email_body) > 20:
                print(f"[AI] Categorizing: {subject[:30]}...")
                result = categorize_email(email_body, is_moodle=is_moodle)
                if result:
                    category = result
                    save_analysis(email_id, {
                        "sender": sender, "time": receive_time,
                        "category": category, "summary": subject,
                        "event_time": None, "action_required": None,
                    })
                    # match against full body (most accurate) and persist
                    matched_prefs = match_preferences(subject, email_body, category)
                    save_matched_prefs(email_id, matched_prefs)

                    if is_moodle and category in CAL_WORTHY:
                        print(f"[CAL] Extracting events from Moodle mail: {subject[:30]}...")
                        events = extract_moodle_events(email_body)
                        added = 0
                        for ev in events:
                            lbl = ev.get("label", "")
                            t   = ev.get("time", "")
                            if lbl and t and add_event(
                                email_id, lbl, t,
                                source="moodle_auto", category=category
                            ):
                                added += 1
                        if added:
                            print(f"[CAL] Added {added} event(s) for {email_id}")
                else:
                    print(f"[WARN] Categorization returned None for {email_id}")

            yield {
                "id": email_id, "sender": sender, "time": receive_time[:16],
                "category": category, "subject": subject,
                "is_unread": is_unread, "is_starred": is_starred,
                "is_in_inbox": is_in_inbox, "_index": i + page_offset,
                "matched_prefs": matched_prefs,
            }
        except Exception as error:
            print(f"[ERROR] Pass 2 failed for {email_id}: {error}")

    # If Gmail says there are more pages, yield a sentinel so the caller can chain
    next_token = results.get("nextPageToken")
    if next_token:
        yield {"_next_page_token": next_token}


def fetch_simple_emails(service, query, page_token=None, page_offset=0):
    """Lightweight metadata-only fetch for Sent / Trash views.

    No AI categorization, no DB cache reads/writes.  Each yielded dict includes
    is_in_inbox so the UI layer can decide which action buttons to show.
    Yields a {"_next_page_token": "..."} sentinel when more pages exist.
    """
    list_kwargs = {"userId": "me", "q": query, "maxResults": MAX_RESULTS}
    if page_token:
        list_kwargs["pageToken"] = page_token

    results  = service.users().messages().list(**list_kwargs).execute()
    messages = results.get("messages", [])
    if not messages:
        return

    meta_map = _batch_fetch_metadata(service, [m["id"] for m in messages])

    for i, message in enumerate(messages):
        email_id = message["id"]
        msg_meta = meta_map.get(email_id)
        if not msg_meta:
            continue
        sender, subject, receive_time, is_unread, is_starred = _parse_meta(msg_meta)
        label_ids = msg_meta.get("labelIds", [])
        yield {
            "id": email_id, "sender": sender, "time": receive_time[:16],
            "category": OTHER, "subject": subject,
            "is_unread": is_unread, "is_starred": is_starred,
            "is_in_inbox": "INBOX" in label_ids,
            "_index": i + page_offset,
            "matched_prefs": [],
        }

    next_token = results.get("nextPageToken")
    if next_token:
        yield {"_next_page_token": next_token}
