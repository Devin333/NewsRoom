from __future__ import annotations

from collections import defaultdict

from business.research.domain import stable_research_id
from business.research.domain.reader_repair import ReaderRepairCase, ReaderRepairSkillCandidateSeed, ReaderRepairStrategy


class ReaderRepairConsolidator:
    def consolidate(
        self,
        cases: list[ReaderRepairCase],
        *,
        min_cases: int = 2,
        min_success_rate: float = 0.75,
    ) -> list[ReaderRepairStrategy]:
        grouped: dict[tuple[str, str], list[ReaderRepairCase]] = defaultdict(list)
        for case in cases:
            grouped[(case.issue.issue_type, case.issue.error_signature)].append(case)
        strategies: list[ReaderRepairStrategy] = []
        for (issue_type, signature), group in grouped.items():
            if len(group) < min_cases:
                continue
            successes = [case for case in group if case.successful]
            success_rate = len(successes) / len(group)
            if success_rate < min_success_rate:
                continue
            failed = [case for case in group if not case.successful]
            strategies.append(
                ReaderRepairStrategy(
                    strategy_id=stable_research_id("reader_repair_strategy", issue_type, signature),
                    issue_type=issue_type,
                    applicability=f"Repeated reader repair issue matching {signature}.",
                    steps=_common_steps(successes),
                    constraints=["preserve source refs", "verify reader schema", "keep failed strategy boundaries"],
                    known_failures=[case.failure_reason or case.repair_strategy for case in failed],
                    evidence_requirements=["source_refs", "verification_results", "payload refs"],
                    confidence=round(success_rate, 4),
                    source_case_refs=[case.repair_case_id for case in group],
                    status="promoted_memory",
                    metadata={"success_rate": success_rate, "case_count": len(group)},
                )
            )
        return strategies

    def skill_candidate_seed(self, strategy: ReaderRepairStrategy) -> ReaderRepairSkillCandidateSeed | None:
        if strategy.status not in {"promoted_memory", "skill_candidate_ready"}:
            return None
        return ReaderRepairSkillCandidateSeed(
            seed_id=stable_research_id("reader_repair_skill_seed", strategy.strategy_id),
            strategy=strategy,
            experience_refs=[f"repair-case://{case_ref}" for case_ref in strategy.source_case_refs],
            patch_objective=f"Use procedural repair memory {strategy.strategy_id} as input to governed skill evolution.",
            publishes_skill=False,
            metadata={"requires_harness_skill_evolution": True},
        )


def _common_steps(cases: list[ReaderRepairCase]) -> list[str]:
    for case in cases:
        steps = case.metadata.get("strategy_steps")
        if isinstance(steps, list) and steps:
            return [str(step) for step in steps]
    return ["match issue signature", "apply localized reader payload patch", "verify schema and source lineage"]


__all__ = ["ReaderRepairConsolidator"]
