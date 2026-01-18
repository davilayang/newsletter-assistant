# src/server.py
# Run MCP server with available tools

import json

from mcp.server.fastmcp import FastMCP
from .gmail_ops import list_messages, get_message_content, send_message

mcp = FastMCP("gmail-mcp")


@mcp.tool()
def get_unread_emails(max_results: int = 3):
    """"""

    messages = []

    for m in list_messages(max_results, query="is:unread"):
        msg_id = m["id"]
        msg = get_message_content(msg_id)
        messages.append(msg)


    return json.dumps(messages)


@mcp.tools()
def create_draft_reply(thread_id: str, reply_body: str):


    pass


if __name__ == "__main__":
    mcp.run()
