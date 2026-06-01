"""Final paper profile composer agent."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_QUALITY_RESULT,
    PAPER_ROLE_TAXONOMY_RESULT,
)


class PaperProfileComposerAgent:
    """Merge prior paper agent outputs into a PublicPaper-compatible profile."""

    agent_id = "paper-profile-composer-agent"

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        taxonomy = _latest_output(context.shared_items, PAPER_ROLE_TAXONOMY_RESULT)
        experiment = _latest_output(context.shared_items, PAPER_ROLE_EXPERIMENT_RESULT)
        quality = _latest_output(context.shared_items, PAPER_ROLE_QUALITY_RESULT)
        low_confidence_items = _low_confidence_items(context.shared_items, taxonomy, experiment, quality)
        confidence = _combined_confidence(taxonomy, experiment, quality)
        output = {
            "primaryTaskGroup": taxonomy.get("primaryTaskGroup"),
            "secondaryTaskGroups": list(_sequence(taxonomy.get("secondaryTaskGroups"))),
            "taskRefs": list(_sequence(taxonomy.get("taskRefs"))),
            "methodRefs": list(_sequence(taxonomy.get("methodRefs"))),
            "benchmarks": list(_sequence(experiment.get("benchmarks"))),
            "confidence": confidence,
            "evidenceSummary": taxonomy.get("evidenceSummary"),
            "classification": {
                "primaryTaskGroup": taxonomy.get("primaryTaskGroup"),
                "secondaryTaskGroups": list(_sequence(taxonomy.get("secondaryTaskGroups"))),
                "confidence": taxonomy.get("confidence"),
                "evidenceSummary": taxonomy.get("evidenceSummary"),
                "agentSessionId": context.request.session_id,
                "qualityScore": quality.get("qualityScore"),
                "evidenceStrength": quality.get("evidenceStrength"),
                "recommendation": quality.get("recommendation"),
            },
            "aiSummary": {
                "experimentSummary": experiment.get("experimentSummary"),
                "engineeringRelevance": _engineering_relevance(context.request.repo_url, quality),
                "limitations": list(_sequence(quality.get("weaknesses"))),
                "contributions": _contributions(context.request.title, context.request.abstract),
            },
            "lowConfidenceItems": low_confidence_items,
        }
        summary = f"Composed final profile with {len(output['taskRefs'])} task ref(s) and {len(output['benchmarks'])} benchmark(s)."
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_FINAL_PROFILE,
            output=output,
            summary=summary,
            confidence=confidence,
        )


def _latest_output(items: Sequence[AgentSessionItem], role: str) -> Mapping[str, Any]:
    for item in reversed(items):
        if item.role == role:
            return item.content
    return {}


def _combined_confidence(*outputs: Mapping[str, Any]) -> float:
    values = []
    for output in outputs:
        value = output.get("confidence")
        if isinstance(value, (int, float)):
            values.append(float(value))
        quality_score = output.get("qualityScore")
        if isinstance(quality_score, (int, float)):
            values.append(float(quality_score))
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _low_confidence_items(
    items: Sequence[AgentSessionItem],
    taxonomy: Mapping[str, Any],
    experiment: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    result = [item for item in _sequence(taxonomy.get("lowConfidenceItems")) if isinstance(item, Mapping)]
    for warning in _sequence(experiment.get("metricWarnings")):
        result.append({"kind": "benchmark", "reason": str(warning), "action": "manual_review"})
    if quality.get("evidenceStrength") == "low":
        result.append({"kind": "quality", "reason": "low_evidence_strength", "action": "manual_review"})
    for item in items:
        if item.confidence is not None and item.confidence < 0.6:
            result.append(
                {
                    "kind": "agent_output",
                    "agentId": item.agent_id,
                    "role": item.role,
                    "confidence": item.confidence,
                    "reason": "low_agent_confidence",
                    "action": "manual_review",
                }
            )
        errors = item.metadata.get("errors") if isinstance(item.metadata, Mapping) else None
        for error in _sequence(errors):
            result.append({"kind": "agent_error", "agentId": item.agent_id, "role": item.role, "reason": str(error), "action": "manual_review"})
    return result


def _engineering_relevance(repo_url: str | None, quality: Mapping[str, Any]) -> str:
    recommendation = str(quality.get("recommendation") or "manual_review")
    repo_text = "Repository evidence is available" if repo_url else "Repository evidence is not available"
    return f"{repo_text}; recommendation is {recommendation}."


def _contributions(title: str, abstract: str) -> list[str]:
    text = " ".join(abstract.split())
    if text:
        return [text[:240]]
    return [title] if title else []


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
