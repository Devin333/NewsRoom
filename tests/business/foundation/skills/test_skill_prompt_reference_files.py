from __future__ import annotations

from tests.business.foundation.skills._helpers import skill_paths


def test_prompt_files_are_non_empty_and_structured() -> None:
    for skill_path in skill_paths():
        main_prompt = (skill_path / "prompts" / "main.md").read_text(encoding="utf-8")
        repair_prompt = (skill_path / "prompts" / "repair.md").read_text(encoding="utf-8")
        judge_prompt = (skill_path / "prompts" / "judge.md").read_text(encoding="utf-8")

        assert main_prompt.strip()
        assert "## Return Format" in main_prompt
        for heading in [
            "## Role",
            "## Task",
            "## Input Contract",
            "## Output Contract",
            "## Procedure",
            "## Constraints",
        ]:
            assert heading in main_prompt
        assert repair_prompt.strip()
        assert "## Repair Rules" in repair_prompt
        assert judge_prompt.strip()
        assert "## Failure Conditions" in judge_prompt


def test_reference_files_are_non_empty_and_structured() -> None:
    for skill_path in skill_paths():
        method = (skill_path / "references" / "method.md").read_text(encoding="utf-8")
        quality_rules = (skill_path / "references" / "quality_rules.md").read_text(
            encoding="utf-8"
        )

        assert method.strip()
        for heading in [
            "## Decision Criteria",
            "## Step-by-Step Procedure",
            "## Scoring or Classification Rules",
            "## Edge Cases",
        ]:
            assert heading in method
        assert quality_rules.strip()
        for heading in [
            "## Required Checks",
            "## Common Failure Modes",
            "## Safe Defaults",
            "## Output Validation Rules",
        ]:
            assert heading in quality_rules


def test_readmes_include_required_sections() -> None:
    for skill_path in skill_paths():
        readme = (skill_path / "README.md").read_text(encoding="utf-8")

        assert readme.strip()
        for heading in ["## Purpose", "## Usage", "## Boundaries"]:
            assert heading in readme
