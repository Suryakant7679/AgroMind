from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.router import MCPRouter


mcp = FastMCP("AIOS MCP Router", instructions="Classifies requests and routes them to registered AIOS MCP tools.")
router = MCPRouter()


@mcp.tool()
def classify_tool_request(request: str) -> dict:
    """Classify a natural-language request into an MCP server and suggested tool."""
    return router.classify_dict(request)


@mcp.tool()
def list_registered_tools() -> dict[str, list[str]]:
    """List tools registered with the AIOS MCP router."""
    return router.TOOL_CATALOG


if __name__ == "__main__":
    mcp.run(transport="stdio")
