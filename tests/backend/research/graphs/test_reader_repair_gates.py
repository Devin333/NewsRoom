from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.research.domain import (
    ReaderIssue,
    ReaderRepairCandidate,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairResult,
    ReaderRepairSkillCandidateSeed,
    ReaderRepairStrategy,
    ReaderRepairVerificationCandidate,
    SourceLineage,
    stable_research_id,
)
from backend.research.graphs import (
    READER_REPAIR_GATE_REFERENCES,
    build_reader_repair_gate_registry,
)
from framework.events.canonical import checksum_for
from framework.harness.memory import MemoryWriteCandidate


def test_reader_repair_registry_fails_closed_without_worker_result() -> None:
    registry = build_reader_repair_gate_registry()

    for reference in READER_REPAIR_GATE_REFERENCES:
        result = registry.resolve(reference).gate.evaluate(
            SimpleNamespace(worker_result=None)
        )

        assert result.gate_name == reference.removesuffix("@1")
        assert result.passed is False
        assert result.details["reason_code"] == (
            "reader_repair_gate_input_invalid"
        )


def test_reader_repair_gate_chain_accepts_exact_verified_candidates() -> None:
    issue = _issue()
    context_pack = ReaderRepairContextPack(
        context_id="repair-context-1",
        issue=issue,
        repair_constraints=["preserve source refs"],
        source_refs=issue.source_refs,
        source_lineage=SourceLineage(source_refs=issue.source_refs),
        failure_case_gap_report={"no_failed_cases_available": True},
    )
    candidate = _candidate(context_pack)
    verification = ReaderRepairVerificationCandidate(
        candidate_id=candidate.candidate_id,
        observations=[
            {
                "check_id": "source-lineage",
                "finding": "The localized patch preserves the cited source region.",
                "evidence_refs": issue.source_refs,
            }
        ],
        source_refs=issue.source_refs,
        metadata={
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
            )
        },
    )
    gate_results = [
        {"gate_name": "ReaderLocalizedPatchGate", "passed": True},
        {"gate_name": "ReaderRepairPayloadFidelityGate", "passed": True},
    ]
    attempt_id = stable_research_id(
        "repair_attempt",
        issue.issue_id,
        candidate.candidate_id,
    )
    repair_result = ReaderRepairResult(
        result_id=stable_research_id("repair_result", attempt_id),
        attempt_id=attempt_id,
        successful=True,
        verification_results=gate_results,
        payload_before_ref="reader-payload://paper-1",
        payload_after_ref="reader-payload://paper-1/repaired",
        source_refs=issue.source_refs,
        metadata={
            "skill_promotion_triggered": False,
            "candidate_id": candidate.candidate_id,
            "repair_summary": candidate.repair_summary,
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
                repair_verification_candidate=verification,
            ),
        },
    )
    repair_case = ReaderRepairCase(
        repair_case_id=stable_research_id(
            "repair_case",
            issue.issue_id,
            attempt_id,
        ),
        issue=issue,
        repair_strategy=candidate.repair_summary,
        repair_attempt_refs=[attempt_id],
        successful=True,
        verification_results=gate_results,
        payload_before_ref=repair_result.payload_before_ref,
        payload_after_ref=repair_result.payload_after_ref,
        source_refs=issue.source_refs,
        constraints=context_pack.repair_constraints,
        metadata={
            "active_skill_mutation": False,
            "input_bindings": _model_bindings(
                reader_repair_context_pack=context_pack,
                reader_repair_result=repair_result,
            ),
        },
    )
    strategy = _strategy(repair_case.repair_case_id)
    seed = ReaderRepairSkillCandidateSeed(
        seed_id="repair-seed-1",
        strategy=strategy,
        experience_refs=[f"repair-case://{repair_case.repair_case_id}"],
        patch_objective="Prepare governed reader-repair skill candidate input.",
        publishes_skill=False,
        metadata={"requires_harness_skill_evolution": True},
    )
    strategy_bundle = {
        "input_bindings": _model_bindings(
            reader_repair_context_pack=context_pack,
            reader_repair_case=repair_case,
        ),
        "strategies": [strategy.to_dict()],
        "skill_candidate_seeds": [seed.to_dict()],
    }
    memory_candidate = MemoryWriteCandidate(
        candidate_id=stable_research_id(
            "repair_memory_write",
            repair_case.repair_case_id,
        ),
        namespace="research.reader_repair",
        content={
            "repair_case": repair_case.to_dict(),
            "strategy_candidate_bundle": strategy_bundle,
        },
        source_refs=tuple(issue.source_refs),
        metadata={
            "active_skill_mutation": False,
            "input_bindings": {
                "reader_repair_case": checksum_for(repair_case.to_dict()),
                "strategy_candidate_bundle": checksum_for(strategy_bundle),
            },
        },
    )
    stages = (
        ("ReaderRepairIssueGate@1", "reader_issue", issue.to_dict()),
        (
            "ReaderRepairContextGate@1",
            "reader_repair_context_pack",
            context_pack.to_dict(),
        ),
        (
            "ReaderRepairCandidateGate@1",
            "reader_repair_candidate",
            candidate.to_dict(),
        ),
        (
            "ReaderRepairVerificationObservationGate@1",
            "repair_verification_candidate",
            verification.to_dict(),
        ),
        (
            "ReaderRepairResultGate@1",
            "reader_repair_result",
            repair_result.to_dict(),
        ),
        (
            "ReaderRepairCaseGate@1",
            "reader_repair_case",
            repair_case.to_dict(),
        ),
        (
            "ReaderRepairStrategyBoundaryGate@1",
            "strategy_candidate_bundle",
            strategy_bundle,
        ),
        (
            "ReaderRepairMemoryPolicyGate@1",
            "memory_write_candidate",
            memory_candidate.to_dict(),
        ),
    )
    registry = build_reader_repair_gate_registry()
    prior: dict[str, dict[str, object]] = {}

    for reference, output_key, payload in stages:
        result = registry.resolve(reference).gate.evaluate(
            _context({output_key: payload}, prior=prior)
        )
        assert result.passed is True, (reference, result.to_dict())
        prior[output_key] = payload


def test_verifier_observation_cannot_supply_harness_verdict() -> None:
    issue = _issue()
    candidate = _candidate()
    registry = build_reader_repair_gate_registry()
    gate = registry.resolve("ReaderRepairVerificationObservationGate@1").gate
    prior = {
        "reader_issue": issue.to_dict(),
        "reader_repair_candidate": candidate.to_dict(),
    }
    valid = {
        "candidate_id": candidate.candidate_id,
        "observations": [
            {
                "check_id": "source-lineage",
                "finding": "The candidate targets the cited source region.",
                "evidence_refs": issue.source_refs,
            }
        ],
        "source_refs": issue.source_refs,
        "metadata": {
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
            )
        },
    }

    accepted = gate.evaluate(
        _context({"repair_verification_candidate": valid}, prior=prior)
    )
    malicious = gate.evaluate(
        _context(
            {
                "repair_verification_candidate": {
                    **valid,
                    "passed": True,
                }
            },
            prior=prior,
        )
    )

    assert accepted.passed is True
    assert malicious.passed is False
    assert malicious.details["reason_code"] == (
        "reader_repair_gate_input_invalid"
    )


def test_subagent_candidates_reject_cross_input_checksum_substitution() -> None:
    issue = _issue()
    context_pack = _context_pack(issue)
    candidate = _candidate(context_pack)
    candidate_payload = candidate.to_dict()
    candidate_payload["metadata"]["input_bindings"][
        "reader_repair_context_pack"
    ] = checksum_for({"context_id": "other-context"})
    registry = build_reader_repair_gate_registry()

    candidate_result = registry.resolve("ReaderRepairCandidateGate@1").gate.evaluate(
        _context(
            {"reader_repair_candidate": candidate_payload},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
        )
    )

    verification = _verification(issue, candidate)
    verification_payload = verification.to_dict()
    verification_payload["metadata"]["input_bindings"][
        "reader_repair_candidate"
    ] = checksum_for({"candidate_id": "other-candidate"})
    verification_result = registry.resolve(
        "ReaderRepairVerificationObservationGate@1"
    ).gate.evaluate(
        _context(
            {"repair_verification_candidate": verification_payload},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_candidate": candidate.to_dict(),
            },
        )
    )

    assert candidate_result.passed is False
    assert "input_bindings" in candidate_result.details["violations"]
    assert verification_result.passed is False
    assert "input_bindings" in verification_result.details["violations"]


def test_result_and_case_reject_cross_input_checksum_substitution() -> None:
    issue = _issue()
    context_pack = _context_pack(issue)
    candidate = _candidate(context_pack)
    verification = _verification(issue, candidate)
    result = _verified_result(issue, candidate, verification)
    result_payload = result.to_dict()
    result_payload["metadata"]["input_bindings"][
        "reader_issue"
    ] = checksum_for({"issue_id": "other-issue"})
    registry = build_reader_repair_gate_registry()

    result_gate = registry.resolve("ReaderRepairResultGate@1").gate.evaluate(
        _context(
            {"reader_repair_result": result_payload},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_candidate": candidate.to_dict(),
                "repair_verification_candidate": verification.to_dict(),
            },
        )
    )

    case = _verified_case(context_pack, result, candidate)
    case_payload = case.to_dict()
    case_payload["metadata"]["input_bindings"][
        "reader_repair_result"
    ] = checksum_for({"result_id": "other-result"})
    case_gate = registry.resolve("ReaderRepairCaseGate@1").gate.evaluate(
        _context(
            {"reader_repair_case": case_payload},
            prior={
                "reader_repair_context_pack": context_pack.to_dict(),
                "reader_repair_result": result.to_dict(),
            },
        )
    )

    assert result_gate.passed is False
    assert "input_bindings" in result_gate.details["violations"]
    assert case_gate.passed is False
    assert "input_bindings" in case_gate.details["violations"]


def test_strategy_bundle_rejects_unverified_repair_case_refs() -> None:
    issue = _issue()
    context_pack = _context_pack(issue)
    candidate = _candidate(context_pack)
    result = _verified_result(issue, candidate, _verification(issue, candidate))
    case = _verified_case(context_pack, result, candidate)
    strategy = _strategy("foreign-repair-case")
    seed = ReaderRepairSkillCandidateSeed(
        seed_id="repair-seed-foreign",
        strategy=strategy,
        experience_refs=["repair-case://foreign-repair-case"],
        patch_objective="Prepare a governed skill candidate input.",
        metadata={"requires_harness_skill_evolution": True},
    )
    bundle = {
        "input_bindings": _model_bindings(
            reader_repair_context_pack=context_pack,
            reader_repair_case=case,
        ),
        "strategies": [strategy.to_dict()],
        "skill_candidate_seeds": [seed.to_dict()],
    }

    evaluated = build_reader_repair_gate_registry().resolve(
        "ReaderRepairStrategyBoundaryGate@1"
    ).gate.evaluate(
        _context(
            {"strategy_candidate_bundle": bundle},
            prior={
                "reader_repair_context_pack": context_pack.to_dict(),
                "reader_repair_case": case.to_dict(),
            },
        )
    )

    assert evaluated.passed is False
    assert evaluated.details["violations"]["invalid_strategy_ids"] == [
        strategy.strategy_id
    ]


def test_result_success_must_equal_deterministic_gate_conjunction() -> None:
    issue = _issue()
    candidate = _candidate()
    verification = ReaderRepairVerificationCandidate(
        candidate_id=candidate.candidate_id,
        observations=[
            {
                "check_id": "source-lineage",
                "finding": "The candidate remains source-scoped.",
                "evidence_refs": issue.source_refs,
            }
        ],
        source_refs=issue.source_refs,
        metadata={
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
            )
        },
    )
    attempt_id = stable_research_id(
        "repair_attempt",
        issue.issue_id,
        candidate.candidate_id,
    )
    result = ReaderRepairResult(
        result_id=stable_research_id("repair_result", attempt_id),
        attempt_id=attempt_id,
        successful=True,
        verification_results=[
            {"gate_name": "ReaderLocalizedPatchGate", "passed": False}
        ],
        payload_before_ref=issue.payload_ref,
        payload_after_ref="reader-payload://after",
        source_refs=issue.source_refs,
        metadata={
            "skill_promotion_triggered": False,
            "candidate_id": candidate.candidate_id,
            "repair_summary": candidate.repair_summary,
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
                repair_verification_candidate=verification,
            ),
        },
    )
    gate = build_reader_repair_gate_registry().resolve(
        "ReaderRepairResultGate@1"
    ).gate

    evaluated = gate.evaluate(
        _context(
            {"reader_repair_result": result.to_dict()},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_candidate": candidate.to_dict(),
                "repair_verification_candidate": verification.to_dict(),
            },
        )
    )

    assert evaluated.passed is False
    assert evaluated.details["violations"]["successful"] == (
        "must equal deterministic gate conjunction"
    )


def test_skill_candidate_bundle_cannot_publish_or_bypass_evolution() -> None:
    case = _case()
    context_pack = _context_pack(case.issue)
    strategy = _strategy(case.repair_case_id)
    seed = ReaderRepairSkillCandidateSeed(
        seed_id="repair-seed-1",
        strategy=strategy,
        experience_refs=[f"repair-case://{case.repair_case_id}"],
        patch_objective="Prepare governed reader-repair skill candidate input.",
        publishes_skill=False,
        metadata={"requires_harness_skill_evolution": True},
    )
    gate = build_reader_repair_gate_registry().resolve(
        "ReaderRepairStrategyBoundaryGate@1"
    ).gate
    valid = {
        "input_bindings": _model_bindings(
            reader_repair_context_pack=context_pack,
            reader_repair_case=case,
        ),
        "strategies": [strategy.to_dict()],
        "skill_candidate_seeds": [seed.to_dict()],
    }
    prior = {
        "reader_repair_context_pack": context_pack.to_dict(),
        "reader_repair_case": case.to_dict(),
    }

    accepted = gate.evaluate(
        _context({"strategy_candidate_bundle": valid}, prior=prior)
    )
    malicious_seed = seed.to_dict()
    malicious_seed["publishes_skill"] = True
    rejected = gate.evaluate(
        _context(
            {
                "strategy_candidate_bundle": {
                    "input_bindings": valid["input_bindings"],
                    "strategies": [strategy.to_dict()],
                    "skill_candidate_seeds": [malicious_seed],
                }
            },
            prior=prior,
        )
    )

    assert accepted.passed is True
    assert rejected.passed is False
    assert rejected.details["reason_code"] == (
        "reader_repair_gate_input_invalid"
    )


@pytest.mark.parametrize(
    ("mutation", "violation_key"),
    (
        ({"namespace": "research.private"}, "namespace"),
        ({"candidate_id": "memory-candidate-other"}, "candidate_id"),
        (
            {
                "metadata": {
                    "active_skill_mutation": False,
                    "input_bindings": {},
                }
            },
            "input_bindings",
        ),
        (
            {
                "content": {
                    "promote_skill": True,
                }
            },
            "skill_authority_fields",
        ),
    ),
)
def test_memory_candidate_rejects_namespace_and_skill_authority(
    mutation: dict[str, object],
    violation_key: str,
) -> None:
    case = _case()
    verified_bundle = _empty_strategy_bundle(case)
    candidate = _memory_candidate(case, verified_bundle).to_dict()
    if "content" in mutation:
        candidate["content"].update(mutation["content"])
    else:
        candidate.update(mutation)
    gate = build_reader_repair_gate_registry().resolve(
        "ReaderRepairMemoryPolicyGate@1"
    ).gate

    result = gate.evaluate(
        _context(
            {"memory_write_candidate": candidate},
            prior={
                "reader_repair_case": case.to_dict(),
                "strategy_candidate_bundle": verified_bundle,
            },
        )
    )

    assert result.passed is False
    assert violation_key in result.details["violations"]


def test_memory_candidate_accepts_verified_case_and_candidate_bundle() -> None:
    case = _case()
    verified_bundle = _empty_strategy_bundle(case)
    candidate = _memory_candidate(case, verified_bundle)
    gate = build_reader_repair_gate_registry().resolve(
        "ReaderRepairMemoryPolicyGate@1"
    ).gate
    result = gate.evaluate(
        _context(
            {"memory_write_candidate": candidate.to_dict()},
            prior={
                "reader_repair_case": case.to_dict(),
                "strategy_candidate_bundle": verified_bundle,
            },
        )
    )

    assert result.passed is True


def _context(
    output: dict[str, object],
    *,
    prior: dict[str, dict[str, object]] | None = None,
):
    outputs = {
        key: {key: value}
        for key, value in (prior or {}).items()
    }
    return SimpleNamespace(
        worker_result=SimpleNamespace(output=output),
        state=SimpleNamespace(metadata={"outputs": outputs}),
    )


def _issue() -> ReaderIssue:
    return ReaderIssue(
        issue_id="reader-issue-1",
        paper_id="paper-1",
        run_id="repair-run-1",
        issue_type="section_boundary_error",
        error_signature="section-boundary:paper-1",
        symptom="A section boundary is missing.",
        source_refs=["paper://paper-1/section-1"],
        payload_ref="reader-payload://paper-1",
    )


def _candidate(
    context_pack: ReaderRepairContextPack | None = None,
) -> ReaderRepairCandidate:
    metadata = (
        {}
        if context_pack is None
        else {
            "input_bindings": _model_bindings(
                reader_repair_context_pack=context_pack,
            )
        }
    )
    return ReaderRepairCandidate(
        candidate_id="repair-candidate-1",
        repair_summary="Restore the missing source-backed section boundary.",
        target_region_refs=["paper://paper-1/section-1"],
        patch_operations=[
            {"op": "replace_region", "path": "reader-payload://paper-1"}
        ],
        expected_effect="Reader navigation matches the source section.",
        risks=["section offsets may change"],
        confidence=0.8,
        metadata=metadata,
    )


def _verification(
    issue: ReaderIssue,
    candidate: ReaderRepairCandidate,
) -> ReaderRepairVerificationCandidate:
    return ReaderRepairVerificationCandidate(
        candidate_id=candidate.candidate_id,
        observations=[
            {
                "check_id": "source-lineage",
                "finding": "The candidate remains source-scoped.",
                "evidence_refs": issue.source_refs,
            }
        ],
        source_refs=issue.source_refs,
        metadata={
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
            )
        },
    )


def _verified_result(
    issue: ReaderIssue,
    candidate: ReaderRepairCandidate,
    verification: ReaderRepairVerificationCandidate,
) -> ReaderRepairResult:
    attempt_id = stable_research_id(
        "repair_attempt",
        issue.issue_id,
        candidate.candidate_id,
    )
    return ReaderRepairResult(
        result_id=stable_research_id("repair_result", attempt_id),
        attempt_id=attempt_id,
        successful=True,
        verification_results=[
            {"gate_name": "ReaderLocalizedPatchGate", "passed": True}
        ],
        payload_before_ref=issue.payload_ref,
        payload_after_ref="reader-payload://paper-1/repaired",
        source_refs=issue.source_refs,
        metadata={
            "skill_promotion_triggered": False,
            "candidate_id": candidate.candidate_id,
            "repair_summary": candidate.repair_summary,
            "input_bindings": _model_bindings(
                reader_issue=issue,
                reader_repair_candidate=candidate,
                repair_verification_candidate=verification,
            ),
        },
    )


def _verified_case(
    context_pack: ReaderRepairContextPack,
    result: ReaderRepairResult,
    candidate: ReaderRepairCandidate,
) -> ReaderRepairCase:
    return ReaderRepairCase(
        repair_case_id=stable_research_id(
            "repair_case",
            context_pack.issue.issue_id,
            result.attempt_id,
        ),
        issue=context_pack.issue,
        repair_strategy=candidate.repair_summary,
        repair_attempt_refs=[result.attempt_id],
        successful=result.successful,
        verification_results=result.verification_results,
        payload_before_ref=result.payload_before_ref,
        payload_after_ref=result.payload_after_ref,
        source_refs=result.source_refs,
        constraints=context_pack.repair_constraints,
        metadata={
            "active_skill_mutation": False,
            "input_bindings": _model_bindings(
                reader_repair_context_pack=context_pack,
                reader_repair_result=result,
            ),
        },
    )


def _context_pack(issue: ReaderIssue) -> ReaderRepairContextPack:
    return ReaderRepairContextPack(
        context_id="repair-context-1",
        issue=issue,
        source_refs=issue.source_refs,
        source_lineage=SourceLineage(source_refs=issue.source_refs),
        failure_case_gap_report={"no_failed_cases_available": True},
    )


def _case() -> ReaderRepairCase:
    issue = _issue()
    return ReaderRepairCase(
        repair_case_id="repair-case-1",
        issue=issue,
        repair_strategy="Restore the source-backed section boundary.",
        successful=True,
        verification_results=[
            {"gate_name": "ReaderRepairResultGate", "passed": True}
        ],
        payload_before_ref="reader-payload://paper-1",
        payload_after_ref="reader-payload://paper-1/repaired",
        source_refs=issue.source_refs,
        metadata={"active_skill_mutation": False},
    )


def _strategy(case_id: str = "repair-case-1") -> ReaderRepairStrategy:
    return ReaderRepairStrategy(
        strategy_id="repair-strategy-1",
        issue_type="section_boundary_error",
        applicability="Repeated source-backed section boundary failures.",
        steps=["match signature", "patch region", "verify source lineage"],
        constraints=["preserve source refs"],
        evidence_requirements=["verification_results"],
        confidence=0.9,
        source_case_refs=[case_id],
        status="promoted_memory",
    )


def _empty_strategy_bundle(case: ReaderRepairCase) -> dict[str, object]:
    context_pack = _context_pack(case.issue)
    return {
        "input_bindings": _model_bindings(
            reader_repair_context_pack=context_pack,
            reader_repair_case=case,
        ),
        "strategies": [],
        "skill_candidate_seeds": [],
    }


def _memory_candidate(
    case: ReaderRepairCase,
    strategy_bundle: dict[str, object],
) -> MemoryWriteCandidate:
    return MemoryWriteCandidate(
        candidate_id=stable_research_id(
            "repair_memory_write",
            case.repair_case_id,
        ),
        namespace="research.reader_repair",
        content={
            "repair_case": case.to_dict(),
            "strategy_candidate_bundle": strategy_bundle,
        },
        source_refs=tuple(case.source_refs),
        metadata={
            "active_skill_mutation": False,
            "input_bindings": {
                "reader_repair_case": checksum_for(case.to_dict()),
                "strategy_candidate_bundle": checksum_for(strategy_bundle),
            },
        },
    )


def _model_bindings(**values: BaseModel) -> dict[str, str]:
    return {
        key: checksum_for(value.model_dump(mode="json", exclude_none=True))
        for key, value in values.items()
    }
