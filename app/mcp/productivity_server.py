from mcp.server.fastmcp import FastMCP

from app.mcp.productivity_tools import ProductivityReader

mcp = FastMCP("AIOS Productivity", instructions="Read-only Slack channel/history and Notion search/page integrations.")
reader = ProductivityReader()


@mcp.tool()
def slack_channels(limit: int = 100) -> list[dict]: return reader.slack_channels(limit)


@mcp.tool()
def slack_history(channel: str, limit: int = 50) -> list[dict]: return reader.slack_history(channel, limit)


@mcp.tool()
def notion_search(query: str = "", limit: int = 50) -> list[dict]: return reader.notion_search(query, limit)


@mcp.tool()
def notion_page(page_id: str) -> dict: return reader.notion_page(page_id)


if __name__ == "__main__": mcp.run(transport="stdio")
