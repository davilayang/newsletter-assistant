# src/server.py
# Run MCP server with available tools

from mcp.server.fastmcp import FastMCP
from .gmail_ops import list_recent_messages, send_email

mcp = FastMCP("gmail-mcp")


@mcp.tool()
def gmail_list(max_results: int = 5):
    """List recent Gmail message IDs."""
    return list_recent_messages(max_results)


@mcp.tool()
def gmail_send(to_addr: str, subject: str, body: str):
    """Send a Gmail email."""
    return send_email(to_addr, subject, body)


if __name__ == "__main__":
    mcp.run()
