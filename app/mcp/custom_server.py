from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.custom_tools import CustomMCPRegistry

mcp = FastMCP("AIOS Custom MCP", instructions="Discover and invoke explicitly configured workspace stdio MCP servers.")
registry = CustomMCPRegistry()


@mcp.tool()
def custom_servers() -> list[dict]: return registry.list_servers()


@mcp.tool()
async def custom_tools(server: str) -> dict: return await registry.list_tools(server)


@mcp.tool()
async def custom_call(server: str, tool: str, arguments: dict[str, Any] | None = None, timeout: int = 30) -> dict:
    return await registry.call_tool(server, tool, arguments, timeout)


if __name__ == "__main__": mcp.run(transport="stdio")
