import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
# This scope only allows reading messages, which is safe for testing.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

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
            # Fetch the specific details of each message using its ID
            # We only request the metadata headers to save bandwidth and time
            msg = service.users().messages().get(
                userId="me", 
                id=message["id"], 
                format="metadata", 
                metadataHeaders=["From", "Subject"]
            ).execute()
            
            headers = msg.get("payload", {}).get("headers", [])
            sender = "Unknown Sender"
            subject = "No Subject"
            
            # Extract the From and Subject headers
            for header in headers:
                if header["name"] == "From":
                    sender = header["value"]
                if header["name"] == "Subject":
                    subject = header["value"]
                    
            print(f"From:    {sender}")
            print(f"Subject: {subject}")
            print("-" * 50)

    except Exception as error:
        print(f"An error occurred: {error}")

if __name__ == "__main__":
    main()