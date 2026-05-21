from __future__ import annotations

from tests.business.foundation.skills._helpers import load_skill_package, metadata_value, skill_paths


def test_skill_frontmatter_loads_with_package_loader() -> None:
    for skill_path in skill_paths():
        package = load_skill_package(skill_path)
        metadata = package.metadata

        assert metadata_value(metadata, "name") == skill_path.name
        assert metadata_value(metadata, "version") == "1.0.0"
        assert metadata_value(metadata, "description")
        assert metadata_value(metadata, "category")
        assert len(metadata_value(metadata, "tags")) >= 3
        assert (skill_path / metadata_value(metadata, "input_schema")).is_file()
        assert (skill_path / metadata_value(metadata, "output_schema")).is_file()
        assert {"llm", "schema_validator"}.issubset(set(metadata_value(metadata, "allowed_tools")))
        assert metadata_value(metadata, "risk_level") == "medium"
        assert metadata_value(metadata, "owner") == "business-foundation"


def test_skill_frontmatter_declares_required_quality_gates() -> None:
    for skill_path in skill_paths():
        package = load_skill_package(skill_path)
        quality_gates = set(metadata_value(package.metadata, "quality_gates"))

        assert "schema_valid" in quality_gates
        assert "no_empty_output" in quality_gates
