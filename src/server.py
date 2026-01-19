# src/server.py
# Run MCP server with available tools

import json

from mcp.server.fastmcp import FastMCP

from .gmail_ops import (
    create_draft_message,
    get_message_content,
    list_messages,
    send_draft,
)

mcp = FastMCP("gmail-mcp")


@mcp.tool()
def get_unread_emails(max_results: int = 3) -> str:
    """Get most recent unread emails' metadata and content body from Gmail API

    Args:
        max_results: Number of unread emails to retrieve, default to 3
    """

    messages: list[dict] = []

    unread_query = "is:unread"  # Filter for only unread messages

    for m in list_messages(max_results, query=unread_query):
        msg_id = m["id"]
        msg = get_message_content(msg_id)
        messages.append(msg)

    return json.dumps(messages)


@mcp.tool()
def create_draft_reply(reply_to_message_id: str, reply_body: str) -> dict[str, str]:
    """Create a draft reply to an Email on Gmail API

    Args:
        thread_id: String as the Email thread_id
        reply_body: Email reply body
    """

    draft = create_draft_message(reply_to_message_id, reply_body)
    return draft


@mcp.tool()
def send_draft_message(draft_id: str):
    """Send the given draft email

    Args:
        draft_id: String, Unique identifier to a Email draft
    """

    send_status = send_draft(draft_id)
    return send_status


if __name__ == "__main__":
    mcp.run()
