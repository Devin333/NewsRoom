"""Orchestrator for paper radar multi-agent analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session import AgentSharedWorkspace

from business.boards.paper_radar.agents.base import PaperAgent
from business.boards.paper_radar.agents.experiment_agent import PaperExperimentAgent
from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult, PaperAnalysisRequest, PaperAnalysisResult
from business.boards.paper_radar.agents.profile_composer_agent import PaperProfileComposerAgent
from business.boards.paper_radar.agents.quality_agent import PaperQualityAgent
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_METADATA,
    PAPER_ROLE_QUALITY_RESULT,
    PAPER_ROLE_TAXONOMY_RESULT,
)
from business.boards.paper_radar.agents.taxonomy_agent import PaperTaxonomyAgent


ORCHESTRATOR_AGENT_ID = "paper-analysis-orchestrator"


class PaperAnalysisOrchestrator:
    """Coordinate paper sub-agents through a framework shared workspace."""

    def __init__(
        self,
        *,
        workspace: AgentSharedWorkspace,
        taxonomy_agent: PaperAgent | None = None,
        experiment_agent: PaperAgent | None = None,
        quality_agent: PaperAgent | None = None,
        profile_composer_agent: PaperAgent | None = None,
    ) -> None:
        self._workspace = workspace
        self._taxonomy_agent = taxonomy_agent or PaperTaxonomyAgent()
        self._experiment_agent = experiment_agent or PaperExperimentAgent()
        self._quality_agent = quality_agent or PaperQualityAgent()
        self._profile_composer_agent = profile_composer_agent or PaperProfileComposerAgent()

    def analyze_paper(self, request: PaperAnalysisRequest) -> PaperAnalysisResult:
        """Run the paper analysis pipeline and return the final profile."""

        session_id = request.session_id
        self._workspace.clear(session_id)
        self._write_metadata(request)
        errors: list[str] = []
        agent_outputs: dict[str, Any] = {}

        taxonomy = self._run_agent(
            self._taxonomy_agent,
            request=request,
            roles=[PAPER_ROLE_METADATA],
            fallback_role=PAPER_ROLE_TAXONOMY_RESULT,
        )
        errors.extend(taxonomy.errors)
        agent_outputs[taxonomy.role] = dict(taxonomy.output)
        self._write_result(request, taxonomy)

        experiment = self._run_agent(
            self._experiment_agent,
            request=request,
            roles=[PAPER_ROLE_METADATA, PAPER_ROLE_TAXONOMY_RESULT],
            fallback_role=PAPER_ROLE_EXPERIMENT_RESULT,
        )
        errors.extend(experiment.errors)
        agent_outputs[experiment.role] = dict(experiment.output)
        self._write_result(request, experiment)

        quality = self._run_agent(
            self._quality_agent,
            request=request,
            roles=[PAPER_ROLE_TAXONOMY_RESULT, PAPER_ROLE_EXPERIMENT_RESULT],
            fallback_role=PAPER_ROLE_QUALITY_RESULT,
        )
        errors.extend(quality.errors)
        agent_outputs[quality.role] = dict(quality.output)
        self._write_result(request, quality)

        profile = self._run_agent(
            self._profile_composer_agent,
            request=request,
            roles=[PAPER_ROLE_TAXONOMY_RESULT, PAPER_ROLE_EXPERIMENT_RESULT, PAPER_ROLE_QUALITY_RESULT],
            fallback_role=PAPER_ROLE_FINAL_PROFILE,
        )
        errors.extend(profile.errors)
        final_profile = dict(profile.output) if profile.output else _degraded_profile(self._workspace.read(session_id=session_id), request)
        agent_outputs[profile.role] = final_profile
        self._write_result(request, PaperAgentResult(**{**profile.__dict__, "output": final_profile}))

        low_confidence_items = tuple(item for item in _sequence(final_profile.get("lowConfidenceItems")) if isinstance(item, Mapping))
        return PaperAnalysisResult(
            paper_id=request.paper_id,
            run_id=request.run_id,
            session_id=session_id,
            final_profile=final_profile,
            agent_outputs=agent_outputs,
            low_confidence_items=low_confidence_items,
            errors=tuple(errors),
        )

    def _write_metadata(self, request: PaperAnalysisRequest) -> None:
        self._workspace.write(
            session_id=request.session_id,
            agent_id=ORCHESTRATOR_AGENT_ID,
            role=PAPER_ROLE_METADATA,
            content={
                "paperId": request.paper_id,
                "title": request.title,
                "abstract": request.abstract,
                "repoUrl": request.repo_url,
                "githubStars": request.github_stars,
                "metadata": dict(request.metadata),
                "sectionCount": len(request.page_sections),
            },
            summary=f"Paper metadata for {request.title}",
            refs={"paper_id": request.paper_id, "run_id": request.run_id},
        )

    def _run_agent(
        self,
        agent: PaperAgent,
        *,
        request: PaperAnalysisRequest,
        roles: Sequence[str],
        fallback_role: str,
    ) -> PaperAgentResult:
        shared_items = self._workspace.read(session_id=request.session_id, roles=roles)
        try:
            return agent.run(PaperAgentContext(request=request, shared_items=shared_items))
        except Exception as exc:  # pragma: no cover - exercised by test fakes.
            return PaperAgentResult(
                agent_id=getattr(agent, "agent_id", "unknown-paper-agent"),
                role=fallback_role,
                output={},
                summary=str(exc),
                confidence=0.0,
                errors=(str(exc),),
            )

    def _write_result(self, request: PaperAnalysisRequest, result: PaperAgentResult) -> None:
        self._workspace.write(
            session_id=request.session_id,
            agent_id=result.agent_id,
            role=result.role,
            content=dict(result.output),
            summary=result.summary,
            confidence=result.confidence,
            refs={"paper_id": request.paper_id, "run_id": request.run_id},
            metadata={"errors": list(result.errors), "evidenceRefs": [dict(ref) for ref in result.evidence_refs]},
        )


def _degraded_profile(items: Sequence[Any], request: PaperAnalysisRequest) -> Mapping[str, Any]:
    taxonomy = _latest_output(items, PAPER_ROLE_TAXONOMY_RESULT)
    experiment = _latest_output(items, PAPER_ROLE_EXPERIMENT_RESULT)
    return {
        "primaryTaskGroup": taxonomy.get("primaryTaskGroup"),
        "secondaryTaskGroups": list(_sequence(taxonomy.get("secondaryTaskGroups"))),
        "taskRefs": list(_sequence(taxonomy.get("taskRefs"))),
        "methodRefs": list(_sequence(taxonomy.get("methodRefs"))),
        "benchmarks": list(_sequence(experiment.get("benchmarks"))),
        "classification": {
            "primaryTaskGroup": taxonomy.get("primaryTaskGroup"),
            "secondaryTaskGroups": list(_sequence(taxonomy.get("secondaryTaskGroups"))),
            "confidence": taxonomy.get("confidence"),
            "evidenceSummary": taxonomy.get("evidenceSummary"),
            "agentSessionId": request.session_id,
            "qualityScore": None,
        },
        "aiSummary": {
            "experimentSummary": experiment.get("experimentSummary"),
            "engineeringRelevance": "Generated from partial paper agent outputs.",
            "limitations": ["One or more paper agents failed."],
            "contributions": [],
        },
        "lowConfidenceItems": [{"kind": "agent_error", "reason": "degraded_profile", "action": "manual_review"}],
        "confidence": 0.0,
        "evidenceSummary": taxonomy.get("evidenceSummary"),
    }


def _latest_output(items: Sequence[Any], role: str) -> Mapping[str, Any]:
    for item in reversed(items):
        if getattr(item, "role", None) == role:
            return item.content
    return {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
