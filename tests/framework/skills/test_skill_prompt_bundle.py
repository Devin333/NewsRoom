from __future__ import annotations

from pathlib import Path

from framework.skills import SkillPackageLoader, SkillPromptBuilder, SkillRunContext


FIXTURES = Path("tests/fixtures/skills")


def test_prompt_builder_loads_main_references_and_examples() -> None:
    package = SkillPackageLoader().load(FIXTURES / "runnable-skill")
    bundle = SkillPromptBuilder(max_reference_chars=20).build(
        package,
        {"text": "hello"},
        SkillRunContext.for_test("runnable-skill"),
    )

    assert bundle.skill_name == "runnable-skill"
    assert "Transform input text" in bundle.main_prompt
    assert bundle.references == {"method.md": "Use direct evidence "}
    assert bundle.examples == [{"case_id": "case_001", "input": {"text": "hello"}, "expected": {"result": "ok"}}]
    assert "Main Prompt" in bundle.combined_context()
    assert "Examples" not in bundle.combined_context(include_examples=False)
