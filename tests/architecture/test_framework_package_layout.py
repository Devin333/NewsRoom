from __future__ import annotations

from _helpers import PROJECT_ROOT


REQUIRED_PACKAGES = (
    "framework/shared",
    "framework/specs",
    "framework/workflow",
    "framework/agent",
    "framework/tool",
    "framework/llm",
    "framework/memory",
    "framework/workers",
    "framework/events",
    "framework/artifacts",
    "framework/governance",
)


def test_framework_required_package_layout_exists() -> None:
    missing = [
        package
        for package in REQUIRED_PACKAGES
        if not (PROJECT_ROOT / package).is_dir()
    ]

    assert missing == []
