from __future__ import annotations

import tomllib

from tests.business.foundation.skills._helpers import REPO_ROOT


def test_foundation_skill_resources_are_declared_as_package_data() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = pyproject["tool"]["setuptools"]["package-data"]["business.foundation"]

    assert "skills/**/*.md" in package_data
    assert "skills/**/*.json" in package_data
    assert "skills/**/*.yaml" in package_data
    assert "skills/**/*.yml" in package_data
