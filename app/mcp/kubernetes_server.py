from mcp.server.fastmcp import FastMCP
from app.mcp.kubernetes_tools import KubernetesReader
mcp = FastMCP("AIOS Kubernetes", instructions="Read-only Kubernetes contexts, resources, descriptions, and logs."); kubernetes = KubernetesReader()
@mcp.tool()
def kubernetes_contexts() -> dict: return kubernetes.contexts()
@mcp.tool()
def kubernetes_namespaces() -> dict: return kubernetes.namespaces()
@mcp.tool()
def kubernetes_resources(resource: str = "pods", namespace: str = "default", limit: int = 200) -> dict: return kubernetes.resources(resource, namespace, limit)
@mcp.tool()
def kubernetes_describe(resource: str, name: str, namespace: str = "default") -> dict: return kubernetes.describe(resource, name, namespace)
@mcp.tool()
def kubernetes_logs(pod: str, namespace: str = "default", container: str = "", tail: int = 200) -> dict: return kubernetes.logs(pod, namespace, container, tail)
if __name__ == "__main__": mcp.run(transport="stdio")
