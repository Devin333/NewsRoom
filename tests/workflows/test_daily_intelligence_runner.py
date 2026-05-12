import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.framework.llm import LLMResponse, TokenUsage
from core.framework.specs import WorkflowStatus
from domain.sources import SourceDefinition, SourceError
from sources import SourceRegistry
from sources.connectors import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    ArxivConnector,
    FeedConnector,
    GithubConnector,
    HtmlConnector,
    TooManyRedirectsError,
)
from sources.health import BasicSourceHealthManager
from storage.lineage import LocalJsonLineageStore
from workflows.daily_intelligence import DailyIntelligenceRunner


RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Fixture</title>
    <item>
      <title>AI policy update</title>
      <link>https://example.com/ai-policy</link>
      <description>Policy summary.</description>
      <pubDate>Mon, 11 May 2026 02:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

HTML_FIXTURE = """<html lang="en">
  <head>
    <title>AI policy update</title>
    <link rel="canonical" href="https://example.com/ai-policy" />
  </head>
  <body><article><p>Policy summary from an official HTML source.</p></article></body>
</html>
"""

ARXIV_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2605.00001v1</id>
    <updated>2026-05-11T12:00:00Z</updated>
    <published>2026-05-10T10:00:00Z</published>
    <title>Agent Runtime Evaluation</title>
    <summary>We evaluate agent runtime systems.</summary>
    <author><name>Alice Example</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2605.00001v1" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

GITHUB_RELEASES = json.dumps(
    [
        {
            "id": 1,
            "url": "https://api.github.com/repos/owner/repo/releases/1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
            "tag_name": "v1.0.0",
            "name": "Version 1.0.0",
            "body": "Release notes for version 1.",
            "draft": False,
            "prerelease": False,
            "created_at": "2026-05-10T10:00:00Z",
            "published_at": "2026-05-11T12:00:00Z",
            "author": {"login": "maintainer"},
        }
    ]
)


def test_daily_intelligence_runner_live_offline_writes_report_artifacts(tmp_path) -> None:
    result = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
        run_id="daily-offline",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["final_report"].title == "Daily Intelligence: AI policy"

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "live-offline"
    assert manifest["artifacts"]["raw_items"] == "raw_items.json"
    assert manifest["artifacts"]["evidence_bundle"] == "evidence_bundle.json"
    assert manifest["artifacts"]["evidence_scores"] == "evidence_scores.json"
    assert manifest["artifacts"]["evidence_source_map"] == "evidence_source_map.json"
    assert manifest["artifacts"]["citation_check_result"] == "citation_check_result.json"
    assert manifest["artifacts"]["editor_review"] == "editor_review.json"
    assert manifest["artifacts"]["support_matrix"] == "support_matrix.json"
    assert manifest["artifacts"]["report_quality_summary"] == "report_quality_summary.json"
    assert manifest["artifacts"]["quality_events"] == "quality_events.json"
    assert manifest["artifacts"]["quality_gate_metrics"] == "quality_gate_metrics.json"
    assert manifest["quality_score"] == 1.0
    assert manifest["quality_event_count"] == 5
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert manifest["artifacts"]["source_events"] == "source_events.json"
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 6
    assert manifest["source_artifacts"]["item_count"] == 2
    assert manifest["source_artifacts"]["error_count"] == 0
    assert (run_dir / "report.md").exists()
    assert result.output["source_health_updates"][0].source_name == "Fixture AI Feed"
    assert result.output["source_health_updates"][0].url == "fixture://ai"

    source_events = json.loads((run_dir / "source_events.json").read_text())
    event_types = [event["event_type"] for event in source_events]
    assert event_types == [
        "source_fetch_started",
        "source_fetch_succeeded",
        "source_health_updated",
        "source_normalized",
        "source_deduplicated",
        "source_ranked",
    ]
    success_event = next(event for event in source_events if event["event_type"] == "source_fetch_succeeded")
    assert success_event["metadata"]["fetch_latency_ms"] >= 0

    source_metrics = json.loads((run_dir / "source_pipeline_metrics.json").read_text(encoding="utf-8"))
    assert source_metrics["avg_fetch_latency_ms"] >= 0

    source_artifacts = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    first_item = source_artifacts["entries"][0]
    assert first_item["artifact_type"] == "source_item"
    assert (run_dir / first_item["path"]).exists()

    evidence_scores = json.loads((run_dir / "evidence_scores.json").read_text())
    evidence_source_map = json.loads((run_dir / "evidence_source_map.json").read_text())
    assert len(evidence_scores) == len(result.output["evidence_bundle"].items)
    assert set(evidence_source_map) == result.output["evidence_bundle"].source_urls

    quality_events = json.loads((run_dir / "quality_events.json").read_text())
    assert [event["event_type"] for event in quality_events] == [
        "evidence_build_succeeded",
        "citation_check_started",
        "citation_check_succeeded",
        "editor_gate_started",
        "editor_gate_passed",
    ]
    quality_metrics = json.loads((run_dir / "quality_gate_metrics.json").read_text())
    assert quality_metrics["blocked"] is False
    assert quality_metrics["quality_score"] == 1.0

    lineage_store = LocalJsonLineageStore(tmp_path / "_records" / "lineage")
    evidence_id = result.output["evidence_bundle"].items[0].evidence_id
    upstream = lineage_store.upstream("daily-offline", "evidence", evidence_id)
    assert {ref.source_type for ref in upstream} >= {
        "source_url",
        "source_item",
        "normalized_source_item",
        "ranked_source_item",
    }


def test_daily_intelligence_runner_live_missing_llm_key_fails_safely(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="fixture",
                name="Fixture",
                source_type="rss",
                url="https://example.com/rss.xml",
                reliability="high",
            )
        ]
    )
    connector = FeedConnector(fetch_text=lambda url: RSS_FIXTURE)
    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=connector,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-missing-key")

    assert result.status == WorkflowStatus.FAILED
    assert result.error is not None
    assert result.error["error_type"] == "LLMConfigurationError"
    assert "DASHSCOPE_API_KEY" in result.error["message"]
    assert (Path(result.artifact_dir) / "error.json").exists()


def test_daily_intelligence_runner_live_with_injected_llm_succeeds(tmp_path) -> None:
    llm = _FakeReportLLM()
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="fixture",
                name="Fixture",
                source_type="rss",
                url="https://example.com/rss.xml",
                reliability="high",
            )
        ]
    )
    connector = FeedConnector(fetch_text=lambda url: RSS_FIXTURE)
    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=connector,
        llm_client=llm,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-injected")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["final_report"].title == "Injected Live Report"
    assert llm.requests[0].response_format == "json_object"
    assert (Path(result.artifact_dir) / "report.json").exists()


def test_daily_intelligence_runner_live_prefers_structured_llm_output(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="fixture",
                name="Fixture",
                source_type="rss",
                url="https://example.com/rss.xml",
                reliability="high",
            )
        ]
    )
    connector = FeedConnector(fetch_text=lambda url: RSS_FIXTURE)
    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=connector,
        llm_client=_StructuredReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-structured")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["final_report"].title == "Structured Live Report"


def test_daily_intelligence_runner_blocks_uncited_live_report(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="fixture",
                name="Fixture",
                source_type="rss",
                url="https://example.com/rss.xml",
                reliability="high",
            )
        ]
    )
    connector = FeedConnector(fetch_text=lambda url: RSS_FIXTURE)
    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=connector,
        llm_client=_UncitedReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-uncited")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert "blocked_report" in result.output
    assert "final_report" not in result.output
    assert result.output["quality_gate_metrics"].blocked is True
    assert result.output["quality_gate_metrics"].decision == "blocked"
    assert result.output["quality_gate_metrics"].missing_section_sources_count == 1
    assert any(event.event_type == "editor_gate_blocked" for event in result.output["quality_events"])

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["quality_events"] == "quality_events.json"
    assert manifest["artifacts"]["quality_gate_metrics"] == "quality_gate_metrics.json"
    assert manifest["artifacts"]["blocked_report"] == "blocked_report.json"


def test_daily_intelligence_runner_live_uses_topic_source_selection(tmp_path) -> None:
    fetched_urls = []
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="sports",
                name="Sports",
                source_type="rss",
                url="https://example.com/sports.xml",
                reliability="high",
                topics=["sports"],
            ),
            SourceDefinition(
                source_id="ai",
                name="AI",
                source_type="rss",
                url="https://example.com/ai.xml",
                reliability="medium",
                topics=["ai", "policy"],
            ),
        ]
    )

    def fetch_text(url: str) -> str:
        fetched_urls.append(url)
        return RSS_FIXTURE

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=fetch_text),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-topic-selected")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert fetched_urls == ["https://example.com/ai.xml"]


def test_daily_intelligence_runner_live_collects_html_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="html",
                name="HTML",
                source_type="html",
                url="https://example.com/blog",
                reliability="high",
                topics=["ai", "policy"],
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        html_connector=HtmlConnector(fetch_text=lambda url: HTML_FIXTURE),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-html-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "html"
    assert result.output["raw_items"][0].url == "https://example.com/ai-policy"
    assert any(
        event.event_type == "source_fetch_started" and event.metadata["source_type"] == "html"
        for event in result.output["source_events"]
    )


def test_daily_intelligence_runner_live_collects_manual_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="manual",
                name="Manual",
                source_type="manual",
                url="manual://operator",
                reliability="high",
                topics=["ai", "policy"],
                metadata={
                    "records": [
                        {
                            "title": "AI policy update",
                            "url": "https://example.com/ai-policy",
                            "summary": "Policy summary.",
                            "published_at": "2026-05-11T02:00:00Z",
                        }
                    ]
                },
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-manual-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "manual"
    assert result.output["raw_items"][0].metadata["manual_record_index"] == 0


def test_daily_intelligence_runner_live_collects_arxiv_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="arxiv",
                name="arXiv",
                source_type="arxiv",
                url=ARXIV_API_URL,
                reliability="high",
                topics=["ai", "papers"],
                metadata={"query": "cat:cs.AI"},
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        arxiv_connector=ArxivConnector(fetch_text=lambda url: ARXIV_FIXTURE),
        llm_client=_CitedReportLLM("http://arxiv.org/abs/2605.00001v1"),
    ).run(profile="live", topic="AI papers", source_limit=1, run_id="daily-arxiv-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "arxiv"
    assert result.output["raw_items"][0].metadata["arxiv_id"] == "2605.00001v1"


def test_daily_intelligence_runner_live_collects_github_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="github",
                name="GitHub",
                source_type="github",
                url=GITHUB_API_URL,
                reliability="high",
                topics=["ai", "release"],
                metadata={"repository": "owner/repo"},
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        github_connector=GithubConnector(fetch_text=lambda url: GITHUB_RELEASES),
        llm_client=_CitedReportLLM("https://github.com/owner/repo/releases/tag/v1.0.0"),
    ).run(profile="live", topic="AI release", source_limit=1, run_id="daily-github-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "github"
    assert result.output["raw_items"][0].metadata["repository"] == "owner/repo"


def test_daily_intelligence_runner_records_partial_source_failures(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="failing",
                name="Failing",
                source_type="rss",
                url="https://example.com/failing.xml",
                reliability="medium",
            ),
            SourceDefinition(
                source_id="working",
                name="Working",
                source_type="rss",
                url="https://example.com/working.xml",
                reliability="high",
            ),
        ]
    )

    def fetch_text(url: str) -> str:
        if "failing" in url:
            raise RuntimeError("fetch failed")
        return RSS_FIXTURE

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=fetch_text),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-partial-failure")

    assert result.status == WorkflowStatus.SUCCEEDED
    metrics = result.output["source_pipeline_metrics"]
    assert metrics.sources_failed == 1
    assert metrics.sources_fetched == 1
    assert metrics.errors_by_type == {"fetch_connection_error": 1}
    assert result.output["failed_sources"][0]["source_id"] == "failing"
    assert result.output["failed_sources"][0]["source_name"] == "Failing"
    assert result.output["failed_sources"][0]["retryable"] is True
    failing_health = next(
        health for health in result.output["source_health_updates"] if health.source_id == "failing"
    )
    assert failing_health.source_name == "Failing"
    assert failing_health.url == "https://example.com/failing.xml"

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["source_errors"] == "source_errors.json"
    assert manifest["artifacts"]["failed_sources"] == "failed_sources.json"
    assert manifest["artifacts"]["source_fetch_results"] == "source_fetch_results.json"
    assert manifest["artifacts"]["source_events"] == "source_events.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 9
    assert manifest["source_artifacts"] == {"item_count": 1, "error_count": 1, "total_count": 2}

    source_events = json.loads((run_dir / "source_events.json").read_text())
    assert any(
        event["event_type"] == "source_fetch_failed" and event["source_id"] == "failing"
        for event in source_events
    )
    failed_event = next(
        event
        for event in source_events
        if event["event_type"] == "source_fetch_failed" and event["source_id"] == "failing"
    )
    assert failed_event["metadata"]["fetch_latency_ms"] >= 0
    assert any(
        event["event_type"] == "source_fetch_succeeded" and event["source_id"] == "working"
        for event in source_events
    )

    source_artifacts = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    error_entry = next(
        entry for entry in source_artifacts["entries"] if entry["artifact_type"] == "source_error"
    )
    error_payload = json.loads((run_dir / error_entry["path"]).read_text())
    assert error_payload["error"]["source_id"] == "failing"
    assert error_payload["error"]["source_name"] == "Failing"
    assert error_payload["error"]["retryable"] is True

    source_fetch_results = json.loads((run_dir / "source_fetch_results.json").read_text())
    assert [result["source_id"] for result in source_fetch_results] == ["failing", "working"]
    assert source_fetch_results[0]["success"] is False
    assert source_fetch_results[0]["error_type"] == "fetch_connection_error"
    assert source_fetch_results[1]["success"] is True


def test_daily_intelligence_runner_honors_non_health_affecting_source_errors(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="blocked",
                name="Blocked",
                source_type="rss",
                url="https://example.com/blocked.xml",
                reliability="medium",
            ),
            SourceDefinition(
                source_id="working",
                name="Working",
                source_type="rss",
                url="https://example.com/working.xml",
                reliability="high",
            ),
        ]
    )
    health_manager = BasicSourceHealthManager(failure_threshold=1, cooldown_seconds=300)

    def fetch_text(url: str) -> str:
        if "blocked" in url:
            raise TooManyRedirectsError("https://example.com/loop", max_redirects=1)
        return RSS_FIXTURE

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=fetch_text),
        llm_client=_FakeReportLLM(),
        source_health_manager=health_manager,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-non-health-error")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert health_manager.get("blocked").status.value == "healthy"
    failed_event = next(
        event
        for event in result.output["source_events"]
        if event.event_type == "source_fetch_failed" and event.source_id == "blocked"
    )
    assert failed_event.metadata["retryable"] is False
    assert failed_event.metadata["source_health_affecting"] is False
    assert not any(
        event.event_type == "source_health_updated" and event.source_id == "blocked"
        for event in result.output["source_events"]
    )


def test_daily_intelligence_runner_all_sources_failed_preserves_diagnostics(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="failing",
                name="Failing",
                source_type="rss",
                url="https://example.com/failing.xml",
                reliability="medium",
            )
        ]
    )

    def fetch_text(url: str) -> str:
        raise RuntimeError("fetch failed")

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=fetch_text),
        llm_client=_FailIfCalledLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-all-sources-failed")

    assert result.status == WorkflowStatus.FAILED
    assert result.error is not None
    assert result.error["error_type"] == "AllSourcesFailedError"
    assert result.error["step_id"] == "require_sources"
    assert "all_sources_failed" in result.error["message"]
    assert result.output["raw_items"] == []
    assert any(error.error_type == "all_sources_failed" for error in result.output["source_errors"])

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["path"] == ["collect_sources", "require_sources"]
    assert manifest["artifacts"]["error"] == "error.json"
    assert manifest["artifacts"]["source_errors"] == "source_errors.json"
    assert manifest["artifacts"]["source_events"] == "source_events.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert "report_json" not in manifest["artifacts"]

    source_errors = json.loads((run_dir / "source_errors.json").read_text(encoding="utf-8"))
    assert any(error["error_type"] == "all_sources_failed" for error in source_errors)
    all_sources_error = next(
        error for error in source_errors if error["error_type"] == "all_sources_failed"
    )
    assert all_sources_error["source_name"] == "Source Pipeline"
    assert all_sources_error["retryable"] is False

    metrics = json.loads((run_dir / "source_pipeline_metrics.json").read_text(encoding="utf-8"))
    assert metrics["raw_items_count"] == 0
    assert metrics["errors_by_type"]["all_sources_failed"] == 1

    source_events = json.loads((run_dir / "source_events.json").read_text(encoding="utf-8"))
    assert any(
        event["event_type"] == "source_fetch_failed"
        and event["metadata"]["error_type"] == "all_sources_failed"
        for event in source_events
    )

    source_artifacts = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    assert source_artifacts["item_count"] == 0
    assert source_artifacts["error_count"] == 2


def test_daily_intelligence_runner_skips_cooling_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="cooling",
                name="Cooling",
                source_type="rss",
                url="https://example.com/cooling.xml",
                reliability="medium",
            ),
            SourceDefinition(
                source_id="working",
                name="Working",
                source_type="rss",
                url="https://example.com/working.xml",
                reliability="high",
            ),
        ]
    )
    health_manager = BasicSourceHealthManager(failure_threshold=1, cooldown_seconds=300)
    health_manager.record_failure(
        "cooling",
        SourceError(source_id="cooling", error_type="fetch_timeout", error_message="timeout"),
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=lambda url: RSS_FIXTURE),
        llm_client=_FakeReportLLM(),
        source_health_manager=health_manager,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-skip-cooling")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["skipped_sources"][0]["source_id"] == "cooling"
    assert result.output["skipped_sources"][0]["source_name"] == "Cooling"
    assert result.output["skipped_sources"][0]["url"] == "https://example.com/cooling.xml"
    assert result.output["source_pipeline_metrics"].sources_skipped == 1
    skipped_result = next(
        fetch_result
        for fetch_result in result.output["source_fetch_results"]
        if fetch_result.source_id == "cooling"
    )
    assert skipped_result.skipped is True
    assert skipped_result.skip_reason == "cooldown"
    assert any(
        event.event_type == "source_fetch_skipped" and event.source_id == "cooling"
        for event in result.output["source_events"]
    )


def test_daily_intelligence_runner_emits_probe_success_after_cooldown_expires(tmp_path) -> None:
    clock = {"now": datetime(2026, 5, 11, tzinfo=UTC)}
    health_manager = BasicSourceHealthManager(
        failure_threshold=1,
        cooldown_seconds=60,
        now=lambda: clock["now"],
    )
    health_manager.record_failure(
        "recovering",
        SourceError(source_id="recovering", error_type="fetch_timeout", error_message="timeout"),
    )
    clock["now"] = clock["now"] + timedelta(seconds=61)
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="recovering",
                name="Recovering",
                source_type="rss",
                url="https://example.com/recovering.xml",
                reliability="high",
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=lambda url: RSS_FIXTURE),
        llm_client=_FakeReportLLM(),
        source_health_manager=health_manager,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-probe-success")

    assert result.status == WorkflowStatus.SUCCEEDED
    event_types = [event.event_type for event in result.output["source_events"]]
    assert "source_probe_started" in event_types
    assert "source_probe_succeeded" in event_types
    assert "source_fetch_skipped" not in event_types


def test_daily_intelligence_runner_emits_probe_failure_after_cooldown_expires(tmp_path) -> None:
    clock = {"now": datetime(2026, 5, 11, tzinfo=UTC)}
    health_manager = BasicSourceHealthManager(
        failure_threshold=1,
        cooldown_seconds=60,
        now=lambda: clock["now"],
    )
    health_manager.record_failure(
        "recovering",
        SourceError(source_id="recovering", error_type="fetch_timeout", error_message="timeout"),
    )
    clock["now"] = clock["now"] + timedelta(seconds=61)
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="recovering",
                name="Recovering",
                source_type="rss",
                url="https://example.com/recovering.xml",
                reliability="high",
            )
        ]
    )

    def fetch_text(url: str) -> str:
        raise RuntimeError("still failing")

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=fetch_text),
        llm_client=_FailIfCalledLLM(),
        source_health_manager=health_manager,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-probe-failure")

    assert result.status == WorkflowStatus.FAILED
    event_types = [event.event_type for event in result.output["source_events"]]
    assert "source_probe_started" in event_types
    assert "source_probe_failed" in event_types
    probe_failed = next(
        event for event in result.output["source_events"] if event.event_type == "source_probe_failed"
    )
    assert probe_failed.metadata["error_type"] == "fetch_connection_error"


class _FakeReportLLM:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            content=json.dumps(
                {
                    "title": "Injected Live Report",
                    "sections": [
                        {
                            "title": "Summary",
                            "content": "Policy summary.",
                            "sources": ["https://example.com/ai-policy"],
                        }
                    ],
                }
            ),
            usage=TokenUsage(input_tokens=3, output_tokens=4),
        )


class _CitedReportLLM:
    def __init__(self, source_url: str) -> None:
        self.source_url = source_url

    def complete(self, request):
        return LLMResponse(
            content=json.dumps(
                {
                    "title": "Cited Live Report",
                    "sections": [
                        {
                            "title": "Summary",
                            "content": "Source-grounded summary.",
                            "sources": [self.source_url],
                        }
                    ],
                }
            ),
            usage=TokenUsage(input_tokens=3, output_tokens=4),
        )


class _StructuredReportLLM:
    def complete(self, request):
        return LLMResponse(
            content="not json",
            usage=TokenUsage(input_tokens=3, output_tokens=4),
            structured_output={
                "title": "Structured Live Report",
                "sections": [
                    {
                        "title": "Summary",
                        "content": "Policy summary.",
                        "sources": ["https://example.com/ai-policy"],
                    }
                ],
            },
        )


class _UncitedReportLLM:
    def complete(self, request):
        return LLMResponse(
            content=json.dumps(
                {
                    "title": "Uncited Live Report",
                    "sections": [
                        {
                            "title": "Summary",
                            "content": "Policy summary without citations.",
                            "sources": [],
                        }
                    ],
                }
            ),
            usage=TokenUsage(input_tokens=3, output_tokens=4),
        )


class _FailIfCalledLLM:
    def complete(self, request):
        raise AssertionError("LLM should not be called when all sources fail")
