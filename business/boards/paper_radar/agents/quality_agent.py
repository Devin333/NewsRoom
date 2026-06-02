"""Quality assessment agent for paper radar analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_EVIDENCE_VERIFICATION,
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_QUALITY_RESULT,
    PAPER_ROLE_TAXONOMY_RESULT,
)


class PaperQualityAgent:
    """Score experiment evidence strength, risks, and publication readiness."""

    agent_id = "paper-quality-agent"
    required_roles = (PAPER_ROLE_TAXONOMY_RESULT, PAPER_ROLE_EXPERIMENT_RESULT, PAPER_ROLE_EVIDENCE_VERIFICATION)
    produced_role = PAPER_ROLE_QUALITY_RESULT

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        taxonomy = _latest_output(context.shared_items, PAPER_ROLE_TAXONOMY_RESULT)
        experiment = _latest_output(context.shared_items, PAPER_ROLE_EXPERIMENT_RESULT)
        verification = _latest_output(context.shared_items, PAPER_ROLE_EVIDENCE_VERIFICATION)
        benchmarks = [item for item in _sequence(experiment.get("benchmarks")) if isinstance(item, Mapping)]
        weak_claims = [item for item in _sequence(verification.get("weakClaims")) if isinstance(item, Mapping)]
        rejected_claims = [item for item in _sequence(verification.get("rejectedClaims")) if isinstance(item, Mapping)]
        has_experiment_section = _has_section(context.request.page_sections, ("experiment", "evaluation", "result"))
        has_benchmark = bool(benchmarks)
        has_metric_value = any(item.get("value") not in (None, "", [], {}) for item in benchmarks)
        has_baseline = any(item.get("baseline") for item in benchmarks)
        has_evidence = bool(taxonomy.get("evidenceSummary") or any(item.get("evidence") for item in benchmarks))
        has_ablation_or_limitation = _has_section(context.request.page_sections, ("ablation", "limitation", "discussion"))
        claims_without_results = _claims_without_results(context.request.abstract, has_metric_value)
        score = _quality_score(
            has_experiment_section=has_experiment_section,
            has_benchmark=has_benchmark,
            has_metric_value=has_metric_value,
            has_baseline=has_baseline,
            has_repo=bool(context.request.repo_url),
            has_ablation_or_limitation=has_ablation_or_limitation,
            has_evidence=has_evidence,
            claims_without_results=claims_without_results,
            unverified_claim_count=len(weak_claims) + len(rejected_claims),
        )
        output = {
            "qualityScore": score,
            "evidenceStrength": _evidence_strength(score),
            "strengths": _strengths(
                has_experiment_section=has_experiment_section,
                has_benchmark=has_benchmark,
                has_metric_value=has_metric_value,
                has_baseline=has_baseline,
                has_repo=bool(context.request.repo_url),
                has_ablation_or_limitation=has_ablation_or_limitation,
            ),
            "weaknesses": _weaknesses(
                has_benchmark=has_benchmark,
                has_baseline=has_baseline,
                has_evidence=has_evidence,
                claims_without_results=claims_without_results,
                unverified_claim_count=len(weak_claims) + len(rejected_claims),
            ),
            "riskFlags": _risk_flags(
                has_benchmark=has_benchmark,
                has_baseline=has_baseline,
                claims_without_results=claims_without_results,
                unverified_claim_count=len(weak_claims) + len(rejected_claims),
            ),
            "recommendation": _recommendation(score),
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_QUALITY_RESULT,
            output=output,
            summary=f"Quality score {score:.2f} with {_evidence_strength(score)} evidence.",
            confidence=score,
        )


def _quality_score(
    *,
    has_experiment_section: bool,
    has_benchmark: bool,
    has_metric_value: bool,
    has_baseline: bool,
    has_repo: bool,
    has_ablation_or_limitation: bool,
    has_evidence: bool,
    claims_without_results: bool,
    unverified_claim_count: int = 0,
) -> float:
    score = 0.5
    for flag in (has_experiment_section, has_benchmark, has_metric_value, has_baseline, has_repo, has_ablation_or_limitation):
        if flag:
            score += 0.1
    if not has_benchmark:
        score -= 0.1
    if not has_baseline:
        score -= 0.1
    if not has_evidence:
        score -= 0.1
    if claims_without_results:
        score -= 0.1
    if unverified_claim_count:
        score -= min(0.25, unverified_claim_count * 0.08)
    return round(max(0.0, min(1.0, score)), 2)


def _latest_output(items: Sequence[AgentSessionItem], role: str) -> Mapping[str, Any]:
    for item in reversed(items):
        if item.role == role:
            return item.content
    return {}


def _has_section(page_sections: Sequence[Mapping[str, Any]], terms: Sequence[str]) -> bool:
    for section in page_sections:
        text = f"{section.get('title') or ''} {section.get('sectionType') or ''} {section.get('textExcerpt') or ''}".casefold()
        if any(term in text for term in terms):
            return True
    return False


def _claims_without_results(abstract: str, has_metric_value: bool) -> bool:
    text = abstract.casefold()
    return not has_metric_value and any(term in text for term in ("state-of-the-art", "outperform", "superior", "significant improvement"))


def _evidence_strength(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _recommendation(score: float) -> str:
    if score >= 0.75:
        return "publish"
    if score >= 0.55:
        return "manual_review"
    return "caution"


def _strengths(
    *,
    has_experiment_section: bool,
    has_benchmark: bool,
    has_metric_value: bool,
    has_baseline: bool,
    has_repo: bool,
    has_ablation_or_limitation: bool,
) -> list[str]:
    values = []
    if has_experiment_section:
        values.append("Experiment or evaluation section is present.")
    if has_benchmark:
        values.append("Benchmark evidence was extracted.")
    if has_metric_value:
        values.append("At least one metric value is reported.")
    if has_baseline:
        values.append("A baseline or comparison is mentioned.")
    if has_repo:
        values.append("A repository URL is available.")
    if has_ablation_or_limitation:
        values.append("Ablation, limitation, or discussion evidence is present.")
    return values


def _weaknesses(*, has_benchmark: bool, has_baseline: bool, has_evidence: bool, claims_without_results: bool, unverified_claim_count: int = 0) -> list[str]:
    values = []
    if not has_benchmark:
        values.append("No benchmark result was extracted.")
    if not has_baseline:
        values.append("No clear baseline comparison was extracted.")
    if not has_evidence:
        values.append("Evidence is sparse.")
    if claims_without_results:
        values.append("The paper makes strong claims without extracted metric evidence.")
    if unverified_claim_count:
        values.append(f"{unverified_claim_count} benchmark claim(s) have weak or rejected evidence.")
    return values


def _risk_flags(*, has_benchmark: bool, has_baseline: bool, claims_without_results: bool, unverified_claim_count: int = 0) -> list[str]:
    flags = []
    if not has_benchmark:
        flags.append("missing_benchmark")
    if not has_baseline:
        flags.append("missing_baseline")
    if claims_without_results:
        flags.append("claims_without_results")
    if unverified_claim_count:
        flags.append("unverified_benchmark_claim")
    return flags


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
