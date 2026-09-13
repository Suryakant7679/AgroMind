from mcp.server.fastmcp import FastMCP
from app.mcp.git_tools import GitInspector

mcp = FastMCP("AIOS Git", instructions="Read-only Git repository inspection.")
git = GitInspector()

@mcp.tool()
def git_status() -> dict: return git.status()
@mcp.tool()
def git_diff(staged: bool = False, path: str = "") -> dict: return git.diff(staged, path)
@mcp.tool()
def git_log(limit: int = 20) -> dict: return git.log(limit)
@mcp.tool()
def git_show(revision: str = "HEAD") -> dict: return git.show(revision)
@mcp.tool()
def git_branches() -> dict: return git.branches()

if __name__ == "__main__": mcp.run(transport="stdio")
