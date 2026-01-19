# src/ops_gmail.py

import base64

from email.message import EmailMessage
from .gmail_api import get_gmail_service

from email import policy
from email.parser import BytesParser

# Helper functions


def _parse_headers(email_message) -> dict[str, str]:
    def _h(name: str) -> str:
        v = email_message.get(name)
        return str(v) if v is not None else ""

    return {
        "from": _h("From"),
        "subject": _h("Subject"),
    }


def _extract_best_body_text(email_message) -> str | None:
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

        text = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text if text else None

    return None


# Gmail Operations


def list_messages(
    max_results: int = 5, query: str | None = None
) -> list[dict[str, str]]:
    """list_messages
    List most recent messages in the inbox, optionally filtering by query
    """
    service = get_gmail_service()
    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    return result.get("messages", [])


def get_message_content(message_id: str) -> dict[str, str]:
    """get_mnessage_content
    Get a Email's metadata and content body
    """
    service = get_gmail_service()
    content = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="raw")
        .execute()
    )

    raw_bytes = base64.urlsafe_b64decode(content["raw"])
    email_message = BytesParser(policy=policy.default).parsebytes(raw_bytes)

    headers = _parse_headers(email_message)
    body = _extract_best_body_text(email_message)

    output = {
        "id": content.get("id"),  # Email Id
        "thread_id": content.get("threadId"),
        "from": headers["from"],
        "subject": headers["subject"],
        "snippet": content.get("snippet"),
        "body": body,
    }

    return output


def create_draft_message(message_id: str, reply_body: str):
    """create_draft_message
    Create a draft email that replies to the message ID with given body
    """

    service = get_gmail_service()

    # Get the message
    message = get_message_content(message_id)

    if any(
        [pattern in message["from"] for pattern in ("no-reply", "no_reply", "noreply")]
    ):
        raise ValueError(
            f"Cannot create draft for no-reply addresses. Got: `{message['from']}`"
        )

    # Build the reply
    em = EmailMessage()
    em["To"] = message["from"]
    em["Subject"] = "RE: " + message["subject"]
    em.set_content(reply_body.strip())

    raw = base64.urlsafe_b64encode(em.as_bytes()).decode("utf-8")

    draft = (
        service.users()
        .drafts()
        .create(
            userId="me",
            body={
                "message": {
                    "raw": raw,
                    "threadId": message["thread_id"],
                }
            },
        )
        .execute()
    )

    return {
        "draft_id": draft.get("id"),
        "thread_id": message["thread_id"],
        "subject": em["Subject"],
        "body": em.get_content(),
    }


def send_draft(draft_id: str):
    """send_draft
    Send the draft email
    """

    service = get_gmail_service()

    sent = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()

    return {
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
    }
