import asyncio

import pytest


mcp_package = pytest.importorskip("mcp", reason="MCP optional extra is not installed")

from mcp import Client

from evidence_assistant.mcp_server import mcp


def test_mcp_server_discovers_and_calls_clinical_evidence_tool():
    assert mcp is not None

    async def exercise_server():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "query_clinical_evidence",
                {
                    "question": "降压药应早上服用还是睡前服用？",
                    "mode": "hybrid",
                    "enable_live_apis": False,
                },
            )
        return tools, result

    tools, result = asyncio.run(exercise_server())
    assert "query_clinical_evidence" in {tool.name for tool in tools.tools}
    assert result.is_error is False
    payload = result.structured_content
    if payload and set(payload) == {"result"}:
        payload = payload["result"]
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "answered"
