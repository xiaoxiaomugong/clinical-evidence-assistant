"""Real subprocess transport checks (core without MCP reports N/A/skipped)."""

import asyncio
import os
import sys
from pathlib import Path

import pytest


try:
    import mcp
except ImportError:
    if os.getenv("CLINICAL_REQUIRE_MCP") == "1":
        pytest.fail("The mandatory MCP environment is missing its runtime", pytrace=False)
    pytest.skip("MCP transport is N/A without the optional runtime", allow_module_level=True)

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]


def test_stdio_subprocess_discovers_tool_and_returns_answer_and_refusal(tmp_path):
    stderr_path = tmp_path / "server.stderr"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", (
            "import logging; "
            "from evidence_assistant.mcp_server import main; "
            "logging.getLogger('clinical_stdio_probe').warning('STDERR_PROTOCOL_PROBE'); "
            "main()"
        )],
        cwd=str(ROOT),
        env={
            "PYTHONPATH": str(ROOT / "src"),
            "EVIDENCE_ASSISTANT_ENV_FILE": str(tmp_path / "absent.env"),
            "CLINICAL_EVIDENCE_ROOT": str(ROOT),
            "EVIDENCE_ASSISTANT_DATA_DIR": str(ROOT / "data"),
            "EVIDENCE_ASSISTANT_CACHE_DIR": str(tmp_path / "cache"),
            "PDF_INDEX_PATH": str(tmp_path / "absent.sqlite3"),
            "ENABLE_LIVE_APIS": "false", "ENABLE_SUPABASE": "false",
            "LLM_API_KEY": "", "PUBMED_API_KEY": "", "NCBI_EMAIL": "",
            "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": "", "SUPABASE_SECRET_KEY": "",
            "RETRIEVAL_BACKEND": "legacy", "RERANK_BACKEND": "deterministic",
            "MODEL_LOCAL_FILES_ONLY": "true", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        },
    )
    transport_errors = []

    async def on_message(message):
        if isinstance(message, Exception):
            transport_errors.append(type(message).__name__)

    async def exercise():
        # MCP's stdio reader parses every stdout line as a JSON-RPC message;
        # parse errors are delivered to this callback, not silently ignored.
        with stderr_path.open("w", encoding="utf-8") as errlog:
            async with Client(stdio_client(params, errlog=errlog), message_handler=on_message,
                              read_timeout_seconds=20) as client:
                tools = await client.list_tools()
                results = []
                for question in ("降压药应早上服用还是睡前服用？", "姓名：张三，病历号 A123456，高血压的证据？"):
                    results.append(await client.call_tool("query_clinical_evidence", {
                        "question": question, "mode": "hybrid", "enable_live_apis": False,
                    }))
                return tools, results

    tools, results = asyncio.run(asyncio.wait_for(exercise(), timeout=45))
    assert "query_clinical_evidence" in {tool.name for tool in tools.tools}
    payloads = []
    for result in results:
        assert result.is_error is False
        payload = result.structured_content
        if payload and set(payload) == {"result"}:
            payload = payload["result"]
        assert payload["schema_version"] == "1.0"
        payloads.append(payload)
    assert payloads[0]["status"] == "answered"
    assert payloads[1]["status"] == "refused"
    assert payloads[1]["answer"]["refusal_code"] == "PHI_BLOCKED"
    assert transport_errors == [], "stdout contained non-protocol data"
    stderr = stderr_path.read_text(encoding="utf-8")
    assert "STDERR_PROTOCOL_PROBE" in stderr
    assert "A123456" not in stderr
    assert "张三" not in stderr
