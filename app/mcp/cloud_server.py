from mcp.server.fastmcp import FastMCP

from app.mcp.cloud_tools import CloudReader

mcp = FastMCP("AIOS Cloud", instructions="Read-only AWS, Azure, and Google Cloud inventory through configured provider CLIs.")
cloud = CloudReader()


@mcp.tool()
def cloud_providers() -> list[dict]:
    return cloud.providers()


@mcp.tool()
def cloud_inspect(provider: str, resource: str = "resources", timeout: int = 30) -> dict:
    return cloud.inspect(provider, resource, timeout)


if __name__ == "__main__":
    mcp.run(transport="stdio")
