import base64
import re
from bs4 import BeautifulSoup


def _clean_text(text: str) -> str:
    """Normalize whitespace: unify line endings, collapse 3+ blank lines to 2,
    strip trailing spaces from each line."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Strip trailing whitespace from every line
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)
    # Collapse 3+ consecutive blank lines → 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to clean, readable plain text."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove non-visible elements entirely
    for tag in soup(["script", "style", "head", "meta", "link", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return _clean_text(text)


def get_email_body(payload):
    """Extracts and decodes the readable body from a Gmail message payload.

    Prefers text/plain; falls back to text/html (stripped to plain text).
    Handles nested multipart structures recursively.
    """
    body = ""

    # ── Multipart ──
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")

            if mime_type == "text/plain":
                data = part["body"].get("data")
                if data:
                    safe_data = data + "=" * (-len(data) % 4)
                    try:
                        body += base64.urlsafe_b64decode(safe_data).decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        pass

            elif mime_type == "text/html":
                data = part["body"].get("data")
                if data and not body:   # only use HTML if no plain-text found yet
                    safe_data = data + "=" * (-len(data) % 4)
                    try:
                        raw_html = base64.urlsafe_b64decode(safe_data).decode(
                            "utf-8", errors="replace"
                        )
                        body += _html_to_text(raw_html)
                    except Exception:
                        pass

            elif "parts" in part:
                # Recurse into nested multipart (e.g. multipart/alternative inside multipart/mixed)
                sub = get_email_body(part)
                if sub and not body:
                    body += sub

    # ── Single Part ──
    else:
        data = payload.get("body", {}).get("data")
        if data:
            safe_data = data + "=" * (-len(data) % 4)
            try:
                decoded = base64.urlsafe_b64decode(safe_data).decode(
                    "utf-8", errors="replace"
                )
                if payload.get("mimeType") == "text/html":
                    body += _html_to_text(decoded)
                else:
                    body += decoded
            except Exception:
                pass

    return _clean_text(body)