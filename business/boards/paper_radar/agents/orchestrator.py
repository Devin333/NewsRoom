"""Orchestrator for the final paper radar multi-agent analysis chain."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session import AgentSessionEvent, AgentSessionQuery, AgentSharedWorkspace, SessionVisibility
from framework.memory.session import AgentSessionMemoryAdapter

from business.boards.paper_radar.agents.base import PaperAgent
from business.boards.paper_radar.agents.comparison_agent import PaperComparisonAgent
from business.boards.paper_radar.agents.contribution_agent import PaperContributionAgent
from business.boards.paper_radar.agents.evidence_verification_agent import PaperEvidenceVerificationAgent
from business.boards.paper_radar.agents.experiment_agent import PaperExperimentAgent
from business.boards.paper_radar.agents.memory_agent import PaperMemoryAgent
from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult, PaperAnalysisRequest, PaperAnalysisResult
from business.boards.paper_radar.agents.profile_composer_agent import PaperProfileComposerAgent
from business.boards.paper_radar.agents.quality_agent import PaperQualityAgent
from business.boards.paper_radar.agents.reproducibility_agent import PaperReproducibilityAgent
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_BENCHMARK_CLAIMS,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_METADATA,
    PAPER_ROLE_SELECTION_DECISION,
    PAPER_ROLE_SOURCE_ARTIFACTS,
)
from business.boards.paper_radar.agents.selection_agent import PaperSelectionAgent
from business.boards.paper_radar.agents.structure_agent import PaperStructureAgent
from business.boards.paper_radar.agents.taxonomy_agent import PaperTaxonomyAgent


ORCHESTRATOR_AGENT_ID = "paper-analysis-orchestrator"


class PaperAnalysisOrchestrator:
    """Coordinate the final paper sub-agent chain through a shared workspace."""

    def __init__(
        self,
        *,
        workspace: AgentSharedWorkspace,
        structure_agent: PaperAgent | None = None,
        selection_agent: PaperAgent | None = None,
        taxonomy_agent: PaperAgent | None = None,
        experiment_agent: PaperAgent | None = None,
        evidence_verification_agent: PaperAgent | None = None,
        contribution_agent: PaperAgent | None = None,
        quality_agent: PaperAgent | None = None,
        reproducibility_agent: PaperAgent | None = None,
        comparison_agent: PaperAgent | None = None,
        profile_composer_agent: PaperAgent | None = None,
        memory_agent: PaperAgent | None = None,
        memory_adapter: AgentSessionMemoryAdapter | None = None,
    ) -> None:
        self._workspace = workspace
        self._memory_adapter = memory_adapter or AgentSessionMemoryAdapter()
        self._structure_agent = structure_agent or PaperStructureAgent()
        self._selection_agent = selection_agent or PaperSelectionAgent()
        self._taxonomy_agent = taxonomy_agent or PaperTaxonomyAgent()
        self._experiment_agent = experiment_agent or PaperExperimentAgent()
        self._evidence_verification_agent = evidence_verification_agent or PaperEvidenceVerificationAgent()
        self._contribution_agent = contribution_agent or PaperContributionAgent()
        self._quality_agent = quality_agent or PaperQualityAgent()
        self._reproducibility_agent = reproducibility_agent or PaperReproducibilityAgent()
        self._comparison_agent = comparison_agent or PaperComparisonAgent(self._memory_adapter)
        self._profile_composer_agent = profile_composer_agent or PaperProfileComposerAgent()
        self._memory_agent = memory_agent or PaperMemoryAgent(self._memory_adapter)

    def analyze_paper(self, request: PaperAnalysisRequest) -> PaperAnalysisResult:
        """Run the final paper analysis workflow and return the final profile."""

        self._workspace.clear(request.session_id)
        self._workspace.create_session(request.session_ref)
        self._write_metadata(request)
        self._write_source_artifacts(request)

        errors: list[str] = []
        review_queue_items: list[Mapping[str, Any]] = []
        agent_outputs: dict[str, Any] = {}

        for agent in self._workflow_agents():
            result = self._run_agent(agent, request=request)
            errors.extend(result.errors)
            for warning in result.warnings:
                review_queue_items.append({"kind": "agent_warning", "agentId": result.agent_id, "role": result.role, "reason": warning})
            agent_outputs[result.role] = dict(result.output)
            self._write_result(request, result)
            if result.role == PAPER_ROLE_SELECTION_DECISION and result.output.get("decision") == "skip":
                break
            if result.role == PAPER_ROLE_BENCHMARK_CLAIMS:
                continue
            if result.role == PAPER_ROLE_FINAL_PROFILE:
                self._workspace.mark_final(session_id=request.session_id, item_id=self._latest_item_id(request.session_id, PAPER_ROLE_FINAL_PROFILE))

        final_profile = self._final_profile(request)
        low_confidence_items = tuple(item for item in _sequence(final_profile.get("lowConfidenceItems")) if isinstance(item, Mapping))
        review_queue_items.extend(item for item in _sequence(final_profile.get("reviewQueueItems")) if isinstance(item, Mapping))
        self._workspace.create_snapshot(session_id=request.session_id, run_id=request.run_id)
        self._workspace.close_session(session_id=request.session_id, status="completed", metadata={"paperId": request.paper_id})
        return PaperAnalysisResult(
            paper_id=request.paper_id,
            run_id=request.run_id,
            session_id=request.session_id,
            final_profile=final_profile,
            agent_outputs=agent_outputs,
            low_confidence_items=low_confidence_items,
            review_queue_items=tuple(review_queue_items),
            errors=tuple(errors),
        )

    def _workflow_agents(self) -> tuple[PaperAgent, ...]:
        return (
            self._structure_agent,
            self._selection_agent,
            self._taxonomy_agent,
            self._experiment_agent,
            self._evidence_verification_agent,
            self._contribution_agent,
            self._quality_agent,
            self._reproducibility_agent,
            self._comparison_agent,
            self._profile_composer_agent,
            self._memory_agent,
        )

    def _write_metadata(self, request: PaperAnalysisRequest) -> None:
        self._workspace.write(
            ref=request.session_ref,
            agent_id=ORCHESTRATOR_AGENT_ID,
            role=PAPER_ROLE_METADATA,
            content={
                "paperId": request.paper_id,
                "title": request.title,
                "abstract": request.abstract,
                "repoUrl": request.repo_url,
                "githubStars": request.github_stars,
                "sourceUrl": request.source_url,
                "publishedAt": request.published_at,
                "authors": list(request.authors),
                "tags": list(request.tags),
                "metadata": dict(request.metadata),
                "sectionCount": len(request.page_sections),
            },
            summary=f"Paper metadata for {request.title}",
            refs={"paper_id": request.paper_id, "run_id": request.run_id},
        )

    def _write_source_artifacts(self, request: PaperAnalysisRequest) -> None:
        content = {
            "pdfArtifactUri": request.pdf_artifact_uri,
            "fullTextDigest": _text_digest(request.full_text),
            "pageSectionCount": len(request.page_sections),
        }
        self._workspace.write(
            ref=request.session_ref,
            agent_id=ORCHESTRATOR_AGENT_ID,
            role=PAPER_ROLE_SOURCE_ARTIFACTS,
            content=content,
            summary="Source artifact references and text digests.",
            refs={"paper_id": request.paper_id, "run_id": request.run_id},
        )

    def _run_agent(self, agent: PaperAgent, *, request: PaperAnalysisRequest) -> PaperAgentResult:
        produced_role = str(getattr(agent, "produced_role", "paper_agent_result"))
        required_roles = tuple(str(role) for role in getattr(agent, "required_roles", ()))
        self._workspace.append_event(
            AgentSessionEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                event_type="agent.started",
                agent_id=agent.agent_id,
                role=produced_role,
            )
        )
        shared_items = self._workspace.query(
            AgentSessionQuery(
                session_id=request.session_id,
                roles=required_roles,
                statuses=(),
                visibility=tuple(SessionVisibility),
                include_private=True,
            ),
            reader_agent_id=ORCHESTRATOR_AGENT_ID,
        )
        try:
            result = agent.run(PaperAgentContext(request=request, shared_items=shared_items))
        except Exception as exc:  # pragma: no cover - exercised through fakes.
            result = PaperAgentResult(
                agent_id=getattr(agent, "agent_id", "unknown-paper-agent"),
                role=getattr(agent, "produced_role", "paper_agent_error"),
                output={"warning": str(exc)},
                summary=str(exc),
                confidence=0.0,
                errors=(str(exc),),
                warnings=("agent_failed",),
            )
            self._workspace.append_event(
                AgentSessionEvent(
                    session_id=request.session_id,
                    run_id=request.run_id,
                    event_type="agent.failed",
                    agent_id=result.agent_id,
                    role=result.role,
                    payload={"error": str(exc)},
                )
            )
            return result
        self._workspace.append_event(
            AgentSessionEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                event_type="agent.completed",
                agent_id=result.agent_id,
                role=result.role,
                payload={"confidence": result.confidence, "warnings": list(result.warnings)},
            )
        )
        return result

    def _write_result(self, request: PaperAnalysisRequest, result: PaperAgentResult) -> None:
        self._workspace.write(
            ref=request.session_ref,
            agent_id=result.agent_id,
            role=result.role,
            content=dict(result.output),
            summary=result.summary,
            confidence=result.confidence,
            visibility=result.visibility,
            refs={"paper_id": request.paper_id, "run_id": request.run_id},
            metadata={
                "errors": list(result.errors),
                "warnings": list(result.warnings),
                "evidenceRefs": [dict(ref) for ref in result.evidence_refs],
            },
        )
        if result.role == "paper_experiment_result":
            self._workspace.write(
                ref=request.session_ref,
                agent_id=result.agent_id,
                role=PAPER_ROLE_BENCHMARK_CLAIMS,
                content={"claims": list(_sequence(result.output.get("benchmarks")))},
                summary="Benchmark claims extracted from experiment results.",
                confidence=result.confidence,
                refs={"paper_id": request.paper_id, "run_id": request.run_id},
            )

    def _final_profile(self, request: PaperAnalysisRequest) -> Mapping[str, Any]:
        latest = self._workspace.latest(session_id=request.session_id, role=PAPER_ROLE_FINAL_PROFILE)
        if latest is not None and latest.content:
            return latest.content
        return {
            "taskRefs": [],
            "methodRefs": [],
            "benchmarks": [],
            "classification": {"agentSessionId": request.session_id, "confidence": 0.0},
            "aiSummary": {"summary": "Paper analysis did not produce a final profile."},
            "lowConfidenceItems": [{"kind": "agent_error", "reason": "missing_final_profile", "action": "manual_review"}],
            "reviewQueueItems": [{"kind": "agent_error", "reason": "missing_final_profile", "action": "manual_review"}],
            "confidence": 0.0,
        }

    def _latest_item_id(self, session_id: str, role: str) -> str:
        item = self._workspace.latest(session_id=session_id, role=role)
        return item.item_id if item is not None else ""


def _text_digest(text: str | None) -> Mapping[str, Any]:
    if not text:
        return {"available": False, "charCount": 0}
    return {"available": True, "charCount": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
