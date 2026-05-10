from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.framework import RunResult, WorkflowRunner
from core.framework.llm import LLMRequest, OpenAICompatibleClient, OpenAICompatibleConfig
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import FunctionStepRegistry, ScopedDataBuffer
from domain.reports import BlockedReport, FinalReport, render_markdown
from domain.sources import SourceDefinition, SourceError, SourcePipelineMetrics
from evidence import EvidenceBuilder, EvidenceBundle
from quality import CitationChecker, EditorDecision, EditorGate
from sources import SourceRegistry
from sources.connectors import FeedConnector
from sources.health import BasicSourceHealthManager
from sources.processing import deduplicate_items, normalize_items, rank_items

PROFILE_LIVE = "live"
PROFILE_LIVE_OFFLINE = "live-offline"
WORKFLOW_ID = "daily-intelligence-live"
WORKFLOW_VERSION = "0.1.0"


class DailyIntelligenceRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        source_registry: SourceRegistry | None = None,
        feed_connector: FeedConnector | None = None,
        llm_client: OpenAICompatibleClient | None = None,
        source_health_manager: BasicSourceHealthManager | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.source_registry = source_registry or build_default_source_registry()
        self.feed_connector = feed_connector or FeedConnector()
        self.llm_client = llm_client
        self.source_health_manager = source_health_manager or BasicSourceHealthManager()

    def run(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int = 3,
        run_id: str | None = None,
    ) -> RunResult:
        if profile not in {PROFILE_LIVE, PROFILE_LIVE_OFFLINE}:
            raise ValueError(f"unsupported daily intelligence profile: {profile}")
        registry = self._function_registry(profile)
        runner = WorkflowRunner(artifact_root=self.artifact_root, function_registry=registry)
        return runner.run(
            build_daily_intelligence_workflow(profile),
            {"topic": topic, "source_limit": source_limit, "profile": profile},
            profile=profile,
            run_id=run_id,
        )

    def _function_registry(self, profile: str) -> FunctionStepRegistry:
        registry = FunctionStepRegistry()
        registry.register("daily.collect_sources", lambda buffer: self._collect_sources(buffer, profile))
        registry.register("daily.normalize_sources", _normalize_sources)
        registry.register("daily.deduplicate_sources", _deduplicate_sources)
        registry.register("daily.rank_sources", _rank_sources)
        registry.register("daily.build_evidence", _build_evidence)
        registry.register("daily.draft_report", lambda buffer: self._draft_report(buffer, profile))
        registry.register("daily.quality_gate", _quality_gate)
        return registry

    def _collect_sources(self, buffer: ScopedDataBuffer, profile: str) -> dict[str, Any]:
        request = buffer.read("request")
        limit = int(request.get("source_limit", 3))
        source_errors: list[SourceError] = []
        skipped_sources: list[dict[str, Any]] = []
        failed_sources: list[dict[str, Any]] = []
        source_health_updates = []
        metrics = SourcePipelineMetrics()
        if profile == PROFILE_LIVE_OFFLINE:
            raw_items = FeedConnector().parse(_fixture_source(), _fixture_feed(), limit=limit)
            metrics.sources_total = 1
            metrics.sources_fetched = 1
            metrics.raw_items_count = len(raw_items)
            metrics.items_by_source = {"fixture-ai": len(raw_items)}
            source_health_updates.append(self.source_health_manager.record_success("fixture-ai"))
            return {
                "raw_items": raw_items,
                "source_errors": source_errors,
                "skipped_sources": skipped_sources,
                "failed_sources": failed_sources,
                "source_health_updates": source_health_updates,
                "source_pipeline_metrics": metrics,
            }

        raw_items = []
        enabled_sources = self.source_registry.list_sources()
        metrics.sources_total = len(enabled_sources)
        for source in enabled_sources:
            remaining = max(0, limit - len(raw_items))
            if remaining == 0:
                break
            if self.source_health_manager.should_skip(source.source_id):
                health = self.source_health_manager.get(source.source_id)
                skipped_sources.append(
                    {
                        "source_id": source.source_id,
                        "reason": "cooldown",
                        "cooldown_until": (
                            health.cooldown_until.isoformat().replace("+00:00", "Z")
                            if health.cooldown_until
                            else None
                        ),
                    }
                )
                source_health_updates.append(health)
                metrics.sources_skipped += 1
                continue
            items, errors = self.feed_connector.fetch(source, limit=remaining)
            raw_items.extend(items)
            if items:
                metrics.sources_fetched += 1
                metrics.items_by_source[source.source_id] = len(items)
                source_health_updates.append(self.source_health_manager.record_success(source.source_id))
            if errors:
                metrics.sources_failed += 1
                source_errors.extend(errors)
                failed_sources.extend(error.to_dict() for error in errors)
                for error in errors:
                    metrics.record_error(error)
                    source_health_updates.append(
                        self.source_health_manager.record_failure(source.source_id, error)
                    )
        metrics.raw_items_count = len(raw_items)
        if not raw_items:
            raise RuntimeError("no source items collected from enabled sources")
        return {
            "raw_items": raw_items,
            "source_errors": source_errors,
            "skipped_sources": skipped_sources,
            "failed_sources": failed_sources,
            "source_health_updates": source_health_updates,
            "source_pipeline_metrics": metrics,
        }

    def _draft_report(self, buffer: ScopedDataBuffer, profile: str) -> dict[str, Any]:
        request = buffer.read("request")
        evidence_bundle = buffer.read("evidence_bundle")
        if profile == PROFILE_LIVE_OFFLINE:
            return {"report_draft": _deterministic_report(request["topic"], evidence_bundle)}

        llm_client = self.llm_client or OpenAICompatibleClient(OpenAICompatibleConfig.dashscope_defaults())
        response = llm_client.complete(_report_request(request["topic"], evidence_bundle))
        return {"report_draft": _parse_report_json(response.content)}


def build_daily_intelligence_workflow(profile: str) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WORKFLOW_ID,
        name="Daily Intelligence Live",
        version=WORKFLOW_VERSION,
        description="Daily intelligence workflow for live and live-offline profiles.",
        start_step_id="collect_sources",
        terminal_step_ids=["quality_gate"],
        steps=[
            StepSpec(
                step_id="collect_sources",
                implementation="daily.collect_sources",
                read_keys=["request"],
                write_keys=[
                    "raw_items",
                    "source_errors",
                    "skipped_sources",
                    "failed_sources",
                    "source_health_updates",
                    "source_pipeline_metrics",
                ],
                required_output_keys=[
                    "raw_items",
                    "source_errors",
                    "skipped_sources",
                    "failed_sources",
                    "source_health_updates",
                    "source_pipeline_metrics",
                ],
            ),
            StepSpec(
                step_id="normalize_sources",
                implementation="daily.normalize_sources",
                read_keys=["raw_items", "source_pipeline_metrics"],
                write_keys=["normalized_items", "source_pipeline_metrics"],
                required_output_keys=["normalized_items", "source_pipeline_metrics"],
            ),
            StepSpec(
                step_id="deduplicate_sources",
                implementation="daily.deduplicate_sources",
                read_keys=["normalized_items", "source_pipeline_metrics"],
                write_keys=["deduplicated_items", "source_pipeline_metrics"],
                required_output_keys=["deduplicated_items", "source_pipeline_metrics"],
            ),
            StepSpec(
                step_id="rank_sources",
                implementation="daily.rank_sources",
                read_keys=["deduplicated_items", "request", "source_pipeline_metrics"],
                write_keys=["ranked_items", "source_pipeline_metrics"],
                required_output_keys=["ranked_items", "source_pipeline_metrics"],
            ),
            StepSpec(
                step_id="build_evidence",
                implementation="daily.build_evidence",
                read_keys=["ranked_items"],
                write_keys=["evidence_bundle"],
                required_output_keys=["evidence_bundle"],
            ),
            StepSpec(
                step_id="draft_report",
                implementation="daily.draft_report",
                read_keys=["request", "evidence_bundle"],
                write_keys=["report_draft"],
                required_output_keys=["report_draft"],
            ),
            StepSpec(
                step_id="quality_gate",
                implementation="daily.quality_gate",
                read_keys=["report_draft", "evidence_bundle"],
                write_keys=[
                    "citation_check_result",
                    "editor_review",
                    "final_report",
                    "report_markdown",
                    "blocked_report",
                ],
                required_output_keys=["citation_check_result", "editor_review"],
            ),
        ],
        edges=[
            EdgeSpec("collect-to-normalize", "collect_sources", "normalize_sources"),
            EdgeSpec("normalize-to-dedupe", "normalize_sources", "deduplicate_sources"),
            EdgeSpec("dedupe-to-rank", "deduplicate_sources", "rank_sources"),
            EdgeSpec("rank-to-evidence", "rank_sources", "build_evidence"),
            EdgeSpec("evidence-to-draft", "build_evidence", "draft_report"),
            EdgeSpec("draft-to-quality", "draft_report", "quality_gate"),
        ],
        metadata={"profile": profile, "product_path": profile == PROFILE_LIVE},
    )


def build_default_source_registry() -> SourceRegistry:
    return SourceRegistry(
        [
            SourceDefinition(
                source_id="openai-news",
                name="OpenAI News",
                source_type="rss",
                url="https://openai.com/news/rss.xml",
                reliability="high",
                authority_score=0.9,
                topics=["ai", "models"],
            ),
            SourceDefinition(
                source_id="google-ai-blog",
                name="Google AI Blog",
                source_type="rss",
                url="https://blog.google/technology/ai/rss/",
                reliability="high",
                authority_score=0.85,
                topics=["ai", "research"],
            ),
        ]
    )


def _normalize_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    normalized_items = normalize_items(buffer.read("raw_items"))
    metrics = buffer.read("source_pipeline_metrics")
    metrics.normalized_items_count = len(normalized_items)
    return {"normalized_items": normalized_items, "source_pipeline_metrics": metrics}


def _deduplicate_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    normalized_items = buffer.read("normalized_items")
    deduplicated_items = deduplicate_items(normalized_items)
    metrics = buffer.read("source_pipeline_metrics")
    metrics.deduplicated_items_count = len(deduplicated_items)
    metrics.duplicate_count = max(0, len(normalized_items) - len(deduplicated_items))
    return {"deduplicated_items": deduplicated_items, "source_pipeline_metrics": metrics}


def _rank_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    request = buffer.read("request")
    ranked_items = rank_items(buffer.read("deduplicated_items"), topic=request["topic"])
    metrics = buffer.read("source_pipeline_metrics")
    metrics.ranked_items_count = len(ranked_items)
    return {"ranked_items": ranked_items, "source_pipeline_metrics": metrics}


def _build_evidence(buffer: ScopedDataBuffer) -> dict[str, Any]:
    bundle = EvidenceBuilder().build(buffer.read("ranked_items"), bundle_id="daily")
    if not bundle.items:
        raise RuntimeError("no valid evidence built from ranked sources")
    return {"evidence_bundle": bundle}


def _quality_gate(buffer: ScopedDataBuffer) -> dict[str, Any]:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    citation_check = CitationChecker().check(report_draft, evidence_bundle)
    review = EditorGate().review(citation_check)
    outputs: dict[str, Any] = {
        "citation_check_result": citation_check,
        "editor_review": review,
    }
    if review.decision == EditorDecision.PASS:
        final_report = FinalReport(
            title=report_draft["title"],
            sections=report_draft["sections"],
            source_urls=sorted(evidence_bundle.source_urls),
            metadata={"evidence_bundle_id": evidence_bundle.bundle_id},
        )
        outputs["final_report"] = final_report
        outputs["report_markdown"] = render_markdown(final_report)
    else:
        outputs["blocked_report"] = BlockedReport(
            title=report_draft.get("title", "Blocked Daily Intelligence Report"),
            reasons=review.reasons,
            draft=report_draft,
            metadata={"citation_check_result": citation_check.to_dict()},
        )
    return outputs


def _deterministic_report(topic: str, evidence_bundle: EvidenceBundle) -> dict[str, Any]:
    lead = evidence_bundle.items[0]
    return {
        "title": f"Daily Intelligence: {topic}",
        "sections": [
            {
                "title": "Summary",
                "content": f"{lead.title}: {lead.summary}",
                "sources": [lead.source_url],
            },
            {
                "title": "Source Notes",
                "content": f"Built from {len(evidence_bundle.items)} evidence item(s).",
                "sources": sorted(evidence_bundle.source_urls),
            },
        ],
    }


def _report_request(topic: str, evidence_bundle: EvidenceBundle) -> LLMRequest:
    evidence_payload = [item.to_dict() for item in evidence_bundle.items]
    user = (
        "Create a concise daily intelligence report as JSON with keys title and sections. "
        "Each section must include title, content, and sources. "
        "Only cite source URLs present in the evidence. "
        f"Topic: {topic}. Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )
    return LLMRequest(
        messages=[
            {"role": "system", "content": "You write source-grounded intelligence reports."},
            {"role": "user", "content": user},
        ],
        metadata={"profile": PROFILE_LIVE},
    )


def _parse_report_json(content: str) -> dict[str, Any]:
    clean = content.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:]
    payload = json.loads(clean)
    if not isinstance(payload, dict):
        raise ValueError("LLM report output must be a JSON object")
    if "title" not in payload or "sections" not in payload:
        raise ValueError("LLM report output must include title and sections")
    return payload


def _fixture_source() -> SourceDefinition:
    return SourceDefinition(
        source_id="fixture-ai",
        name="Fixture AI Feed",
        source_type="rss",
        url="fixture://ai",
        reliability="high",
        topics=["ai", "chips", "policy"],
    )


def _fixture_feed() -> str:
    return """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Fixture AI</title>
    <item>
      <title>AI chip policy update</title>
      <link>https://example.com/ai-chip-policy</link>
      <description>Export controls and model supply chains remain central.</description>
      <pubDate>Mon, 11 May 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>New model evaluation benchmark</title>
      <link>https://example.com/model-benchmark</link>
      <description>Researchers published a deterministic evaluation benchmark.</description>
      <pubDate>Mon, 11 May 2026 01:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
