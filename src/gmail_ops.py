# src/ops_gmail.py

import base64

from email.message import EmailMessage
from .gmail_api import get_gmail_service

# Helper functions

def _parse_headers(email_message) -> dict[str, str]:
    def _h(name: str) -> str:
        v = email_message.get(name)
        return str(v) if v is not None else ""
    return {
        "from": _h("From"),
        "subject": _h("Subject"),
    }


def _extract_best_body_text(email_message) -> Optional[str]:
    """
    Prefer text/plain (non-attachment). If not present, use text/html converted to text.
    """
    plain = None
    html = None

    if email_message.is_multipart():
        for part in email_message.walk():
            ctype = part.get_content_type()
            disp = part.get_content_disposition()  # None, 'inline', 'attachment'
            if disp == "attachment":
                continue

            if ctype == "text/plain" and plain is None:
                try:
                    plain = part.get_content()
                except Exception:
                    # Some messages might have weird encodings
                    payload = part.get_payload(decode=True) or b""
                    plain = payload.decode(errors="ignore")

            elif ctype == "text/html" and html is None:
                try:
                    html = part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    html = payload.decode(errors="ignore")
    else:
        # Single-part message
        ctype = email_message.get_content_type()
        try:
            content = email_message.get_content()
        except Exception:
            payload = email_message.get_payload(decode=True) or b""
            content = payload.decode(errors="ignore")

        if ctype == "text/plain":
            plain = content
        elif ctype == "text/html":
            html = content
        else:
            plain = content  # fallback

    if plain and plain.strip():
        return plain.strip()

    if html and html.strip():
        # Optional: if you want nicer HTML->text, install bs4 and replace this with BeautifulSoup.
        # For now: crude tag-strip fallback.
        import re
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text if text else None

    return None





# Gmail Operations

def list_messages(max_results: int = 5, query: str = None):
    """list_messages


    """
    service = get_gmail_service()
    result = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results
    ).execute()

    return result.get("messages", [])



def get_message_content(message_id: str):
    """Get Gmail message content and body"""

    output: List[Dict[str, Any]] = []


    service = get_gmail_service()
    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="raw")
        .execute()
    )

    headers = _parse_headers(email_message)
    body = _extract_best_body_text(email_message)

    out.append(
        {
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "from": headers["from"],
            "subject": headers["subject"],
            "snippet": msg.get("snippet"),  # still useful even if you include body
            "body": body,
        }
    )

    return output

def send_message(to_addr: str, subject: str, body: str):
    """send_email

    """
    service = get_gmail_service()

    message = EmailMessage()
    message["To"] = to_addr
    message["From"] = "me"
    message["Subject"] = subject
    message.set_content(body)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )

    return sent
