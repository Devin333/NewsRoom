from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_daily_artifact_publisher_uses_section_dispatcher() -> None:
    from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import (
        DailyIntelligenceArtifactPublisher,
    )
    from business.boards.cross_board.workflows.daily_intelligence.artifact_sections import (
        publish_daily_artifact_sections,
    )

    assert DailyIntelligenceArtifactPublisher.publisher_id == "daily_intelligence"
    assert callable(publish_daily_artifact_sections)


def test_daily_artifact_publisher_uses_output_projection_boundary() -> None:
    publisher_path = (
        PROJECT_ROOT
        / "business"
        / "boards"
        / "cross_board"
        / "workflows"
        / "daily_intelligence"
        / "artifact_publisher.py"
    )

    imports = _imports_for_file(publisher_path)

    assert (
        "business.boards.cross_board.workflows.daily_intelligence.output_projection"
        in imports
    )
    assert (
        "business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases"
        not in imports
    )


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
