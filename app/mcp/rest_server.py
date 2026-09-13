from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.rest_tools import rest_request

mcp = FastMCP("AIOS REST", instructions="SSRF-protected REST client. Mutating methods require explicit opt-in.")


@mcp.tool()
def request_api(method: str, url: str, headers: dict[str, str] | None = None, query: dict[str, str] | None = None, json_body: Any = None, timeout: int = 15, max_chars: int = 100_000) -> dict:
    return rest_request(method, url, headers, query, json_body, timeout, max_chars)


if __name__ == "__main__": mcp.run(transport="stdio")
