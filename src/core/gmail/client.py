# src/core/gmail/client.py
# Set up connection to Gmail API

import logging

from pathlib import Path
from typing import Sequence

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


# Minimum scopes for Gmail read + send
# https://developers.google.com/workspace/gmail/api/auth/scopes
SCOPES: Sequence[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

CREDENTIALS_FILE = Path("creds/credentials.json")
TOKEN_FILE = Path("creds/token.json")


def authenticate(interactive: bool = True) -> Credentials:
    """Load or obtain Gmail OAuth credentials.

    Args:
        interactive: If True, opens a browser for re-auth when needed.
                     If False, raises an error instead (safe for agent sessions).
    """
    creds: Credentials | None = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.expired:
            logger.info(
                "Gmail OAuth token expired (refresh_token=%s)",
                bool(creds.refresh_token),
            )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                logger.warning("Gmail refresh token invalid.")
                TOKEN_FILE.unlink(missing_ok=True)
                creds = None

        if not creds or not creds.valid:
            if not interactive:
                raise RuntimeError(
                    "Gmail credentials are missing or expired. "
                    "Run `uv run python -m src.core.gmail.client` to re-authenticate, "
                    "then restart the agent."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)  # type: ignore

        with TOKEN_FILE.open("w") as f:
            f.write(creds.to_json())  # type: ignore

    return creds  # type: ignore


def get_gmail_service(interactive: bool = True):
    """Build and return an authenticated Gmail API service client."""
    creds = authenticate(interactive=interactive)
    return build("gmail", "v1", credentials=creds)


if __name__ == "__main__":
    # Run this directly to (re-)authenticate before starting the agent:
    #   uv run python -m src.core.gmail.client
    authenticate(interactive=True)
    print("Gmail authentication successful. token.json updated.")
