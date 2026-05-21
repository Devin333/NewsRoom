from __future__ import annotations

from pathlib import Path

from framework.skills import (
    EvidenceRequiredGate,
    NoEmptyOutputGate,
    NoErrorStatusGate,
    SchemaValidGate,
    SkillPackageLoader,
    SkillQualityGateRunner,
    SkillRunContext,
    SkillSchemaValidator,
)


FIXTURES = Path("tests/fixtures/skills")


def test_builtin_quality_gates() -> None:
    package = SkillPackageLoader().load(FIXTURES / "runnable-skill")
    context = SkillRunContext.for_test("runnable-skill")

    assert NoEmptyOutputGate().evaluate(package, {}, {"result": "ok"}, context).passed
    assert not NoEmptyOutputGate().evaluate(package, {}, {}, context).passed
    assert EvidenceRequiredGate().evaluate(package, {}, {"citations": [{"source_id": "fixture"}]}, context).passed
    assert EvidenceRequiredGate().evaluate(
        package,
        {},
        {"claim_results": [{"evidence_spans": [{"span": "hello"}]}]},
        context,
    ).passed
    assert not EvidenceRequiredGate().evaluate(package, {}, {"result": "ok"}, context).passed
    assert SchemaValidGate(SkillSchemaValidator()).evaluate(package, {}, {"result": "ok"}, context).passed
    assert not SchemaValidGate(SkillSchemaValidator()).evaluate(package, {}, {"missing": "ok"}, context).passed
    assert NoErrorStatusGate().evaluate(package, {}, {"status": "ok"}, context).passed
    assert not NoErrorStatusGate().evaluate(package, {}, {"status": "failed"}, context).passed


def test_quality_gate_runner_uses_declared_gates() -> None:
    package = SkillPackageLoader().load(FIXTURES / "runnable-skill")
    context = SkillRunContext.for_test("runnable-skill")
    results = SkillQualityGateRunner().run(package, {"text": "hello"}, {"result": "ok"}, context)

    assert [result.gate_name for result in results] == ["no_empty_output", "schema_valid"]
    assert all(result.passed for result in results)
