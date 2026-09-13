from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.filesystem_tools import WorkspaceFilesystem


mcp = FastMCP("AIOS Filesystem", instructions="Workspace-confined file listing, reading, searching, and opt-in writing.")
filesystem = WorkspaceFilesystem()


@mcp.tool()
def list_files(path: str = ".", recursive: bool = False, limit: int = 200) -> list[dict]:
    """List files beneath the configured workspace root."""
    return filesystem.list_files(path, recursive, limit)


@mcp.tool()
def read_file(path: str, max_chars: int = 100_000) -> dict:
    """Read a UTF-8 text file inside the workspace."""
    return filesystem.read_file(path, max_chars)


@mcp.tool()
def search_text(query: str, path: str = ".", limit: int = 100) -> list[dict]:
    """Search text files inside the workspace."""
    return filesystem.search_text(query, path, limit)


@mcp.tool()
def write_file(path: str, content: str, overwrite: bool = False) -> dict:
    """Write a workspace file when filesystem writes are explicitly enabled."""
    return filesystem.write_file(path, content, overwrite)


if __name__ == "__main__":
    mcp.run(transport="stdio")
