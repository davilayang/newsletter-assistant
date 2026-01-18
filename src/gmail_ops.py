# src/ops_gmail.py

import base64

from email.message import EmailMessage
from .gmail_api import get_gmail_service


# Gmail Service





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
