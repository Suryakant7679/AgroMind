from mcp.server.fastmcp import FastMCP
from app.mcp.docker_tools import container_logs, inspect_container, list_containers, list_images

mcp = FastMCP("AIOS Docker", instructions="Read-only Docker container, image, inspection, and log tools.")

@mcp.tool()
def docker_containers(all_containers: bool = True) -> list[dict]: return list_containers(all_containers)
@mcp.tool()
def docker_inspect(name: str) -> dict: return inspect_container(name)
@mcp.tool()
def docker_logs(name: str, tail: int = 100) -> dict: return container_logs(name, tail)
@mcp.tool()
def docker_images() -> list[dict]: return list_images()

if __name__ == "__main__": mcp.run(transport="stdio")
