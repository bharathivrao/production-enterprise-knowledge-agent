"""Local stdio MCP adapter for the same read-only dispatcher used by the API.

This intentionally does not expose an HTTP listener: authentication for a
remotely accessible MCP endpoint belongs to the enterprise access-control stage.
"""

import asyncio

from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import ToolAnnotations

from app.core.config import get_settings
from app.retrieval.scope import PUBLIC_SCOPE
from app.tools.dispatcher import ToolDispatcher, ToolError


mcp = MCPServer(
    "enterprise-knowledge-readonly",
    instructions="Read-only public-scope search and chunk reading. No write tools.",
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False)


def _execute(name: str, arguments: dict) -> list[dict]:
    settings = get_settings()
    dispatcher = ToolDispatcher(
        PUBLIC_SCOPE, max_calls=1,
        max_elapsed_seconds=settings.tool_max_elapsed_seconds,
    )
    try:
        return dispatcher.execute(name, arguments).result
    except ToolError as error:
        # Only safe, controlled messages cross the MCP boundary.
        raise MCPError(-32602, f"{error.code}: {error}") from None


@mcp.tool(annotations=READ_ONLY)
async def search_documents(query: str, top_k: int = 3) -> list[dict]:
    """Search public-scope documents; return short previews and chunk IDs."""
    return await asyncio.to_thread(
        _execute, "search_documents", {"query": query, "top_k": top_k},
    )


@mcp.tool(annotations=READ_ONLY)
async def read_document_chunks(chunk_ids: list[str]) -> list[dict]:
    """Read up to three authorized chunks selected by their IDs."""
    return await asyncio.to_thread(
        _execute, "read_document_chunks", {"chunk_ids": chunk_ids},
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
