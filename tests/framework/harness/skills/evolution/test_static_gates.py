from __future__ import annotations

from dataclasses import replace

from framework.harness import (
    SkillCandidate,
    SkillEvolutionBudget,
    SkillPatchSet,
    SkillStaticGateSuite,
    SkillVersionRef,
)


def test_static_gates_reject_patch_budget_overflow() -> None:
    candidate = _candidate(
        operations=(
            {"op": "replace_section", "path": "SKILL.md#a", "value": "a"},
            {"op": "replace_section", "path": "prompts/repair.md#b", "value": "b"},
        )
    )
    suite = SkillStaticGateSuite(SkillEvolutionBudget(max_patch_operations=1, max_changed_files=1))

    results = suite.evaluate(candidate)
    failed = {result.gate_name: result for result in results if not result.passed}

    assert failed["skill_patch_budget"].details["violations"]["patch_operations"] == {"used": 2, "max": 1}


def test_static_gates_reject_high_risk_tools_without_approval() -> None:
    candidate = _candidate(allowed_tools=("llm", "shell"))

    result = SkillStaticGateSuite().allowed_tools.evaluate(candidate)

    assert result.passed is False
    assert result.details["high_risk_tools"] == ["shell"]


def test_static_gates_reject_quality_gate_removal() -> None:
    candidate = _candidate(
        operations=(
            {
                "op": "update_frontmatter_field",
                "path": "SKILL.md#quality_gates",
                "value": ["no_empty_output"],
            },
        )
    )

    result = SkillStaticGateSuite().quality_gate_retention.evaluate(candidate)

    assert result.passed is False
    assert "schema_valid" in result.details["missing_required"]


def test_static_gates_reject_secret_like_candidate_content() -> None:
    candidate = _candidate()
    candidate = replace(candidate, metadata={"token_note": "api_key=abcdefghijklmnop"})

    result = SkillStaticGateSuite().no_secret.evaluate(candidate)

    assert result.passed is False


def test_static_gates_reject_legacy_paper_radar_leakage() -> None:
    candidate = _candidate(operations=({"op": "replace_section", "path": "SKILL.md#legacy", "value": "import backend.boards.paper_radar"},))

    result = SkillStaticGateSuite().domain_boundary.evaluate(candidate)

    assert result.passed is False
    assert result.details["violations"] == ["candidate_leaks_legacy_paper_radar"]


def _candidate(
    *,
    operations: tuple[dict, ...] = ({"op": "replace_section", "path": "SKILL.md#repair", "value": "preserve refs"},),
    allowed_tools: tuple[str, ...] = ("llm", "schema_validator"),
) -> SkillCandidate:
    base = SkillVersionRef(skill_name="reader.repair", version="1.0.0")
    return SkillCandidate(
        candidate_id="candidate-static",
        base_version=base,
        patch_set=SkillPatchSet(candidate_id="candidate-static", base_skill=base, operations=operations),
        manifest_snapshot={
            "files": ["SKILL.md", "schemas/input.json", "schemas/output.json"],
            "metadata": {
                "name": "reader.repair",
                "version": "1.0.0",
                "risk_level": "medium",
                "owner": "harness",
                "allowed_tools": list(allowed_tools),
                "quality_gates": ["schema_valid", "evidence_required", "no_empty_output"],
                "input_schema": "schemas/input.json",
                "output_schema": "schemas/output.json",
            },
        },
    )
