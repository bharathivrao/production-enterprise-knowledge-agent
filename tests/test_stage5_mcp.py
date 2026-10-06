import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError

from app.tools import mcp_server
from app.tools.dispatcher import ToolError


def test_mcp_registers_only_read_only_tools():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "search_documents", "read_document_chunks",
    }
    assert all(tool.annotations.read_only_hint is True for tool in tools)


def test_mcp_adapter_uses_shared_dispatcher_and_public_scope():
    with patch("app.tools.mcp_server.ToolDispatcher") as dispatcher_type:
        dispatcher_type.return_value.execute.return_value.result = [{"chunk_id": "x"}]
        result = mcp_server._execute("search_documents", {"query": "payments"})
    assert result == [{"chunk_id": "x"}]
    assert dispatcher_type.call_args.args[0] is mcp_server.PUBLIC_SCOPE
    dispatcher_type.return_value.execute.assert_called_once_with(
        "search_documents", {"query": "payments"},
    )


def test_mcp_adapter_never_exposes_internal_error():
    with patch("app.tools.mcp_server.ToolDispatcher") as dispatcher_type:
        dispatcher_type.return_value.execute.side_effect = ToolError(
            "invalid_arguments", "Invalid tool arguments",
        )
        with pytest.raises(MCPError, match="invalid_arguments"):
            mcp_server._execute("read_document_chunks", {"chunk_ids": []})


def test_stdio_mcp_boundary_lists_tools_and_rejects_bad_arguments():
    async def check():
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "app.tools.mcp_server"],
            cwd=str(Path(__file__).resolve().parents[1]),
            # The SDK forwards only a small allowlist of parent environment
            # variables. CI has no .env, so supply the required test setting.
            env={"POSTGRES_PASSWORD": "mcp-test-only"},
        )
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == {
                    "search_documents", "read_document_chunks",
                }
                with pytest.raises(MCPError, match="invalid_arguments"):
                    await session.call_tool("read_document_chunks", {"chunk_ids": []})

    asyncio.run(check())
