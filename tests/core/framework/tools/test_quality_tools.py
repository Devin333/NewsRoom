from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_quality_tools,
)


def test_quality_citation_check_tool_passes_known_urls() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.citation_check",
            arguments={
                "report": _report("https://example.com/source"),
                "evidence_bundle": _bundle(["https://example.com/source"]),
            },
        ),
        ToolPolicy(allowed_tools=["quality.citation_check"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["passed"] is True
    assert observation.result.output["citation_coverage_score"] == 1.0


def test_quality_citation_check_tool_fails_unknown_urls() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.citation_check",
            arguments={
                "report": _report("https://example.com/missing"),
                "evidence_bundle": _bundle(["https://example.com/source"]),
            },
        ),
        ToolPolicy(allowed_tools=["quality.citation_check"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["passed"] is False
    assert observation.result.output["unknown_urls"] == ["https://example.com/missing"]


def _report(source_url: str) -> dict:
    return {
        "title": "Report",
        "sections": [
            {
                "title": "Summary",
                "content": "Supported claim.",
                "sources": [source_url],
            }
        ],
    }


def _bundle(source_urls: list[str]) -> dict:
    return {
        "bundle_id": "bundle-1",
        "items": [
            {
                "evidence_id": f"ev-{index}",
                "source_url": source_url,
                "title": "Evidence",
                "summary": "Evidence summary",
                "confidence": 0.9,
                "source_id": "source-1",
            }
            for index, source_url in enumerate(source_urls)
        ],
    }
