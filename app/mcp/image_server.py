from mcp.server.fastmcp import FastMCP

from app.mcp.image_tools import ImageProcessor

mcp = FastMCP("AIOS Image", instructions="Workspace-confined image inspection and opt-in resize, crop, and conversion.")
images = ImageProcessor()


@mcp.tool()
def image_info(path: str) -> dict: return images.info(path)


@mcp.tool()
def transform_image(source_path: str, output_path: str, width: int | None = None, height: int | None = None, crop: list[int] | None = None, image_format: str | None = None, quality: int = 85, overwrite: bool = False) -> dict:
    return images.transform(source_path, output_path, width, height, crop, image_format, quality, overwrite)


if __name__ == "__main__": mcp.run(transport="stdio")
