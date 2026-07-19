from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from framework.artifacts.paths import validate_artifact_path_segment
from framework.harness import (
    ArtifactPort,
    ArtifactRef,
    ArtifactWriteRequest,
    ContextAssembler,
    ContextBudget,
    ContextEnvelope,
    ContextSnapshot,
    HarnessBudget,
    HarnessControlPlane,
    HarnessEvent,
    HarnessTransitionPort,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessTrace,
    HarnessTranscript,
    HarnessWorkerResult,
    HarnessWorkerStatus,
    RAGBudget,
    RAGContextPack,
    SkillExperience,
    SkillExperienceOutcome,
    transcript_entry_from_event,
)
from framework.shared.json import to_jsonable

from business.research.benchmark.models import ResearchScore
from business.research.domain import (
    EvidenceRef,
    GateResult,
    PaperSourceRecord,
    ReaderIssue,
    ResearchAnalysis,
    ResearchClaim,
    ResearchDocument,
    ResearchEvidencePack,
    ResearchPaper,
    ResearchQualityResult,
    ResearchReaderPayload,
    ThreeMinuteRead,
    stable_research_id,
)
from business.research.paper_card import PaperCardBuilder, ResearchPaperCard
from business.research.rag import ResearchRAGContext, ResearchRetrievalGoal
from business.research.reader import ReaderPayloadBuilder
from business.research.services import (
    CitationVerifier,
    ReaderIssueDetector,
    ResearchEvidenceBuilder,
    ResearchQualityGate,
    ResearchRAGPolicyBuilder,
)
from business.research.taxonomy import TaxonomyAssignment, TaxonomyAssignmentBuilder, TaxonomyCandidate, TaxonomyRegistry
from business.research.workflows import (
    build_paper_analysis_gate_registry,
    build_paper_analysis_workflow_spec,
)


@dataclass(frozen=True)
class AnalyzePaperRequest:
    run_id: str
    paper_id: str
    source_ref: str
    user_id: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchAnalysisResult:
    run_id: str
    status: str
    analysis: ResearchAnalysis | None
    quality: ResearchQualityResult
    paper_card: ResearchPaperCard | None
    reader_payload: ResearchReaderPayload | None
    rag_context: ResearchRAGContext | None
    reader_issue: ReaderIssue | None
    artifact_refs: dict[str, str]
    trace: HarnessTrace
    transcript: HarnessTranscript
    context_snapshot: ContextSnapshot | None
    context_envelope: ContextEnvelope | None
    compression_records: list[dict[str, Any]]
    skill_experience_refs: list[str]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == HarnessRunStatus.SUCCEEDED.value and self.analysis is not None

    @property
    def reader_payload_ref(self) -> str | None:
        return self.artifact_refs.get("research-reader-payload")

    @property
    def trace_ref(self) -> str:
        return f"harness-trace://{self.run_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "quality": self.quality.to_dict(),
            "paper_card": self.paper_card.to_dict() if self.paper_card else None,
            "reader_payload": self.reader_payload.to_dict() if self.reader_payload else None,
            "rag_context": self.rag_context.to_dict() if self.rag_context else None,
            "reader_issue": self.reader_issue.to_dict() if self.reader_issue else None,
            "artifact_refs": dict(self.artifact_refs),
            "trace": self.trace.to_dict(),
            "transcript": self.transcript.to_dict(),
            "context_snapshot": self.context_snapshot.to_dict() if self.context_snapshot else None,
            "context_envelope": self.context_envelope.to_dict() if self.context_envelope else None,
            "compression_records": to_jsonable(self.compression_records),
            "skill_experience_refs": list(self.skill_experience_refs),
            "diagnostics": to_jsonable(self.diagnostics),
            "trace_ref": self.trace_ref,
            "reader_payload_ref": self.reader_payload_ref,
        }


class ResearchSinglePaperRuntime:
    def __init__(
        self,
        *,
        source_provider: Any,
        document_compiler: Any,
        llm_worker: Any,
        github_repository: Any,
        rag_runtime: Any,
        artifact_port: ArtifactPort,
        event_port_factory: Callable[[str], HarnessTransitionPort],
        taxonomy_registry: TaxonomyRegistry | None = None,
        context_assembler: ContextAssembler | None = None,
        quality_gate: ResearchQualityGate | None = None,
    ) -> None:
        self.source_provider = source_provider
        self.document_compiler = document_compiler
        self.llm_worker = llm_worker
        self.github_repository = github_repository
        self.rag_runtime = rag_runtime
        self.artifact_port = artifact_port
        if not callable(event_port_factory):
            raise TypeError("event_port_factory must be callable")
        self.event_port_factory = event_port_factory
        self.taxonomy_registry = taxonomy_registry or TaxonomyRegistry.default()
        self.context_assembler = context_assembler or ContextAssembler()
        self.quality_gate = quality_gate or ResearchQualityGate()
        self.evidence_builder = ResearchEvidenceBuilder()
        self.reader_builder = ReaderPayloadBuilder()
        self.paper_card_builder = PaperCardBuilder()
        self.reader_issue_detector = ReaderIssueDetector()
        self.rag_policy_builder = ResearchRAGPolicyBuilder()
        self.citation_verifier = CitationVerifier()
        self.gate_registry = build_paper_analysis_gate_registry()

    def run(self, request: AnalyzePaperRequest) -> ResearchAnalysisResult:
        run_id = validate_artifact_path_segment(request.run_id, field="run_id")
        workspace = _ResearchRunWorkspace(request=request)
        event_port = self.event_port_factory(run_id)
        if not isinstance(event_port, HarnessTransitionPort):
            raise TypeError("event_port_factory must return HarnessTransitionPort")
        workflow = build_paper_analysis_workflow_spec()
        run_spec = HarnessRunSpec(
            run_id=run_id,
            workflow=workflow,
            inputs={"paper_id": request.paper_id, "source_ref": request.source_ref},
            budget=_budget_from_options(request.options),
            metadata={"research_runtime": "single_paper", "paper_id": request.paper_id},
        )
        control_plane = HarnessControlPlane(
            event_port=event_port,
            worker_registry=self._worker_registry(workspace),
            gate_registry=self.gate_registry,
        )
        harness_result = control_plane.run(run_spec)
        trace = HarnessTrace(
            run_id=run_id,
            events=harness_result.events,
            metadata={"paper_id": request.paper_id},
        )
        transcript = _transcript_from_events(run_id, harness_result.events)
        artifacts = dict(workspace.artifact_refs)
        if harness_result.state.status == HarnessRunStatus.SUCCEEDED and trace.events:
            artifacts["harness-trace"] = self._write_artifact(
                "harness-trace",
                trace.to_dict(),
                metadata={"run_id": run_id},
            ).ref
            artifacts["harness-transcript"] = self._write_artifact(
                "harness-transcript",
                transcript.to_dict(),
                metadata={"run_id": run_id},
            ).ref
        quality = workspace.quality or ResearchQualityResult(
            result_id=stable_research_id("quality", run_id, "halted"),
            target_id=request.paper_id,
            target_type="summary",
            passed=False,
            score=0.0,
            gate_results=[GateResult.fail("ResearchBudgetGate", "run halted before quality result was produced")],
        )
        diagnostics = {
            "harness_status": harness_result.state.status.value,
            "terminal_reason": harness_result.state.metadata.get("terminal_reason"),
            "worker_results": {key: value.to_dict() for key, value in harness_result.worker_results.items()},
            "gate_failures": _gate_failures(harness_result.events),
            "research_diagnostics": list(workspace.diagnostics),
        }
        return ResearchAnalysisResult(
            run_id=run_id,
            status=harness_result.state.status.value,
            analysis=workspace.analysis,
            quality=quality,
            paper_card=workspace.paper_card,
            reader_payload=workspace.reader_payload,
            rag_context=workspace.research_rag_context,
            reader_issue=workspace.reader_issue,
            artifact_refs=artifacts,
            trace=trace,
            transcript=transcript,
            context_snapshot=workspace.context_snapshot,
            context_envelope=workspace.context_envelope,
            compression_records=list(workspace.compression_records),
            skill_experience_refs=list(workspace.skill_experience_refs),
            diagnostics=diagnostics,
        )

    def _worker_registry(self, workspace: "_ResearchRunWorkspace") -> dict[str, Any]:
        return {
            "load_paper_source": lambda task: self._load_paper_source(task, workspace),
            "compile_document": lambda task: self._compile_document(task, workspace),
            "run_research_rag": lambda task: self._run_research_rag(task, workspace),
            "build_evidence_pack": lambda task: self._build_evidence_pack(task, workspace),
            "analyze_structure": lambda task: self._analyze_structure(task, workspace),
            "analyze_contribution": lambda task: self._analyze_contribution(task, workspace),
            "analyze_experiments": lambda task: self._analyze_experiments(task, workspace),
            "verify_claims": lambda task: self._verify_claims(task, workspace),
            "quality_gate": lambda task: self._quality_gate(task, workspace),
            "build_reader_payload": lambda task: self._build_reader_payload(task, workspace),
            "build_paper_card": lambda task: self._build_paper_card(task, workspace),
            "publish_artifacts": lambda task: self._publish_artifacts(task, workspace),
        }

    def _load_paper_source(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        paper = self.source_provider.fetch_paper(workspace.request.source_ref)
        source_record = self.source_provider.fetch_source_record(paper.paper_id)
        workspace.paper = paper
        workspace.source_record = source_record
        return _ok(
            {
                "paper": paper.to_dict(),
                "source_record": source_record.to_dict(),
                "source_refs": [workspace.request.source_ref],
            }
        )

    def _compile_document(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.paper is None or workspace.source_record is None:
            return _failed("paper source must be loaded before compile_document")
        document = self.document_compiler.compile(workspace.source_record)
        workspace.document = document
        return _ok({"document": document.to_dict(), "source_refs": document.lineage.source_refs})

    def _run_research_rag(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.paper is None or workspace.document is None:
            return _failed("paper and document are required before RAG")
        goal = ResearchRetrievalGoal(
            goal_id=stable_research_id("research_goal", workspace.request.run_id, workspace.paper.paper_id),
            paper_id=workspace.paper.paper_id,
            question="Build evidence for method, experiment, limitation, and claim support.",
            required_evidence_types=["method", "experiment", "limitation", "claim_support"],
            target_sections=[section.section_id for section in workspace.document.sections],
            allowed_source_refs=[
                source_ref for section in workspace.document.sections for source_ref in [section.source_ref]
            ]
            or list(workspace.document.lineage.source_refs),
            allowed_memory_namespaces=[f"research:user:{workspace.request.user_id or 'anonymous'}"],
            constraints={"paper_only": True},
        )
        session_spec = self.rag_policy_builder.build_session_spec(
            run_id=workspace.request.run_id,
            workflow_id="research.paper_analysis",
            step_id="run_research_rag",
            session_id=stable_research_id("research_rag", workspace.request.run_id, workspace.paper.paper_id),
            goal=goal,
            budget=_rag_budget_from_options(workspace.request.options),
        )
        rag_context = self.rag_runtime.run(session_spec=session_spec, document=workspace.document)
        workspace.rag_context_pack = getattr(self.rag_runtime, "last_context_pack", None)
        workspace.research_rag_context = rag_context
        output = {
            "research_rag_context": rag_context.to_dict(),
            "source_refs": rag_context.source_refs,
            "rag_budget": session_spec.budget.to_dict(),
        }
        if rag_context.gap_report.missing_information:
            output["rag_gap_report"] = rag_context.gap_report.to_dict()
        return _ok(output)

    def _build_evidence_pack(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.document is None:
            return _failed("document is required before evidence pack")
        pack = self.evidence_builder.build_from_document(document=workspace.document)
        if workspace.research_rag_context is not None:
            existing = {item.evidence_id for item in pack.items}
            merged = list(pack.items)
            for item in workspace.research_rag_context.accepted_evidence:
                if item.evidence_id not in existing:
                    merged.append(item)
                    existing.add(item.evidence_id)
            pack = ResearchEvidencePack(
                pack_id=pack.pack_id,
                paper_id=pack.paper_id,
                items=merged,
                coverage={
                    **pack.coverage,
                    "rag_required_evidence": 0.0
                    if workspace.research_rag_context.gap_report.missing_information
                    else 1.0,
                },
                missing_information=workspace.research_rag_context.gap_report.missing_information,
                lineage=pack.lineage,
            )
        workspace.evidence_pack = pack
        return _ok({"evidence_pack": pack.to_dict(), "source_refs": pack.lineage.source_refs})

    def _analyze_structure(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        candidate = self.llm_worker.generate_candidate(
            task="candidate_three_minute_read",
            payload={
                "paper": workspace.paper.to_dict() if workspace.paper else {},
                "evidence_pack": workspace.evidence_pack.to_dict() if workspace.evidence_pack else {},
            },
        )
        workspace.llm_candidate_warnings.extend(_forbidden_candidate_keys(candidate))
        summary_payload = dict(candidate.get("three_minute_read", {}))
        evidence_by_id = {
            item.evidence_id: item
            for item in (workspace.evidence_pack.items if workspace.evidence_pack else ())
        }
        evidence_refs: list[EvidenceRef] = []
        for item in summary_payload.get("evidence_refs", []):
            evidence_ref = EvidenceRef(**item) if isinstance(item, dict) else item
            canonical_evidence = evidence_by_id.get(evidence_ref.evidence_id)
            if canonical_evidence is not None and evidence_ref.source_ref != canonical_evidence.source_ref:
                evidence_ref = evidence_ref.model_copy(
                    update={
                        "source_ref": canonical_evidence.source_ref,
                        "metadata": {
                            **evidence_ref.metadata,
                            "candidate_source_ref": evidence_ref.source_ref,
                            "source_ref_normalized": True,
                        },
                    }
                )
            evidence_refs.append(evidence_ref)
        summary = ThreeMinuteRead(
            problem=str(summary_payload.get("problem") or ""),
            core_idea=str(summary_payload.get("core_idea") or ""),
            key_contributions=[str(item) for item in summary_payload.get("key_contributions", [])],
            method_summary=str(summary_payload.get("method_summary") or ""),
            experiment_summary=str(summary_payload.get("experiment_summary") or ""),
            limitations=[str(item) for item in summary_payload.get("limitations", [])],
            why_it_matters=str(summary_payload.get("why_it_matters") or ""),
            read_next=[str(item) for item in summary_payload.get("read_next", [])],
            evidence_refs=evidence_refs,
            confidence=float(summary_payload.get("confidence", 0.0) or 0.0),
        )
        workspace.summary = summary
        return _ok(
            {
                "candidate_ref": stable_research_id("candidate", workspace.request.run_id, "summary"),
                "three_minute_read": summary.to_dict(),
                "claims": [summary.core_idea],
                "warnings": list(workspace.llm_candidate_warnings),
            }
        )

    def _analyze_contribution(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.summary is None:
            return _failed("summary candidate is required before contribution analysis")
        workspace.contributions = list(workspace.summary.key_contributions)
        workspace.taxonomy_candidates = [
            TaxonomyCandidate(
                candidate_id=stable_research_id("taxonomy_candidate", workspace.request.run_id, item["level"], item["term_id"]),
                level=item["level"],
                term_id=item["term_id"],
                label=item["label"],
                evidence_refs=item["evidence_refs"],
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in self.llm_worker.generate_candidate(
                task="candidate_taxonomy",
                payload={
                    "paper": workspace.paper.to_dict() if workspace.paper else {},
                    "evidence_pack": (
                        workspace.evidence_pack.to_dict()
                        if workspace.evidence_pack
                        else {}
                    ),
                },
            ).get("taxonomy_candidates", [])
        ]
        assignment = TaxonomyAssignmentBuilder(self.taxonomy_registry).build(workspace.request.paper_id, workspace.taxonomy_candidates)
        workspace.taxonomy_assignment = assignment
        return _ok(
            {
                "contributions": list(workspace.contributions),
                "taxonomy_assignment": assignment.to_dict(),
                "taxonomy_review_candidate_ids": assignment.review_candidate_ids,
                "summary_evidence_refs": [
                    evidence_ref.to_dict() for evidence_ref in workspace.summary.evidence_refs
                ],
            }
        )

    def _analyze_experiments(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        candidate = self.llm_worker.generate_candidate(
            task="candidate_experiment_claims",
            payload={"evidence_pack": workspace.evidence_pack.to_dict() if workspace.evidence_pack else {}},
        )
        claims: list[ResearchClaim] = []
        scores: list[ResearchScore] = []
        candidate_scores: list[dict[str, Any]] = []
        for item in candidate.get("claims", []):
            claims.append(
                ResearchClaim(
                    claim_id=str(item.get("claim_id")),
                    text=str(item.get("text")),
                    claim_type=str(item.get("claim_type", "experiment")),
                    section_id=item.get("section_id"),
                    evidence_ids=[str(ref) for ref in item.get("evidence_ids", [])],
                    confidence=float(item.get("confidence", 0.0)),
                )
            )
        for item in candidate.get("scores", []):
            candidate_source_refs = [str(ref) for ref in item.get("source_refs", [])]
            canonical_source_refs = _canonicalize_evidence_source_refs(
                candidate_source_refs,
                workspace.evidence_pack,
            )
            candidate_score = {
                "score_id": str(item.get("score_id")),
                "paper_id": workspace.request.paper_id,
                "benchmark_id": str(item.get("benchmark_id")),
                "dataset_id": str(item.get("dataset_id")),
                "metric_id": str(item.get("metric_id")),
                "value": float(item.get("value")),
                "source_refs": canonical_source_refs,
            }
            if canonical_source_refs != candidate_source_refs:
                candidate_score["metadata"] = {
                    "candidate_source_refs": candidate_source_refs,
                    "source_refs_normalized": True,
                }
            candidate_scores.append(candidate_score)
            if _score_candidate_is_in_supported_range(candidate_score):
                scores.append(ResearchScore(**candidate_score))
        workspace.candidate_scores = candidate_scores
        if len(scores) != len(candidate_scores):
            workspace.score_gate_results.append(
                GateResult.fail(
                    "ResearchScoreRangeGate",
                    "candidate benchmark score is outside supported range",
                    metadata={
                        "violations": {
                            str(item.get("score_id", "score")): item.get("value")
                            for item in candidate_scores
                            if not _score_candidate_is_in_supported_range(item)
                        }
                    },
                )
            )
        workspace.claims = claims
        workspace.scores = scores
        return _ok(
            {
                "claims": [claim.text for claim in claims],
                "claim_models": [claim.to_dict() for claim in claims],
                "scores": candidate_scores,
                "claim_confidence_observation": min([claim.confidence for claim in claims] or [1.0]),
            }
        )

    def _verify_claims(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.evidence_pack is None:
            return _failed("evidence pack is required before claim verification")
        gate_results = self.citation_verifier.verify_claims(workspace.claims, workspace.evidence_pack)
        workspace.claim_gate_results = gate_results
        return _ok(
            {
                "claim_gate_results": [result.to_dict() for result in gate_results],
                "claim_models": [claim.to_dict() for claim in workspace.claims],
                "evidence_pack": workspace.evidence_pack.to_dict(),
            }
        )

    def _quality_gate(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.paper is None or workspace.summary is None or workspace.evidence_pack is None:
            return _failed("paper, summary, and evidence are required before quality gate")
        analysis = ResearchAnalysis(
            paper_id=workspace.paper.paper_id,
            summary=workspace.summary,
            contributions=workspace.contributions,
            methods=[candidate.term_id for candidate in workspace.taxonomy_candidates if candidate.level == "area"],
            experiments=[claim.text for claim in workspace.claims if claim.claim_type == "experiment"],
            limitations=workspace.summary.limitations,
            reproducibility=[],
            related_work=[],
            claims=workspace.claims,
            evidence_pack_id=workspace.evidence_pack.pack_id,
            quality={"llm_candidate_warnings": list(workspace.llm_candidate_warnings)},
        )
        gate_results = [*workspace.claim_gate_results, *workspace.score_gate_results]
        if not analysis.summary.evidence_refs:
            gate_results.append(GateResult.fail("ResearchEvidenceCoverageGate", "analysis summary requires evidence refs"))
        if not analysis.claims:
            gate_results.append(GateResult.fail("ResearchReportReadinessGate", "analysis requires claims"))
        if workspace.research_rag_context and workspace.research_rag_context.gap_report.missing_information:
            gate_results.append(GateResult.fail("ResearchRAGEvidenceNeedGate", "required RAG evidence is missing"))
        quality = self.quality_gate.evaluate(target_id=workspace.paper.paper_id, target_type="summary", gate_results=gate_results)
        workspace.analysis = analysis
        workspace.quality = quality
        return _ok(
            {
                "analysis": analysis.to_dict(),
                "research_quality": quality.to_dict(),
                "gate_failures": [flag.to_dict() for flag in quality.quality_flags],
            }
        )

    def _build_reader_payload(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.paper is None or workspace.document is None:
            return _failed("paper and document are required before reader payload")
        reader_payload = self.reader_builder.build(
            paper=workspace.paper,
            document=workspace.document,
            analysis=workspace.analysis,
            evidence=workspace.evidence_pack,
        )
        issues = self.reader_issue_detector.detect(reader_payload)
        workspace.reader_payload = reader_payload
        workspace.reader_issue = issues[0] if issues else None
        return _ok(
            {
                "reader_payload": reader_payload.to_dict(),
                "reader_issue": workspace.reader_issue.to_dict() if workspace.reader_issue else None,
            }
        )

    def _build_paper_card(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.paper is None:
            return _failed("paper is required before paper card")
        github_profile = None
        repository_status = "missing"
        repository_diagnostics: list[str] = []
        if workspace.paper.code_url:
            github_profile = self.github_repository.fetch_profile(workspace.paper.code_url)
            repository_status = "available"
        else:
            repository_diagnostics.append("code_repository_missing")
            if "code_repository_missing" not in workspace.diagnostics:
                workspace.diagnostics.append("code_repository_missing")
        taxonomy = workspace.taxonomy_assignment or TaxonomyAssignment(paper_id=workspace.paper.paper_id)
        card = self.paper_card_builder.build(
            paper=workspace.paper,
            three_minute_read=workspace.summary,
            taxonomy={
                "domains": taxonomy.domains,
                "areas": taxonomy.areas,
                "tasks": taxonomy.tasks,
                "methods": [candidate.term_id for candidate in workspace.taxonomy_candidates if candidate.level == "area"],
                "benchmarks": [score.benchmark_id for score in workspace.scores],
            },
            github=github_profile.to_dict() if github_profile is not None else None,
            reader_payload_status="needs_repair" if workspace.reader_issue else ("ready" if workspace.reader_payload else "missing"),
            metadata={
                "source_lineage": [workspace.request.source_ref],
                "code_repository_status": repository_status,
                "code_repository_diagnostics": repository_diagnostics,
            },
        )
        workspace.paper_card = card
        return _ok(
            {
                "paper_card": card.to_dict(),
                "code_repository_status": repository_status,
                "code_repository_diagnostics": repository_diagnostics,
            }
        )

    def _publish_artifacts(self, task: dict[str, Any], workspace: "_ResearchRunWorkspace") -> HarnessWorkerResult:
        if workspace.analysis:
            workspace.artifact_refs["research-analysis"] = self._write_artifact("research-analysis", workspace.analysis.to_dict()).ref
        if workspace.reader_payload:
            workspace.artifact_refs["research-reader-payload"] = self._write_artifact("research-reader-payload", workspace.reader_payload.to_dict()).ref
        if workspace.paper_card:
            workspace.artifact_refs["research-paper-card"] = self._write_artifact("research-paper-card", workspace.paper_card.to_dict()).ref
        if workspace.quality:
            workspace.artifact_refs["research-quality-result"] = self._write_artifact("research-quality-result", workspace.quality.to_dict()).ref
        if workspace.research_rag_context:
            workspace.artifact_refs["research-rag-context-pack"] = self._write_artifact("research-rag-context-pack", workspace.research_rag_context.to_dict()).ref
        if workspace.reader_issue:
            workspace.artifact_refs["reader-issue"] = self._write_artifact("reader-issue", workspace.reader_issue.to_dict()).ref
        workspace.context_envelope = self._assemble_context(workspace)
        workspace.context_snapshot = self.context_assembler.snapshot_store.load(workspace.context_envelope.snapshot_ref or "")
        workspace.compression_records = _research_ordered_compression_records(
            [
                event["payload"]
                for event in self.context_assembler.events
                if event.get("event_type") == "context_compression_recorded"
            ]
        )
        workspace.artifact_refs["research-context-snapshot"] = self._write_artifact(
            "research-context-snapshot",
            workspace.context_snapshot.to_dict(),
        ).ref
        workspace.artifact_refs["research-context-compression-records"] = self._write_artifact(
            "research-context-compression-records",
            {"records": list(workspace.compression_records)},
        ).ref
        if workspace.research_rag_context and workspace.research_rag_context.gap_report.missing_information:
            workspace.artifact_refs["research-rag-gap-report"] = self._write_artifact(
                "research-rag-gap-report",
                workspace.research_rag_context.gap_report.to_dict(),
            ).ref
        skill_experience = self._record_skill_experience(workspace)
        workspace.skill_experience_refs.append(skill_experience.experience_id)
        return _ok({"artifact_refs": dict(workspace.artifact_refs), "skill_experience_refs": list(workspace.skill_experience_refs)})

    def _assemble_context(self, workspace: "_ResearchRunWorkspace") -> ContextEnvelope:
        source_refs = []
        if workspace.research_rag_context:
            source_refs = list(workspace.research_rag_context.source_refs)
        return self.context_assembler.assemble(
            {
                "run_id": workspace.request.run_id,
                "workflow_id": "research.paper_analysis",
                "step_id": "publish_artifacts",
                "phase": "verify",
                "worker_id": "research-analysis-worker",
                "worker_type": "subagent",
                "workflow_ref": "workflow://research.paper_analysis",
                "worker_contract_ref": "schema://research.analysis.output",
                "run_state_ref": f"run-state://{workspace.request.run_id}",
                "evidence_memory_ref": workspace.research_rag_context.context_id if workspace.research_rag_context else "evidence-memory://empty",
                "current_task_ref": "task://publish_artifacts",
                "current_instruction": "Publish verified Research artifacts only after deterministic gates pass.",
                "source_refs": source_refs,
                "artifact_refs": tuple(workspace.artifact_refs.values()),
                "evidence_refs": tuple(workspace.evidence_pack.evidence_ids if workspace.evidence_pack else ()),
                "allowed_tools": ("retrieval.search", "retrieval.read_source"),
                "allowed_memory_namespaces": (f"research:user:{workspace.request.user_id or 'anonymous'}",),
                "budget": ContextBudget(
                    max_input_tokens=int(workspace.request.options.get("context_max_input_tokens", 4096)),
                    max_output_tokens=1024,
                    max_context_segments=6,
                    max_evidence_items=8,
                    max_memory_items=6,
                    max_artifact_refs=24,
                    reserved_output_tokens=512,
                    compression_threshold=0.8,
                ),
                "evidence_memory_tokens": int(workspace.request.options.get("evidence_memory_tokens", 120)),
                "metadata": {
                    "paper_id": workspace.request.paper_id,
                    "stable_prefix_excludes": ["full_paper_text", "github_metrics", "user_notes", "dynamic_rag_results"],
                },
            }
        )

    def _record_skill_experience(self, workspace: "_ResearchRunWorkspace") -> SkillExperience:
        research_quality_score = workspace.quality.score if workspace.quality else 0.0
        return SkillExperience(
            experience_id=stable_research_id("skill_experience", workspace.request.run_id, workspace.request.paper_id),
            run_id=workspace.request.run_id,
            step_id="quality_gate",
            skill_name="research-contribution-analysis",
            skill_version="1.0.0",
            domain="research",
            task_type="paper_analysis",
            input_refs=[workspace.request.source_ref],
            output_refs=list(workspace.artifact_refs.values()),
            transcript_refs=[f"harness-transcript://{workspace.request.run_id}"],
            gate_results=[result.to_dict() for result in workspace.claim_gate_results],
            score=research_quality_score,
            outcome=(
                SkillExperienceOutcome.SUCCESS
                if research_quality_score >= 0.8
                else SkillExperienceOutcome.FAILURE
            ),
            evidence_refs=workspace.evidence_pack.evidence_ids if workspace.evidence_pack else (),
            source="research_single_paper_run",
            summary="Single-paper Research analysis experience recorded for offline skill evolution.",
            metadata={"skill_promotion_triggered": False, "package_hash": "sha256:fake-research-skill"},
        )

    def _write_artifact(
        self,
        artifact_type: str,
        payload: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        return self.artifact_port.write_artifact(
            ArtifactWriteRequest(artifact_type=artifact_type, payload=payload, metadata=metadata or {})
        )


@dataclass
class _ResearchRunWorkspace:
    request: AnalyzePaperRequest
    paper: ResearchPaper | None = None
    source_record: PaperSourceRecord | None = None
    document: ResearchDocument | None = None
    evidence_pack: ResearchEvidencePack | None = None
    rag_context_pack: RAGContextPack | None = None
    research_rag_context: ResearchRAGContext | None = None
    summary: ThreeMinuteRead | None = None
    contributions: list[str] = field(default_factory=list)
    claims: list[ResearchClaim] = field(default_factory=list)
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    scores: list[ResearchScore] = field(default_factory=list)
    taxonomy_candidates: list[TaxonomyCandidate] = field(default_factory=list)
    taxonomy_assignment: TaxonomyAssignment | None = None
    analysis: ResearchAnalysis | None = None
    quality: ResearchQualityResult | None = None
    reader_payload: ResearchReaderPayload | None = None
    paper_card: ResearchPaperCard | None = None
    reader_issue: ReaderIssue | None = None
    claim_gate_results: list[GateResult] = field(default_factory=list)
    score_gate_results: list[GateResult] = field(default_factory=list)
    llm_candidate_warnings: list[str] = field(default_factory=list)
    artifact_refs: dict[str, str] = field(default_factory=dict)
    context_snapshot: ContextSnapshot | None = None
    context_envelope: ContextEnvelope | None = None
    compression_records: list[dict[str, Any]] = field(default_factory=list)
    skill_experience_refs: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _budget_from_options(options: dict[str, Any]) -> HarnessBudget:
    return HarnessBudget(
        max_turns=min(int(options.get("max_turns", 40)), 64),
        max_replans=min(int(options.get("max_replans", 3)), 6),
        max_retries_per_step=min(int(options.get("max_retries_per_step", 2)), 4),
        max_worker_calls=min(int(options.get("max_worker_calls", 32)), 64),
    )


def _rag_budget_from_options(options: dict[str, Any]) -> RAGBudget:
    return RAGBudget(
        max_rounds=min(int(options.get("rag_max_rounds", 6)), 8),
        max_replans=1,
        max_queries=min(int(options.get("rag_max_queries", 12)), 16),
        max_source_reads=min(int(options.get("rag_max_source_reads", 24)), 32),
        max_memory_hits=min(int(options.get("rag_max_memory_hits", 8)), 12),
        max_context_items=8,
        max_context_tokens=4096,
        max_worker_calls=16,
    )


def _ok(output: dict[str, Any]) -> HarnessWorkerResult:
    return HarnessWorkerResult(status=HarnessWorkerStatus.SUCCEEDED, output=output)


def _failed(error: str) -> HarnessWorkerResult:
    return HarnessWorkerResult(status=HarnessWorkerStatus.FAILED, error=error)


def _forbidden_candidate_keys(candidate: dict[str, Any]) -> list[str]:
    forbidden = {"next_step", "route", "quality_passed", "write_memory", "publish_artifact", "promote_skill"}
    return sorted(forbidden.intersection(candidate))


def _score_candidate_is_in_supported_range(candidate: dict[str, Any]) -> bool:
    value = candidate.get("value")
    refs = candidate.get("source_refs")
    return isinstance(value, int | float) and -1_000_000_000 <= value <= 1_000_000_000 and bool(refs)


def _canonicalize_evidence_source_refs(
    source_refs: list[str],
    evidence_pack: ResearchEvidencePack | None,
) -> list[str]:
    if evidence_pack is None:
        return source_refs
    allowed = {
        ref
        for item in evidence_pack.items
        for ref in (item.source_ref, *item.lineage.source_refs)
    }
    normalized: list[str] = []
    for source_ref in source_refs:
        if source_ref in allowed:
            normalized.append(source_ref)
            continue
        matches = {
            item.source_ref
            for item in evidence_pack.items
            if any(
                source_ref == span_ref
                or source_ref.endswith(f"/{span_ref}")
                or source_ref.endswith(f"#{span_ref}")
                for span_ref in item.span_refs
            )
        }
        normalized.append(next(iter(matches)) if len(matches) == 1 else source_ref)
    return list(dict.fromkeys(normalized))


def _research_ordered_compression_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: (
            0 if any(str(ref).startswith("paper://") for ref in record.get("preserved_refs", ())) else 1,
            str(record.get("compression_id", "")),
        ),
    )


def _transcript_from_events(run_id: str, events: list[HarnessEvent]) -> HarnessTranscript:
    transcript = HarnessTranscript(run_id)
    for index, event in enumerate(events):
        transcript.append(transcript_entry_from_event(event, phase_index=index))
    return transcript


def _gate_failures(events: list[HarnessEvent]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for event in events:
        payload = event.to_dict().get("payload", {})
        if isinstance(payload, dict) and payload.get("passed") is False:
            failures.append(payload)
    return failures


__all__ = [
    "AnalyzePaperRequest",
    "ResearchAnalysisResult",
    "ResearchSinglePaperRuntime",
]
