from mcp.server.fastmcp import FastMCP
from app.mcp.browser_tools import extract_links, fetch_url

mcp = FastMCP("AIOS Browser", instructions="Read public HTTP(S) text resources with SSRF protection.")

@mcp.tool()
def browse_url(url: str, max_chars: int = 50_000) -> dict: return fetch_url(url, max_chars)
@mcp.tool()
def page_links(url: str, limit: int = 100) -> list[dict]: return extract_links(url, limit)

if __name__ == "__main__": mcp.run(transport="stdio")
