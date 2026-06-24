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


def _reflow_plain_text(text: str) -> str:
    """Reflow hard-wrapped plain text into natural paragraphs.

    Email clients insert hard line breaks at ~72 chars. This joins those soft
    wraps back into continuous paragraphs, matching Gmail's web display.
    Blank lines (paragraph separators) are preserved. Blocks that look
    structured (quoted lines, lists) are left as-is.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = re.split(r'\n{2,}', text)
    result = []
    for para in paragraphs:
        lines = [l.rstrip() for l in para.split('\n')]
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            continue
        # Preserve structured blocks: quoted text or list items
        is_structured = any(
            re.match(r'^\s*>|^\s*[-*•]\s|\s*\d+[.)]\s', l)
            for l in non_empty
        )
        if is_structured or len(non_empty) == 1:
            result.append('\n'.join(lines))
        else:
            result.append(' '.join(l.strip() for l in non_empty))
    return '\n\n'.join(result)


def _html_to_text(html: str) -> str:
    """Convert HTML to clean, readable plain text."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove non-visible elements entirely
    for tag in soup(["script", "style", "head", "meta", "link", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return _clean_text(text)


def _decode_part(data: str, mime_type: str, label: str) -> str:
    """Base64-decode one message part and return plain text.
    Logs a warning (instead of silently returning '') if decoding fails."""
    safe_data = data + "=" * (-len(data) % 4)
    try:
        decoded = base64.urlsafe_b64decode(safe_data).decode("utf-8", errors="replace")
        if mime_type == "text/html":
            return _html_to_text(decoded)
        return _reflow_plain_text(decoded)
    except Exception as e:
        print(f"[PARSER] Failed to decode {label} part ({mime_type}): {e}")
        return ""


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
                    body += _decode_part(data, "text/plain", "plain-text")

            elif mime_type == "text/html":
                data = part["body"].get("data")
                if data and not body:   # only use HTML if no plain-text found yet
                    body += _decode_part(data, "text/html", "html")

            elif "parts" in part:
                # Recurse into nested multipart (e.g. multipart/alternative inside multipart/mixed)
                sub = get_email_body(part)
                if sub and not body:
                    body += sub

    # ── Single Part ──
    else:
        data = payload.get("body", {}).get("data")
        if data:
            mime_type = payload.get("mimeType", "")
            body += _decode_part(data, mime_type, "single-part")

    return _clean_text(body)
