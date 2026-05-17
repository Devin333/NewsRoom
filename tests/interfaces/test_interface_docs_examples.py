from __future__ import annotations

from pathlib import Path


REQUIRED_DOCS = [
    "docs/09-INTERFACES_CLI_API_MCP.md",
    "docs/api/README.md",
    "docs/api/openapi.json",
    "docs/sdk/python.md",
    "docs/web-console.md",
    "docs/mcp.md",
]

REQUIRED_EXAMPLES = [
    "examples/api/run_daily.py",
    "examples/api/list_reports.py",
    "examples/sdk/run_daily.py",
    "examples/sdk/latest_report.py",
    "examples/mcp/read_latest_report.py",
]


def test_interface_docs_and_examples_exist() -> None:
    missing = [path for path in [*REQUIRED_DOCS, *REQUIRED_EXAMPLES] if not Path(path).exists()]

    assert missing == []


def test_interface_main_doc_covers_required_topics() -> None:
    text = Path("docs/09-INTERFACES_CLI_API_MCP.md").read_text(encoding="utf-8")

    for phrase in [
        "Interface Boundary",
        "CLI Command Map",
        "API Endpoint Map",
        "SDK Usage",
        "MCP Surface",
        "Auth And Rate Limit",
        "Response Envelope",
        "Request-ID",
        "interface-smoke",
        "Current Limits",
    ]:
        assert phrase in text


def test_readme_links_interface_docs_and_examples() -> None:
    text = Path("README.md").read_text(encoding="utf-8")

    for path in REQUIRED_DOCS:
        assert path in text
    for directory in ["examples/api/", "examples/sdk/", "examples/mcp/"]:
        assert directory in text


def test_mcp_doc_describes_dangerous_tool_confirmation() -> None:
    text = Path("docs/mcp.md").read_text(encoding="utf-8")

    assert "news.run.cancel" in text
    assert "requires_confirmation" in text
    assert "side_effect_level" in text
    assert "external_write" in text


def test_example_scripts_have_main_guards() -> None:
    for path in REQUIRED_EXAMPLES:
        text = Path(path).read_text(encoding="utf-8")
        assert 'if __name__ == "__main__":' in text
