from __future__ import annotations

from collections import Counter

from business.boards.cross_board.models import TechnologyJourney
from business.foundation import (
    BoardType,
    BusinessQualityCheck,
    BusinessRegressionGuardResult,
    Relation,
    RelationType,
    build_stable_id,
)

ORDERED_STAGE_TYPES = (
    "research_origin",
    "project_implementation",
    "community_discussion",
    "product_adoption",
)

_RELATION_STAGE_MAP = {
    RelationType.PROPOSES: "research_origin",
    RelationType.IMPLEMENTS: "project_implementation",
    RelationType.DISCUSSES: "community_discussion",
    RelationType.ADOPTS: "product_adoption",
}

_RELATION_BOARD_MAP = {
    RelationType.PROPOSES: BoardType.PAPER_RADAR,
    RelationType.IMPLEMENTS: BoardType.PROJECT_RADAR,
    RelationType.DISCUSSES: BoardType.COMMUNITY_PULSE,
    RelationType.ADOPTS: BoardType.AI_NEWS,
}


def guard_cross_board_insight(
    *,
    evidence_count: int,
    board_support_count: int,
    confidence: float,
    duplicate_evidence_count: int = 0,
    contradictory_evidence_count: int = 0,
    missing_stage_count: int = 0,
) -> BusinessRegressionGuardResult:
    checks = [
        BusinessQualityCheck.create(
            "cross_board_has_evidence",
            passed=evidence_count > 0,
            severity="block",
            reason="Cross-board insight must have evidence relations.",
            observed={"evidence_count": evidence_count},
        ),
        BusinessQualityCheck.create(
            "cross_board_has_multi_board_support",
            passed=board_support_count >= 2,
            severity="block",
            reason="Cross-board insight must have at least two board supports.",
            observed={"board_support_count": board_support_count},
        ),
        BusinessQualityCheck.create(
            "cross_board_confidence_threshold",
            passed=confidence >= 0.65,
            severity="warning",
            reason="Weak relation chain cannot produce strong insight.",
            observed={"confidence": confidence},
        ),
        BusinessQualityCheck.create(
            "cross_board_no_duplicate_evidence",
            passed=duplicate_evidence_count == 0,
            severity="warning",
            reason="Duplicate evidence should not overstate a cross-board chain.",
            observed={"duplicate_evidence_count": duplicate_evidence_count},
        ),
        BusinessQualityCheck.create(
            "cross_board_no_contradictory_evidence",
            passed=contradictory_evidence_count == 0,
            severity="block",
            reason="Contradictory evidence blocks a strong cross-board insight.",
            observed={"contradictory_evidence_count": contradictory_evidence_count},
        ),
        BusinessQualityCheck.create(
            "cross_board_chain_has_required_stages",
            passed=missing_stage_count == 0,
            severity="block",
            reason="Strong cross-board insight requires an ordered journey chain.",
            observed={"missing_stage_count": missing_stage_count},
        ),
    ]
    blocking = [check.reason for check in checks if not check.passed and check.severity == "block"]
    passed = not blocking
    return BusinessRegressionGuardResult(
        guard_id=build_stable_id(
            "cross_guard",
            evidence_count,
            board_support_count,
            confidence,
            duplicate_evidence_count,
            contradictory_evidence_count,
            missing_stage_count,
        ),
        status="pass" if passed else "block",
        passed=passed,
        checks=checks,
        blocking_reasons=blocking,
        warnings=[check.reason for check in checks if not check.passed and check.severity == "warning"],
        metadata={
            "evidence_count": evidence_count,
            "board_support_count": board_support_count,
            "confidence": confidence,
            "duplicate_evidence_count": duplicate_evidence_count,
            "contradictory_evidence_count": contradictory_evidence_count,
            "missing_stage_count": missing_stage_count,
        },
    )


def guard_technology_journey(journey: TechnologyJourney, relations: list[Relation]) -> BusinessRegressionGuardResult:
    stage_types = [stage.stage_type for stage in journey.stages]
    relation_ids = [relation_id for stage in journey.stages for relation_id in stage.evidence_relation_ids]
    duplicate_count = _duplicate_count(relation_ids)
    contradictory_count = _contradictory_count(relations)
    missing_stage_count = _missing_stage_count(stage_types)
    confidence = _chain_confidence(relations)
    return guard_cross_board_insight(
        evidence_count=len(set(relation_ids)),
        board_support_count=len(set(stage_types)),
        confidence=confidence,
        duplicate_evidence_count=duplicate_count,
        contradictory_evidence_count=contradictory_count,
        missing_stage_count=missing_stage_count,
    )


def guard_cross_board_path(path) -> BusinessRegressionGuardResult:
    chain = path.evidence_chain
    evidence_count = chain.evidence_count if chain is not None else len(path.evidence_relation_ids)
    board_support_count = chain.board_support_count if chain is not None else len(set(path.board_sequence))
    confidence = path.confidence
    duplicate_evidence_count = path.duplicate_evidence_count
    contradictory_evidence_count = path.contradictory_evidence_count
    missing_stage_count = len(path.missing_stage_types)
    result = guard_cross_board_insight(
        evidence_count=evidence_count,
        board_support_count=board_support_count,
        confidence=confidence,
        duplicate_evidence_count=duplicate_evidence_count,
        contradictory_evidence_count=contradictory_evidence_count,
        missing_stage_count=missing_stage_count,
    )
    extra_checks = [
        BusinessQualityCheck.create(
            "cross_board_path_not_weak",
            passed=path.path_score >= 0.55,
            severity="warning",
            reason="Weak cross-board path should not produce a strong insight.",
            observed={"path_score": path.path_score},
        )
    ]
    checks = [*result.checks, *extra_checks]
    blocking = [check.reason for check in checks if not check.passed and check.severity == "block"]
    warnings = [check.reason for check in checks if not check.passed and check.severity == "warning"]
    passed = not blocking
    return result.model_copy(
        update={
            "guard_id": build_stable_id("cross_path_guard", path.path_id, [(check.check_type, check.passed) for check in checks]),
            "status": "pass" if passed else "block",
            "passed": passed,
            "checks": checks,
            "blocking_reasons": blocking,
            "warnings": warnings,
            "metadata": {**dict(result.metadata), "path_id": path.path_id, "path_score": path.path_score},
        }
    )


def ordered_stage_types(stage_types: list[str]) -> list[str]:
    order = {stage_type: index for index, stage_type in enumerate(ORDERED_STAGE_TYPES)}
    return sorted(stage_types, key=lambda stage_type: order.get(stage_type, len(order)))


def stage_for_relation_type(relation_type: RelationType | str) -> str | None:
    try:
        key = relation_type if isinstance(relation_type, RelationType) else RelationType(str(relation_type))
    except ValueError:
        return None
    return _RELATION_STAGE_MAP.get(key)


def board_for_stage_relation(relation_type: RelationType | str) -> BoardType | None:
    try:
        key = relation_type if isinstance(relation_type, RelationType) else RelationType(str(relation_type))
    except ValueError:
        return None
    return _RELATION_BOARD_MAP.get(key)


def _duplicate_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _contradictory_count(relations: list[Relation]) -> int:
    by_target: dict[str, set[str]] = {}
    for relation in relations:
        by_target.setdefault(relation.target_ref.object_id, set()).add(relation.relation_type.value)
    contradictory_pairs = 0
    for relation_types in by_target.values():
        if {"supports", "criticizes"} <= relation_types:
            contradictory_pairs += 1
    return contradictory_pairs


def _missing_stage_count(stage_types: list[str]) -> int:
    if not stage_types:
        return len(ORDERED_STAGE_TYPES)
    highest = max(ORDERED_STAGE_TYPES.index(stage_type) for stage_type in stage_types if stage_type in ORDERED_STAGE_TYPES)
    required = set(ORDERED_STAGE_TYPES[: highest + 1])
    return len(required - set(stage_types))


def _chain_confidence(relations: list[Relation]) -> float:
    if not relations:
        return 0.0
    return round(min(relation.confidence.value for relation in relations), 4)
