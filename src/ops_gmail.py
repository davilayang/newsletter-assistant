# src/ops_gmail.py


import base64
from email.message import EmailMessage

from gmail_client import get_gmail_service


def list_recent_messages(max_results: int = 5):
    service = get_gmail_service()
    result = service.users().messages().list(
        userId="me",
        maxResults=max_results
    ).execute()
    return result.get("messages", [])


def send_email(to_addr: str, subject: str, body: str):
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
