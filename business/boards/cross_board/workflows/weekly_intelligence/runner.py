from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any

from framework import RunResult, WorkflowRunner
from framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from framework.workflow import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    FunctionStepRegistry,
    register_manifest_artifact_once,
)
from framework.workflow.buffer.data_buffer import StepScopedDataBufferView
from business.foundation.models.report_output import FinalReport, render_markdown
from infrastructure.storage.artifacts import ArtifactRef
from infrastructure.storage.local_json import LocalJsonRepository
from business.boards.cross_board.workflows.weekly_intelligence.trend_analyzer import WeeklyTrendAnalyzer
from business.boards.cross_board.workflows.weekly_intelligence.weekly_historian import WeeklyHistorian
from business.boards.cross_board.workflows.weekly_intelligence.weekly_improvement import WeeklyImprovementBuilder
from business.boards.cross_board.workflows.weekly_intelligence.weekly_quality import WeeklyQualityBuilder
from business.boards.cross_board.workflows.weekly_intelligence.weekly_subscription import WeeklySubscriptionBuilder
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    LEGACY_DAILY_WORKFLOW_ID,
    daily_workflow_ids,
)

PROFILE_WEEKLY = "weekly"
WORKFLOW_ID = "weekly-intelligence"
WORKFLOW_VERSION = "0.1.0"


class WeeklySourceReportNotFoundError(RuntimeError):
    pass


class WeeklyIntelligenceRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        report_repository: Any | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.report_repository = report_repository or LocalJsonRepository(self.artifact_root)

    def run(
        self,
        *,
        language: str = "en",
        topic: str | None = None,
        source_limit: int = 20,
        period_start: str | datetime | None = None,
        period_end: str | datetime | None = None,
        run_id: str | None = None,
    ) -> RunResult:
        if language != "en":
            raise ValueError("only language=en is supported for weekly intelligence")
        if source_limit <= 0:
            raise ValueError("source_limit must be greater than zero")
        registry = self._function_registry()
        runner = WorkflowRunner(
            artifact_root=self.artifact_root,
            function_registry=registry,
            artifact_publishers=_weekly_artifact_publishers(),
        )
        period = _resolve_period(period_start=period_start, period_end=period_end)
        return runner.run(
            build_weekly_intelligence_workflow(),
            {
                "language": language,
                "topic": _clean_topic(topic),
                "source_limit": source_limit,
                "source_workflow_id": LEGACY_DAILY_WORKFLOW_ID,
                "source_workflow_family": "daily",
                "period_start": _format_datetime(period[0]),
                "period_end": _format_datetime(period[1]),
                "run_id": run_id or "weekly-intelligence-run",
            },
            profile=PROFILE_WEEKLY,
            run_id=run_id,
        )

    def _function_registry(self) -> FunctionStepRegistry:
        registry = FunctionStepRegistry()
        registry.register("weekly.collect_source_reports", self._collect_source_reports)
        registry.register("weekly.analyze_trends", _analyze_weekly_trends)
        registry.register("weekly.build_timeline", _build_weekly_timeline)
        registry.register("weekly.build_quality", _build_weekly_quality)
        registry.register("weekly.build_subscription", _build_weekly_subscription)
        registry.register("weekly.build_improvement", _build_weekly_improvement)
        registry.register("weekly.write_report", _write_weekly_report)
        return registry

    def _collect_source_reports(self, buffer: StepScopedDataBufferView) -> dict[str, Any]:
        request = buffer.read("request")
        source_limit = int(request.get("source_limit", 20))
        period_start = _parse_datetime(str(request["period_start"]))
        period_end = _parse_datetime(str(request["period_end"]))
        workflow_id = str(request.get("source_workflow_id") or LEGACY_DAILY_WORKFLOW_ID)
        workflow_family = request.get("source_workflow_family")
        topic = request.get("topic")

        source_reports: list[dict[str, Any]] = []
        scan_limit = max(source_limit * 5, source_limit)
        candidates = self.report_repository.list_reports(
            limit=scan_limit,
            workflow_id=workflow_id if workflow_family is None else None,
            workflow_ids=daily_workflow_ids() if workflow_family == "daily" else None,
        )
        fallback_reports: list[dict[str, Any]] = []
        for candidate in candidates:
            finished_at = _try_parse_datetime(candidate.finished_at)
            if finished_at is None:
                continue
            detail = self.report_repository.get_report(candidate.report_id)
            source_report = _source_report_from_detail(detail)
            if topic and not _matches_topic(source_report, topic):
                continue
            if not _is_within_period(finished_at, period_start, period_end):
                fallback_reports.append(source_report)
                continue
            source_reports.append(source_report)
            if len(source_reports) >= source_limit:
                break

        if not source_reports and fallback_reports:
            source_reports = fallback_reports[:source_limit]

        if not source_reports:
            raise WeeklySourceReportNotFoundError(
                "no eligible daily reports found for weekly intelligence"
            )

        source_reports.sort(key=lambda item: item["finished_at"], reverse=True)
        return {
            "weekly_period": {
                "period_start": _format_datetime(period_start),
                "period_end": _format_datetime(period_end),
                "source_workflow_id": workflow_id,
            },
            "source_reports": source_reports,
        }


def build_weekly_intelligence_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WORKFLOW_ID,
        name="Weekly Intelligence",
        version=WORKFLOW_VERSION,
        description="Aggregate persisted daily intelligence reports into a weekly report.",
        start_step_id="collect_source_reports",
        terminal_step_ids=["write_weekly_report"],
        steps=[
            StepSpec(
                step_id="collect_source_reports",
                name="Collect source reports",
                implementation="weekly.collect_source_reports",
                read_keys=["request"],
                write_keys=["weekly_period", "source_reports"],
                required_output_keys=["weekly_period", "source_reports"],
            ),
            StepSpec(
                step_id="analyze_weekly_trends",
                name="Analyze weekly trends",
                implementation="weekly.analyze_trends",
                read_keys=["source_reports"],
                write_keys=["weekly_trends"],
                required_output_keys=["weekly_trends"],
            ),
            StepSpec(
                step_id="build_weekly_timeline",
                name="Build weekly timeline",
                implementation="weekly.build_timeline",
                read_keys=["source_reports", "weekly_trends"],
                write_keys=["weekly_timeline"],
                required_output_keys=["weekly_timeline"],
            ),
            StepSpec(
                step_id="build_weekly_quality",
                name="Build weekly quality",
                implementation="weekly.build_quality",
                read_keys=["source_reports", "weekly_trends"],
                write_keys=["weekly_quality"],
                required_output_keys=["weekly_quality"],
            ),
            StepSpec(
                step_id="build_weekly_subscription",
                name="Build weekly subscription",
                implementation="weekly.build_subscription",
                read_keys=["request", "source_reports", "weekly_trends", "weekly_quality"],
                write_keys=["weekly_subscription_payload"],
                required_output_keys=["weekly_subscription_payload"],
            ),
            StepSpec(
                step_id="build_weekly_improvement",
                name="Build weekly improvement",
                implementation="weekly.build_improvement",
                read_keys=["weekly_trends", "weekly_quality"],
                write_keys=["weekly_improvement_report"],
                required_output_keys=["weekly_improvement_report"],
            ),
            StepSpec(
                step_id="write_weekly_report",
                name="Write weekly report",
                implementation="weekly.write_report",
                read_keys=[
                    "request",
                    "weekly_period",
                    "source_reports",
                    "weekly_trends",
                    "weekly_timeline",
                    "weekly_quality",
                    "weekly_subscription_payload",
                    "weekly_improvement_report",
                ],
                write_keys=["final_report", "report_markdown", "weekly_metrics"],
                required_output_keys=["final_report", "report_markdown", "weekly_metrics"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="collect_to_write",
                source_step_id="collect_source_reports",
                target_step_id="analyze_weekly_trends",
            ),
            EdgeSpec(
                edge_id="analyze_to_timeline",
                source_step_id="analyze_weekly_trends",
                target_step_id="build_weekly_timeline",
            ),
            EdgeSpec(
                edge_id="timeline_to_quality",
                source_step_id="build_weekly_timeline",
                target_step_id="build_weekly_quality",
            ),
            EdgeSpec(
                edge_id="quality_to_subscription",
                source_step_id="build_weekly_quality",
                target_step_id="build_weekly_subscription",
            ),
            EdgeSpec(
                edge_id="subscription_to_improvement",
                source_step_id="build_weekly_subscription",
                target_step_id="build_weekly_improvement",
            ),
            EdgeSpec(
                edge_id="improvement_to_write",
                source_step_id="build_weekly_improvement",
                target_step_id="write_weekly_report",
            )
        ],
        input_schema={
            "type": "object",
            "required": ["language", "source_limit", "period_start", "period_end"],
            "properties": {
                "language": {"type": "string"},
                "topic": {"type": ["string", "null"]},
                "source_limit": {"type": "integer", "minimum": 1},
                "period_start": {"type": "string"},
                "period_end": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["final_report", "report_markdown", "weekly_metrics"],
        },
    )


class WeeklyIntelligenceArtifactPublisher:
    publisher_id = "weekly_intelligence"

    def supports(self, context: ArtifactPublishContext) -> bool:
        return (
            context.phase == ArtifactPublishPhase.TERMINAL
            and context.workflow.workflow_id == WORKFLOW_ID
        )

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        if "final_report" in context.output:
            register_manifest_artifact_once(context.manifest, "report_json", "report.json")
            path = context.artifact_manager.write_json(
                context.run_id,
                "report.json",
                context.output["final_report"],
            )
            refs.append(
                ArtifactRef(
                    artifact_id="report_json",
                    run_id=context.run_id,
                    artifact_type="report_json",
                    path="report.json",
                    content_type="application/json",
                    size_bytes=path.stat().st_size,
                    redacted=True,
                    metadata={"workflow_id": context.workflow.workflow_id},
                )
            )
        if isinstance(context.output.get("report_markdown"), str):
            register_manifest_artifact_once(context.manifest, "report_markdown", "report.md")
            path = context.artifact_manager.write_text(
                context.run_id,
                "report.md",
                context.output["report_markdown"],
            )
            refs.append(
                ArtifactRef(
                    artifact_id="report_markdown",
                    run_id=context.run_id,
                    artifact_type="report_markdown",
                    path="report.md",
                    content_type="text/markdown",
                    size_bytes=path.stat().st_size,
                    redacted=True,
                    metadata={"workflow_id": context.workflow.workflow_id},
                )
            )
        for artifact_key, relative_path in {
            "weekly_trends": "weekly_trends.json",
            "weekly_timeline": "weekly_timeline.json",
            "weekly_quality": "weekly_quality.json",
            "weekly_subscription_payload": "weekly_subscription_payload.json",
            "weekly_improvement_report": "weekly_improvement_report.json",
        }.items():
            if artifact_key not in context.output:
                continue
            register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
            path = context.artifact_manager.write_json(
                context.run_id,
                relative_path,
                context.output[artifact_key],
            )
            refs.append(
                ArtifactRef(
                    artifact_id=artifact_key,
                    run_id=context.run_id,
                    artifact_type=artifact_key,
                    path=relative_path,
                    content_type="application/json",
                    size_bytes=path.stat().st_size,
                    redacted=True,
                    metadata={"workflow_id": context.workflow.workflow_id},
                )
            )
        return refs


def _weekly_artifact_publishers() -> list[WeeklyIntelligenceArtifactPublisher]:
    return [WeeklyIntelligenceArtifactPublisher()]


def _write_weekly_report(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    request = buffer.read("request")
    period = buffer.read("weekly_period")
    source_reports = buffer.read("source_reports")
    weekly_trends = buffer.read("weekly_trends")
    weekly_timeline = buffer.read("weekly_timeline")
    weekly_quality = buffer.read("weekly_quality")
    weekly_subscription = buffer.read("weekly_subscription_payload")
    weekly_improvement = buffer.read("weekly_improvement_report")
    topic = request.get("topic")
    topic_label = topic or "all tracked topics"
    source_urls = _unique_url_list(source_reports)
    source_report_ids = [report["report_id"] for report in source_reports]
    average_quality = _average_quality(source_reports)

    sections = [
        {
            "title": "Executive Summary",
            "content": (
                f"Weekly synthesis for {topic_label} covering {period['period_start']} "
                f"to {period['period_end']}. Built from {len(source_reports)} persisted "
                "daily report(s)."
            ),
            "sources": source_urls,
        },
        {
            "title": "Daily Report Highlights",
            "content": _render_highlights(source_reports),
            "sources": source_urls,
        },
        {
            "title": "Coverage And Quality",
            "content": _render_coverage(source_reports, average_quality),
            "sources": [],
        },
        {
            "title": "Weekly Trend Intelligence",
            "content": _render_weekly_trends(weekly_trends),
            "sources": source_urls,
        },
        {
            "title": "Weekly Improvement",
            "content": _render_weekly_improvement(weekly_improvement),
            "sources": [],
        },
    ]
    final_report = FinalReport(
        title=f"Weekly Intelligence: {topic_label}",
        sections=sections,
        source_urls=source_urls,
        metadata={
            "report_type": "weekly",
            "language": request["language"],
            "topic": topic,
            "period_start": period["period_start"],
            "period_end": period["period_end"],
            "source_workflow_id": period["source_workflow_id"],
            "source_report_count": len(source_reports),
            "source_report_ids": source_report_ids,
            "average_quality_score": average_quality,
            "weekly_trends": weekly_trends,
            "weekly_timeline": weekly_timeline,
            "weekly_quality": weekly_quality,
            "weekly_subscription_payload": weekly_subscription,
            "weekly_improvement_report": weekly_improvement,
        },
    )
    return {
        "final_report": final_report,
        "report_markdown": render_markdown(final_report),
        "weekly_metrics": {
            "source_report_count": len(source_reports),
            "source_url_count": len(source_urls),
            "average_quality_score": average_quality,
            "high_confidence_trend_count": len(weekly_trends.get("high_confidence_trends") or []),
            "weekly_quality_score": weekly_quality.get("score"),
            "weekly_recommendation_count": len(weekly_improvement.get("recommendations") or []),
        },
    }


def _analyze_weekly_trends(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {"weekly_trends": WeeklyTrendAnalyzer().analyze(buffer.read("source_reports"))}


def _build_weekly_timeline(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {
        "weekly_timeline": WeeklyHistorian().build(
            buffer.read("source_reports"),
            buffer.read("weekly_trends"),
        )
    }


def _build_weekly_quality(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {
        "weekly_quality": WeeklyQualityBuilder().build(
            buffer.read("source_reports"),
            buffer.read("weekly_trends"),
        )
    }


def _build_weekly_subscription(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    request = buffer.read("request")
    return {
        "weekly_subscription_payload": WeeklySubscriptionBuilder().build(
            run_id=str(request.get("run_id") or "weekly-intelligence-run"),
            topic=request.get("topic"),
            source_reports=buffer.read("source_reports"),
            weekly_trends=buffer.read("weekly_trends"),
            weekly_quality=buffer.read("weekly_quality"),
        )
    }


def _build_weekly_improvement(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {
        "weekly_improvement_report": WeeklyImprovementBuilder().build(
            buffer.read("weekly_quality"),
            buffer.read("weekly_trends"),
        )
    }


def _resolve_period(
    *,
    period_start: str | datetime | None,
    period_end: str | datetime | None,
) -> tuple[datetime, datetime]:
    end = _parse_datetime(period_end) if period_end is not None else datetime.now(UTC)
    start = _parse_datetime(period_start) if period_start is not None else end - timedelta(days=7)
    if start > end:
        raise ValueError("period_start must be before period_end")
    return start, end


def _source_report_from_detail(detail: Any) -> dict[str, Any]:
    report_json = detail.report_json if isinstance(detail.report_json, dict) else {}
    return {
        "report_id": detail.report_id,
        "run_id": detail.run_id,
        "finished_at": detail.finished_at,
        "title": report_json.get("title") or detail.title or detail.report_id,
        "quality_score": detail.quality_score,
        "source_urls": _string_list(report_json.get("source_urls")),
        "sections": _section_list(report_json.get("sections")),
        "metadata": report_json.get("metadata") if isinstance(report_json.get("metadata"), dict) else {},
        "report_markdown": detail.report_markdown,
    }


def _matches_topic(source_report: dict[str, Any], topic: str) -> bool:
    needle = topic.lower()
    haystack = json.dumps(source_report, ensure_ascii=False, sort_keys=True).lower()
    return needle in haystack


def _render_highlights(source_reports: list[dict[str, Any]]) -> str:
    lines = []
    for report in source_reports:
        snippet = _first_section_snippet(report)
        lines.append(f"- {report['finished_at']} {report['title']} ({report['report_id']}): {snippet}")
    return "\n".join(lines)


def _render_coverage(source_reports: list[dict[str, Any]], average_quality: float | None) -> str:
    quality = "unknown" if average_quality is None else f"{average_quality:.2f}"
    source_counts = [len(report.get("source_urls") or []) for report in source_reports]
    return (
        f"Source reports: {len(source_reports)}. "
        f"Source URLs: {sum(source_counts)}. "
        f"Average quality score: {quality}."
    )


def _render_weekly_trends(weekly_trends: dict[str, Any]) -> str:
    trends = weekly_trends.get("high_confidence_trends") or []
    if not trends:
        return "No high-confidence weekly trends detected."
    return "\n".join(
        f"- {trend.get('topic')}: confidence {float(trend.get('confidence') or 0):.2f}"
        for trend in trends
        if isinstance(trend, dict)
    )


def _render_weekly_improvement(weekly_improvement: dict[str, Any]) -> str:
    recommendations = weekly_improvement.get("recommendations") or []
    if not recommendations:
        return "No weekly improvement actions required."
    return "\n".join(
        f"- {item.get('severity', 'info')}: {item.get('suggested_action')}"
        for item in recommendations
        if isinstance(item, dict)
    )


def _first_section_snippet(report: dict[str, Any]) -> str:
    sections = report.get("sections") or []
    if not sections:
        return "No section content available."
    content = str(sections[0].get("content") or "").replace("\n", " ").strip()
    if not content:
        return "No section content available."
    return content[:240]


def _average_quality(source_reports: list[dict[str, Any]]) -> float | None:
    values = [
        float(report["quality_score"])
        for report in source_reports
        if report.get("quality_score") is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _unique_url_list(source_reports: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for report in source_reports:
        for url in report.get("source_urls") or []:
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _section_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sections: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            sections.append(dict(item))
    return sections


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _clean_topic(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _try_parse_datetime(value: str | datetime) -> datetime | None:
    try:
        return _parse_datetime(value)
    except (TypeError, ValueError):
        return None


def _is_within_period(value: datetime, start: datetime, end: datetime) -> bool:
    if value < start:
        return False
    if value <= end:
        return True
    is_midnight_end = (
        end.hour == 0
        and end.minute == 0
        and end.second == 0
        and end.microsecond == 0
    )
    return is_midnight_end and value.date() == end.date()


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
