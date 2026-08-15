from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports


def test_research_does_not_depend_on_legacy_or_interface_layers() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "business" / "research",
        (
            "business.boards.paper_radar",
            "business.boards",
            "interfaces",
            "infrastructure",
            "frontend",
            "apps",
        ),
    )

    assert violations == []


def test_research_rag_evaluation_does_not_import_cli_entrypoints() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "business" / "research" / "rag" / "evaluation",
        ("business.research.rag.cli",),
    )

    assert violations == []


def test_research_graphs_do_not_depend_on_legacy_orchestration() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "business" / "research" / "graphs",
        (
            "business.research.workflows",
            "framework.harness.workflow",
            "framework.workflow",
        ),
    )

    assert violations == []
