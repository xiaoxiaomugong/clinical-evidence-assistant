from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from .tool import query_clinical_evidence as _query_clinical_evidence

try:
    from mcp.server import MCPServer
except ImportError:  # pragma: no cover - exercised when optional extra is absent
    MCPServer = None  # type: ignore[assignment,misc]


INSTRUCTIONS = """
Use query_clinical_evidence for de-identified clinical education or research
questions that need traceable evidence. Preserve the returned citation numbers
when summarizing. Treat status=refused as a safety or evidence boundary, not as
an invitation to invent an answer. This service does not provide diagnosis or
individualized treatment advice.
""".strip()


if MCPServer is not None:
    mcp = MCPServer(
        "Clinical Evidence Assistant",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )

    @mcp.tool()
    def query_clinical_evidence(
        question: str,
        mode: Literal["hybrid", "knowledge", "rag"] = "hybrid",
        enable_live_apis: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """检索并核验临床证据，返回回答、编号引用、证据等级和安全门控结果。

        question 必须去除姓名、病历号等可识别信息。mode 可取 hybrid、
        knowledge 或 rag。enable_live_apis 省略时使用服务端配置；显式设为
        true 时可调用 PubMed、Europe PMC 和 ClinicalTrials.gov。
        """
        return _query_clinical_evidence(question, mode, enable_live_apis)

else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise SystemExit(
            "MCP 运行时未安装。请执行：pip install -e '.[mcp]'"
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
