from __future__ import annotations

import tomllib

from tests.architecture._helpers import PROJECT_ROOT, imported_modules, matches_prefix


PYPROJECT = PROJECT_ROOT / "pyproject.toml"
RUN_SERVICE = PROJECT_ROOT / "interfaces" / "services" / "run_service.py"


def test_pyproject_uses_setuptools_package_auto_discovery() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    packages_find = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find")
    )

    assert isinstance(packages_find, dict)
    assert packages_find.get("where") == ["."]
    assert {"framework*", "backend*", "interfaces*", "infrastructure*"}.issubset(
        set(packages_find.get("include") or [])
    )


def test_run_service_facade_does_not_import_business_workflows_directly() -> None:
    violations = [
        imported
        for imported in imported_modules(RUN_SERVICE)
        if matches_prefix(imported, ("backend",))
    ]

    assert violations == []
