# src/server.py
# Run MCP server with available tools

import json

from mcp.server.fastmcp import FastMCP
from .gmail_ops import list_messages, get_message_content, send_message

mcp = FastMCP("gmail-mcp")

@mcp.tool()
def get_unread_emails(max_results: int = 3) -> str:
    """Get unread emails' metadata and content body from Gmail API

    Args:
        max_results: Number of unread emails to retrieve, default to 3
    """

    messages: list[dict] = []

    unread_query = "is:unread"

    for m in list_messages(max_results, query=unread_query):
        msg_id = m["id"]
        msg = get_message_content(msg_id)
        messages.append(msg)


    return json.dumps(messages)


@mcp.tool()
def create_draft_reply(thread_id: str, reply_body: str) -> str:
    """Create a draft reply email to the Email thread with the given reply body

    Args:
        thread_id: String as the Email thread_id
        reply_body: Email reply body
    """


    pass


@mcp.tool()
def send_draft_message(draft_id: str):
    """Send the draft email

    Args:
        draft_id: String, Unique identifier to a Email draft
    """

    pass


if __name__ == "__main__":
    mcp.run()
