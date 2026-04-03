import base64
from bs4 import BeautifulSoup

def get_email_body(payload):
    # Extracts and decodes the plain text or HTML body from the email payload.
    body = ""
    
    # Multiple Parts
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType")
            
            if mime_type == "text/plain":
                data = part["body"].get("data")
                if data:
                    safe_data = data + "=" * (-len(data) % 4)
                    body += base64.urlsafe_b64decode(safe_data).decode("utf-8")
            
            elif mime_type == "text/html":
                data = part["body"].get("data")
                if data and not body:
                    safe_data = data + "=" * (-len(data) % 4)
                    raw_html = base64.urlsafe_b64decode(safe_data).decode("utf-8")
                    
                    # use BeautifulSoup to remove all HTML tags
                    soup = BeautifulSoup(raw_html, "html.parser")
                    # new line for different paragraph
                    body += soup.get_text(strip=True)

            elif "parts" in part:
                body += get_email_body(part)
    
    # Single Part
    else:
            data = payload.get("body", {}).get("data")
            if data:
                safe_data = data + "=" * (-len(data) % 4)
                decoded_content = base64.urlsafe_b64decode(safe_data).decode("utf-8")
                
                # 判斷這唯一的一層是不是 HTML
                if payload.get("mimeType") == "text/html":
                    soup = BeautifulSoup(decoded_content, "html.parser")
                    body += soup.get_text(separator="\n", strip=True)
                else:
                    body += decoded_content       

    return body