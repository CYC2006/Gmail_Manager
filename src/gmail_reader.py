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


# Route email based on sender and subject to determine AI analysis necessity.  
def route_email(sender, subject):
    sender_lower = sender.lower()
    
    if "moodle" in sender_lower:
        return "📚 Moodle 通知", True  
    elif "消費合作社" in sender:
        return "🗑️ 合作社廣告", False
    elif "coursera" in sender_lower:
        return "💻 外部學習", False
        
    elif "ncku.edu.tw" in sender_lower or "處" in sender or "中心" in sender or "館" in sender:
        return "🔄 等待 AI 分類", True
        
    else:
        return "✉️ 一般信件", True


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


# Map AI categories to Flet safe color strings for UI tags.
def get_category_color(category):
    if "Moodle" in category or "作業" in category or "Deadline" in category:
        return "orange600"
    elif "重要" in category or "警告" in category:
        return "red600"
    elif "活動" in category or "講座" in category:
        return "green600"
    elif "成績" in category:
        return "purple600"
    elif "一般" in category or "等待" in category:
        return "blue600"
    else:
        return "grey600" # Fallback color


def fetch_and_analyze_emails(service):
    """
    Fetch unread emails, check cache, perform AI analysis if necessary,
    and RETURN a list of structured dictionaries for the GUI.
    """
    email_data_list = [] # 📦 The array we will return to the GUI

    try:
        init_db()
        print("[SYSTEM] Fetching the latest 10 unread emails for GUI...")
        
        results = service.users().messages().list(userId="me", q="is:unread", maxResults=10).execute()
        messages = results.get("messages", [])

        if not messages:
            print("[SYSTEM] No unread messages found.")
            return [] # Return empty list if no emails

        for message in messages:
            email_id = message["id"]
            msg = service.users().messages().get(userId="me", id=email_id, format="full").execute()
            
            payload = msg.get("payload", {})
            headers = msg.get("payload", {}).get("headers", [])
            sender = "Unknown Sender"
            subject = "No Subject"
            receive_time = "Unknown Time"
            
            for header in headers:
                if header["name"] == "From":
                    sender = header["value"].split('<')[0].strip() # Clean up sender name
                if header["name"] == "Subject":
                    subject = header["value"]
                if header["name"] == "Date":
                    receive_time = header["value"]

            initial_tag, needs_ai = route_email(sender, subject)
            
            # Variables to store final data for this specific email
            final_category = initial_tag
            final_summary = subject # Default summary is the subject
            
            cached_result = get_cached_result(email_id)
            
            if cached_result:
                print(f"[CACHE] Loaded: {subject[:20]}...")
                final_category = cached_result.get('category')
                final_summary = cached_result.get('summary')
            else:
                email_body = get_email_body(payload)
                
                if needs_ai and len(email_body) > 20:
                    print(f"[AI] Analyzing: {subject[:20]}...")
                    is_moodle_mail = (initial_tag == "📚 Moodle 通知")
                    
                    ai_result = analyze_email_content(email_body, sender, receive_time, is_moodle=is_moodle_mail)
                    
                    if ai_result.get('category') != "⚠️ Analysis Failed":
                        final_category = ai_result.get('category')
                        final_summary = ai_result.get('summary')
                        # Inject sender and time for DB saving since ai_result might not have them
                        ai_result["sender"] = sender
                        ai_result["time"] = receive_time
                        save_analysis(email_id, ai_result)
                    else:
                        print(f"⚠️ Analysis failed for {email_id}")
                else:
                    final_category = initial_tag
                    final_summary = subject
            
            # 🎯 Pack the processed data into our dictionary format for Flet
            email_data_list.append({
                "id": email_id,
                "sender": sender,
                "time": receive_time[:16], # Truncate long date strings
                "category": final_category,
                "summary": final_summary,
                "tag_color": get_category_color(final_category)
            })

        print(f"[SYSTEM] Successfully processed {len(email_data_list)} emails for GUI.")
        return email_data_list # 🚀 Return the payload!

    except Exception as error:
        print(f"[ERROR] An error occurred during fetch and analyze: {error}")
        return []