from mcp.server.fastmcp import FastMCP
from app.config import load_env
from app.mcp.redis_tools import RedisReader
load_env(); mcp = FastMCP("AIOS Redis", instructions="Read-only Redis inspection confined to the AIOS namespace."); redis = RedisReader()
@mcp.tool()
def redis_keys(pattern: str = "*", limit: int = 200) -> list[dict]: return redis.keys(pattern, limit)
@mcp.tool()
def redis_get(key: str, max_chars: int = 50_000) -> dict: return redis.get(key, max_chars)
@mcp.tool()
def redis_stats() -> dict: return redis.stats()
if __name__ == "__main__": mcp.run(transport="stdio")
