from __future__ import annotations

from pathlib import Path

from framework.skills import SkillPackageLoader, SkillSchemaValidator


FIXTURES = Path("tests/fixtures/skills")


def test_schema_validator_validates_input_and_output_success() -> None:
    package = SkillPackageLoader().load(FIXTURES / "runnable-skill")
    validator = SkillSchemaValidator()

    assert validator.validate_input(package, {"text": "hello"}).ok
    assert validator.validate_output(package, {"result": "ok"}).ok


def test_schema_validator_reports_input_and_output_failures() -> None:
    package = SkillPackageLoader().load(FIXTURES / "runnable-skill")
    validator = SkillSchemaValidator()

    input_result = validator.validate_input(package, {"missing": "hello"})
    output_result = validator.validate_output(package, {"evidence": []})

    assert not input_result.ok
    assert input_result.issues[0].code == "schema_validation_failed"
    assert input_result.errors_as_skill_details()[0].code == "schema_validation_failed"
    assert not output_result.ok


def test_schema_validator_reports_missing_and_invalid_schema(tmp_path: Path) -> None:
    validator = SkillSchemaValidator()
    invalid_schema = tmp_path / "invalid.schema.json"
    invalid_schema.write_text("{not-json", encoding="utf-8")

    missing = validator.validate_data({}, tmp_path / "missing.schema.json")
    invalid = validator.validate_data({}, invalid_schema)

    assert missing.issues[0].code == "schema_file_missing"
    assert invalid.issues[0].code == "schema_json_invalid"
