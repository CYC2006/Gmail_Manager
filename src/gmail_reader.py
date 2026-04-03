import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# import other source code
from src.email_parser import get_email_body
from src.ai_agent import analyze_email_content
from src.db_manager import init_db, get_cached_result, save_analysis

# If modifying these scopes, delete the file token.json.
# This scope only allows reading messages, which is safe for testing.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def route_email(sender, subject):
    """
    根據寄件人，決定這封信的處理路徑與初步標籤
    """
    sender_lower = sender.lower()
    
    if "moodle" in sender_lower:
        return "📚 Moodle 通知", False
    elif "消費合作社" in sender:
        return "🗑️ 合作社廣告", False
    elif "coursera" in sender_lower:
        return "💻 外部學習", False
        
    # 只要是包含 ncku.edu.tw 的學校信件，但不在上述規則內
    elif "ncku.edu.tw" in sender_lower or "處" in sender or "中心" in sender or "館" in sender:
        return "🔄 等待 AI 分類", True
        
    else:
        return "✉️ 一般信件", True


def main():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        init_db()

        # Build the Gmail API service
        service = build("gmail", "v1", credentials=creds)
        print("Fetching the latest 10 unread emails...")
        
        # Request a list of unread messages
        # q="is:unread" filters for unread emails, maxResults limits the output
        results = service.users().messages().list(userId="me", q="is:unread", maxResults=10).execute()
        messages = results.get("messages", [])

        if not messages:
            print("No unread messages found.")
            return

        print("\nUnread Messages:")
        print("-" * 50)
        
        for message in messages:
            email_id = message["id"]

            # Fetch the specific details of each message using its ID
            # We only request the metadata headers to save bandwidth and time
            msg = service.users().messages().get(
                userId="me", 
                id=message["id"], 
                format="full"
            ).execute()
            
            payload = msg.get("payload", {})
            headers = msg.get("payload", {}).get("headers", [])
            sender = "Unknown Sender"
            subject = "No Subject"
            
            # Extract the From and Subject headers
            for header in headers:
                if header["name"] == "From":
                    sender = header["value"]
                if header["name"] == "Subject":
                    subject = header["value"]
                if header["name"] == "Date":
                    receive_time = header["value"]
                    
            print(f"From:    {sender}")
            print(f"Subject: {subject}")


            # 1. 執行第一層路由篩選
            initial_tag, needs_ai = route_email(sender, subject)
            print(f"Route: {initial_tag}")
            
            # 2. 檢查資料庫是否已經有這封信的分析紀錄
            cached_result = get_cached_result(email_id)
            
            if cached_result:
                print("📦 [資料庫快取] 讀取已分析結果...")
                print(f"🏷️ 最終分類: {cached_result.get('category')}")
                print(f"📌 摘要: {cached_result.get('summary')}")
            else:
                # 取得乾淨內文
                email_body = get_email_body(payload)
                
                # 如果需要 AI 分析，且內文有實質內容，就交給 Gemini
                if needs_ai and len(email_body) > 20:
                    print("🧠 AI 分析與分類中...")
                    ai_result = analyze_email_content(email_body, sender, receive_time)
                    
                    print(f"🏷️ 最終分類: {ai_result.get('category')}")
                    print(f"📌 摘要: {ai_result.get('summary')}")
                    if ai_result.get('event_time'):
                        print(f"⏰ 關鍵時間: {ai_result.get('event_time')}")
                    
                    # 🛡️ 新增防呆機制：只有當分類不是失敗時，才存入資料庫
                    if ai_result.get('category') != "⚠️ Analysis Failed":
                        save_analysis(email_id, ai_result)
                    else:
                        print("⚠️ 分析失敗，本次不寫入資料庫快取。")

                else:
                    print(f"🏷️ 最終分類: {initial_tag}")

            print("-" * 50)

    except Exception as error:
        print(f"An error occurred: {error}")


if __name__ == "__main__":
    main()