from mcp.server.fastmcp import FastMCP

from app.mcp.duckduckgo_tools import search_web

mcp = FastMCP("AIOS DuckDuckGo", instructions="Search the public web and return citation-ready source URLs.")

@mcp.tool()
def duckduckgo_search(query: str, max_results: int = 5) -> list[dict]:
    return search_web(query, max_results)

if __name__ == "__main__":
    mcp.run(transport="stdio")
