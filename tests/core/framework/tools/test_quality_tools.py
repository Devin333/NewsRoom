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


def test_quality_claim_support_check_tool_maps_sections_to_evidence() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.claim_support_check",
            arguments={
                "report": {
                    "title": "Report",
                    "sections": [
                        {
                            "title": "Supported",
                            "content": "Supported claim.",
                            "sources": ["https://example.com/source"],
                        },
                        {
                            "title": "Unsupported",
                            "content": "Missing support.",
                            "sources": ["https://example.com/missing"],
                        },
                    ],
                },
                "evidence_bundle": _bundle(["https://example.com/source"]),
            },
        ),
        ToolPolicy(allowed_tools=["quality.claim_support_check"]),
    )

    sections = observation.result.output["sections"]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["section_count"] == 2
    assert observation.result.output["supported_section_count"] == 1
    assert observation.result.output["unsupported_section_count"] == 1
    assert observation.result.output["coverage_ratio"] == 0.5
    assert sections[0]["supported"] is True
    assert sections[0]["matched_evidence_ids"] == ["ev-0"]
    assert sections[1]["supported"] is False
    assert observation.result.output["unsupported_sections"] == ["Unsupported"]


def test_quality_claim_support_check_tool_marks_sections_without_sources_unsupported() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.claim_support_check",
            arguments={
                "report": {
                    "title": "Report",
                    "sections": [{"title": "No Sources", "content": "Uncited claim."}],
                },
                "evidence_bundle": _bundle(["https://example.com/source"]),
            },
        ),
        ToolPolicy(allowed_tools=["quality.claim_support_check"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["section_count"] == 1
    assert observation.result.output["supported_section_count"] == 0
    assert observation.result.output["unsupported_section_count"] == 1
    assert observation.result.output["unsupported_sections"] == ["No Sources"]


def test_quality_editor_score_tool_passes_fully_supported_report() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.editor_score",
            arguments={
                "report": _report("https://example.com/source"),
                "evidence_bundle": _bundle(["https://example.com/source"]),
            },
        ),
        ToolPolicy(allowed_tools=["quality.editor_score"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["passed"] is True
    assert observation.result.output["decision"] == "pass"
    assert observation.result.output["quality_score"] == 1.0
    assert observation.result.output["citation_check"]["passed"] is True
    assert observation.result.output["support_matrix"]["coverage_ratio"] == 1.0
    assert observation.result.output["editor_review"]["reasons"] == []


def test_quality_editor_score_tool_blocks_unsupported_report() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.editor_score",
            arguments={
                "report": _report("https://example.com/missing"),
                "evidence_bundle": _bundle(["https://example.com/source"]),
            },
        ),
        ToolPolicy(allowed_tools=["quality.editor_score"]),
    )

    reasons = observation.result.output["editor_review"]["reasons"]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["passed"] is False
    assert observation.result.output["decision"] == "blocked"
    assert observation.result.output["quality_score"] == 0.2
    assert observation.result.output["citation_check"]["unknown_urls"] == [
        "https://example.com/missing"
    ]
    assert observation.result.output["quality_summary"]["support_coverage"] == 0.0
    assert "report cites URLs outside the evidence bundle" in reasons
    assert "unsupported section: Summary" in reasons


def test_quality_duplicate_check_tool_groups_by_canonical_url_and_title() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.duplicate_check",
            arguments={
                "items": [
                    {
                        "source_item_id": "item-1",
                        "url": "https://example.com/news?a=1&utm_source=x",
                        "title": "Chip Export Update",
                    },
                    {
                        "source_item_id": "item-2",
                        "url": "https://example.com/news?a=1",
                        "title": "Different title",
                    },
                    {
                        "source_item_id": "item-3",
                        "url": "https://example.com/other",
                        "title": " chip   export update ",
                    },
                    {
                        "source_item_id": "item-4",
                        "url": "https://example.com/unique",
                        "title": "Unique",
                    },
                ]
            },
        ),
        ToolPolicy(allowed_tools=["quality.duplicate_check"]),
    )

    group = observation.result.output["duplicate_groups"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["item_count"] == 4
    assert observation.result.output["duplicate_group_count"] == 1
    assert observation.result.output["duplicate_item_count"] == 2
    assert group["item_ids"] == ["item-1", "item-2", "item-3"]
    assert group["indexes"] == [0, 1, 2]
    assert group["reasons"] == ["canonical_url", "normalized_title"]


def test_quality_duplicate_check_tool_returns_no_groups_for_unique_items() -> None:
    registry = ToolRegistry()
    register_quality_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="quality.duplicate_check",
            arguments={
                "items": [
                    {"source_item_id": "item-1", "url": "https://example.com/a", "title": "A"},
                    {"source_item_id": "item-2", "url": "https://example.com/b", "title": "B"},
                ]
            },
        ),
        ToolPolicy(allowed_tools=["quality.duplicate_check"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["duplicate_group_count"] == 0
    assert observation.result.output["duplicate_groups"] == []


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
                "summary": "Supported claim.",
                "confidence": 0.9,
                "source_id": "source-1",
            }
            for index, source_url in enumerate(source_urls)
        ],
    }
