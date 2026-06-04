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
