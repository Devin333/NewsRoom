from __future__ import annotations

from pathlib import Path

from framework.skills import MockSkillExecutor, SkillPackageLoader, SkillPromptBuilder, SkillRunContext


FIXTURES = Path("tests/fixtures/skills")


def test_mock_skill_executor_returns_fixed_output_and_echo() -> None:
    package = SkillPackageLoader().load(FIXTURES / "runnable-skill")
    context = SkillRunContext.for_test("runnable-skill")
    prompt_bundle = SkillPromptBuilder().build(package, {"text": "hello"}, context)

    fixed = MockSkillExecutor(outputs={"runnable-skill": {"result": "ok"}}).execute(
        package,
        {"text": "hello"},
        prompt_bundle,
        context,
    )
    echo = MockSkillExecutor().execute(package, {"text": "hello"}, prompt_bundle, context)

    assert fixed.data == {"result": "ok"}
    assert echo.data == {"echo": {"text": "hello"}}
