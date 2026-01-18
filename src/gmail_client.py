# src/gmail_client.py
#

from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Minimum scopes for Gmail read + send
# https://developers.google.com/workspace/gmail/api/auth/scopes
SCOPES: Sequence[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


def get_gmail_service():
    creds: Credentials | None = None

    # Load saved tokens
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # If missing or expired, run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        # Save for later
        with TOKEN_FILE.open("w") as f:
            f.write(creds.to_json())

    # Create Gmail API service
    return build("gmail", "v1", credentials=creds)
