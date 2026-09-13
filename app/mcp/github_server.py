from mcp.server.fastmcp import FastMCP
from app.mcp.github_tools import GitHubReader

mcp = FastMCP("AIOS GitHub", instructions="Read-only GitHub repository, issue, and pull-request queries.")
github = GitHubReader()

@mcp.tool()
def github_repository(owner: str, repo: str) -> dict: return github.repository(owner, repo)
@mcp.tool()
def github_issues(owner: str, repo: str, state: str = "open", limit: int = 20) -> list[dict]: return github.issues(owner, repo, state, limit)
@mcp.tool()
def github_contributors(owner: str, repo: str, limit: int = 100) -> list[dict]: return github.contributors(owner, repo, limit)

@mcp.tool()
def github_pull_requests(owner: str, repo: str, state: str = "open", limit: int = 20, sort: str = "updated", direction: str = "desc") -> list[dict]: return github.pull_requests(owner, repo, state, limit, sort, direction)

if __name__ == "__main__": mcp.run(transport="stdio")
