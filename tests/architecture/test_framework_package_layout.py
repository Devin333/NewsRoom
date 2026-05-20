from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT


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


def test_framework_root_has_no_runtime_modules() -> None:
    allowed = {"__init__.py", "py.typed"}
    unexpected = [
        path.name
        for path in (PROJECT_ROOT / "framework").glob("*.py*")
        if path.name not in allowed
    ]

    assert unexpected == []
