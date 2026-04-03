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

def route_email(sender, subject):
    """
    Route email based on sender and subject to determine AI analysis necessity.
    """
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

def get_gmail_service():
    """
    Handle OAuth2 authentication and return the Gmail API service instance.
    """
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

def fetch_and_analyze_emails(service):
    """
    Fetch unread emails, check cache, and perform AI analysis if necessary.
    """
    try:
        init_db()
        print("Fetching the latest 10 unread emails...")
        
        results = service.users().messages().list(userId="me", q="is:unread", maxResults=10).execute()
        messages = results.get("messages", [])

        if not messages:
            print("No unread messages found.")
            return

        print("\nUnread Messages:")
        print("-" * 50)
        
        for message in messages:
            email_id = message["id"]

            msg = service.users().messages().get(
                userId="me", 
                id=email_id, 
                format="full"
            ).execute()
            
            payload = msg.get("payload", {})
            headers = msg.get("payload", {}).get("headers", [])
            sender = "Unknown Sender"
            subject = "No Subject"
            receive_time = "Unknown Time"
            
            for header in headers:
                if header["name"] == "From":
                    sender = header["value"]
                if header["name"] == "Subject":
                    subject = header["value"]
                if header["name"] == "Date":
                    receive_time = header["value"]
                    
            print(f"From:    {sender}")
            print(f"Subject: {subject}")

            initial_tag, needs_ai = route_email(sender, subject)
            print(f"Route: {initial_tag}")
            
            cached_result = get_cached_result(email_id)
            
            if cached_result:
                print("📦 [Cache] Reading analyzed result from database...")
                print(f"🏷️ Final Category: {cached_result.get('category')}")
                print(f"📌 Summary: {cached_result.get('summary')}")
            else:
                email_body = get_email_body(payload)
                
                if needs_ai and len(email_body) > 20:
                    print("🧠 AI analysis and classification in progress...")
                    
                    is_moodle_mail = (initial_tag == "📚 Moodle 通知")
                    
                    ai_result = analyze_email_content(
                        email_body, 
                        sender, 
                        receive_time, 
                        is_moodle=is_moodle_mail
                    )
                    
                    print(f"🏷️ Final Category: {ai_result.get('category')}")
                    print(f"📌 Summary: {ai_result.get('summary')}")
                    if ai_result.get('event_time'):
                        print(f"⏰ Key Time: {ai_result.get('event_time')}")
                    
                    if ai_result.get('category') != "⚠️ Analysis Failed":
                        save_analysis(email_id, ai_result)
                    else:
                        print("⚠️ Analysis failed, skipping database cache write for this execution.")

                else:
                    print(f"🏷️ Final Category: {initial_tag}")
                    
            print("-" * 50)

    except Exception as error:
        print(f"An error occurred during fetch and analyze: {error}")