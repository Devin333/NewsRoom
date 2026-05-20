import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from framework.llm import LLMResponse, TokenUsage
from framework.specs import WorkflowStatus
from business.foundation.models.source import RawSourceItem, SourceDefinition, SourceError
from business.layers.signal.source_config import SourceConfigError
from business.foundation.registry.source_registry import SourceRegistry
from business.boards.cross_board.workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID
from infrastructure.external.sources import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    HACKERNEWS_API_URL,
    REDDIT_BASE_URL,
    ArxivConnector,
    FeedConnector,
    GithubConnector,
    HackerNewsConnector,
    HtmlConnector,
    RedditConnector,
    SyncSourceConnectorAdapter,
    TooManyRedirectsError,
)
from business.layers.signal.source_health import BasicSourceHealthManager
from infrastructure.storage.lineage import LocalJsonLineageStore
from business.layers.analysis.quality import EditorDecision
from business.boards.cross_board.workflows.daily_intelligence import DailyIntelligenceRunner


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

HACKERNEWS_STORY_IDS = "[123]"
HACKERNEWS_ITEM = json.dumps(
    {
        "id": 123,
        "type": "story",
        "by": "pg",
        "time": 1778490000,
        "title": "AI policy update",
        "url": "https://example.com/hackernews-ai-policy",
        "text": "<p>Policy summary from Hacker News.</p>",
        "score": 42,
        "descendants": 5,
    }
)

REDDIT_LISTING = json.dumps(
    {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc123",
                        "subreddit": "MachineLearning",
                        "title": "AI policy update",
                        "permalink": "/r/MachineLearning/comments/abc123/ai_policy_update/",
                        "url_overridden_by_dest": "https://example.com/reddit-ai-policy",
                        "selftext": "Policy summary from Reddit.",
                        "author": "researcher",
                        "created_utc": 1778490000,
                        "score": 100,
                        "num_comments": 12,
                        "link_flair_text": "Discussion",
                    },
                }
            ]
        }
    }
)


def test_daily_intelligence_runner_workflow_runner_smoke(tmp_path) -> None:
    result = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="daily-workflow-runner-smoke",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.workflow_id == LEGACY_DAILY_WORKFLOW_ID
    assert result.output["final_report"].title == "Daily Intelligence: AI policy"


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
    assert manifest["artifacts"]["candidate_claims"] == "candidate_claims.json"
    assert manifest["artifacts"]["verified_findings"] == "verified_findings.json"
    assert manifest["artifacts"]["evidence_source_map"] == "evidence_source_map.json"
    assert manifest["artifacts"]["citation_check_result"] == "citation_check_result.json"
    assert manifest["artifacts"]["editor_review"] == "editor_review.json"
    assert manifest["artifacts"]["support_matrix"] == "support_matrix.json"
    assert manifest["artifacts"]["report_quality_summary"] == "report_quality_summary.json"
    assert manifest["artifacts"]["quality_events"] == "quality_events.json"
    assert manifest["artifacts"]["quality_gate_metrics"] == "quality_gate_metrics.json"
    assert manifest["artifacts"]["quality_result"] == "quality_result.json"
    assert manifest["quality_decision"] == "pass"
    assert manifest["quality_route"] == "final"
    assert manifest["artifacts"]["rewrite_policy"] == "rewrite_policy.json"
    assert manifest["artifacts"]["rewrite_instructions"] == "rewrite_instructions.json"
    assert manifest["quality_score"] == 1.0
    assert manifest["quality_event_count"] == 6
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert manifest["artifacts"]["source_events"] == "source_events.json"
    assert manifest["artifacts"]["source_health_report"] == "source_health_report.json"
    assert manifest["artifacts"]["source_connector_dispatch_report"] == "source_connector_dispatch_report.json"
    assert manifest["artifacts"]["source_error_policy_report"] == "source_error_policy_report.json"
    assert manifest["artifacts"]["source_fallback_report"] == "source_fallback_report.json"
    assert manifest["artifacts"]["source_selection_report"] == "source_selection_report.json"
    assert manifest["artifacts"]["source_coverage_report"] == "source_coverage_report.json"
    assert manifest["artifacts"]["source_quality_scores"] == "source_quality_scores.json"
    assert manifest["artifacts"]["source_quality_summary_report"] == "source_quality_summary_report.json"
    assert manifest["artifacts"]["source_ranking_scores"] == "source_ranking_scores.json"
    assert manifest["artifacts"]["source_freshness_report"] == "source_freshness_report.json"
    assert manifest["artifacts"]["source_traceability_report"] == "source_traceability_report.json"
    assert manifest["artifacts"]["source_governance_report"] == "source_governance_report.json"
    assert manifest["source_quality_score_count"] == 2
    assert manifest["source_ranking_score_count"] == 2
    assert manifest["artifacts"]["source_fetch_requests"] == "source_fetch_requests.json"
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 8
    assert manifest["source_artifacts"]["item_count"] == 2
    assert manifest["source_artifacts"]["error_count"] == 0
    assert manifest["source_artifacts"]["raw_content_count"] == 2
    assert manifest["source_artifacts"]["fetch_request_count"] == 1
    assert manifest["source_artifacts"]["fetch_result_count"] == 1
    assert manifest["source_artifacts"]["parsed_items_count"] == 1
    assert (run_dir / "report.md").exists()
    assert result.output["source_health_updates"][0].source_name == "Fixture AI Feed"
    assert result.output["source_health_updates"][0].url == "fixture://ai"
    assert result.output["source_health_updates"][0].success_count_24h == 1
    assert result.output["source_health_updates"][0].avg_latency_ms_24h >= 0

    source_events = json.loads((run_dir / "source_events.json").read_text())
    event_types = [event["event_type"] for event in source_events]
    assert event_types == [
        "source_fetch_started",
        "source_parse_started",
        "source_fetch_succeeded",
        "source_parse_succeeded",
        "source_health_updated",
        "source_normalized",
        "source_deduplicated",
        "source_ranked",
    ]
    success_event = next(event for event in source_events if event["event_type"] == "source_fetch_succeeded")
    assert success_event["metadata"]["fetch_latency_ms"] >= 0

    source_metrics = json.loads((run_dir / "source_pipeline_metrics.json").read_text(encoding="utf-8"))
    assert source_metrics["avg_fetch_latency_ms"] >= 0
    assert source_metrics["sources_by_type"] == {"rss": 1}
    assert source_metrics["sources_by_reliability"] == {"high": 1}
    assert source_metrics["fetched_by_type"] == {"rss": 1}
    assert source_metrics["items_by_source_type"] == {"rss": 2}
    assert source_metrics["items_by_reliability"] == {"high": 2}

    health_report = json.loads((run_dir / "source_health_report.json").read_text(encoding="utf-8"))
    assert health_report["health_update_count"] == 1
    assert health_report["status_counts"] == {"healthy": 1}
    assert health_report["rows"][0]["source_id"] == "fixture-ai"
    assert result.output["source_health_report"].status_counts == {"healthy": 1}

    dispatch_report = json.loads((run_dir / "source_connector_dispatch_report.json").read_text(encoding="utf-8"))
    assert dispatch_report["total_dispatch_count"] == 1
    assert dispatch_report["success_count"] == 1
    assert dispatch_report["connector_counts"] == {"FeedConnector": 1}
    assert dispatch_report["rows"][0]["connector_name"] == "FeedConnector"
    assert dispatch_report["rows"][0]["success"] is True
    assert result.output["source_connector_dispatch_report"].success_count == 1

    error_policy_report = json.loads(
        (run_dir / "source_error_policy_report.json").read_text(encoding="utf-8")
    )
    assert error_policy_report["total_error_count"] == 0
    assert error_policy_report["errors_by_type"] == {}
    assert result.output["source_error_policy_report"].total_error_count == 0

    fallback_report = json.loads((run_dir / "source_fallback_report.json").read_text(encoding="utf-8"))
    assert fallback_report["total_fallback_count"] == 0
    assert fallback_report["selection_fallback_used"] is False
    assert fallback_report["item_fallback_count"] == 0
    assert result.output["source_fallback_report"].total_fallback_count == 0

    selection_report = json.loads((run_dir / "source_selection_report.json").read_text(encoding="utf-8"))
    assert selection_report["topic"] == "AI policy"
    assert selection_report["fallback_used"] is False
    assert selection_report["selected_source_ids"] == ["fixture-ai"]
    assert selection_report["selected_sources"][0]["source_type"] == "rss"

    coverage_report = json.loads((run_dir / "source_coverage_report.json").read_text(encoding="utf-8"))
    assert coverage_report["coverage_status"] == "covered"
    assert coverage_report["selected_source_count"] == 1
    assert coverage_report["attempted_source_count"] == 1
    assert coverage_report["fetched_source_count"] == 1
    assert coverage_report["raw_item_count"] == 2
    assert coverage_report["normalized_item_count"] == 2
    assert coverage_report["deduplicated_item_count"] == 2
    assert coverage_report["ranked_item_count"] == 2
    assert coverage_report["fetch_success_ratio"] == 1.0
    assert coverage_report["sources_by_type"] == {"rss": 1}
    assert result.output["source_coverage_report"].coverage_status == "covered"

    source_quality_scores = json.loads((run_dir / "source_quality_scores.json").read_text(encoding="utf-8"))
    assert len(source_quality_scores) == 2
    assert source_quality_scores[0]["source_id"] == "fixture-ai"
    assert source_quality_scores[0]["quality_score"] > 0.8
    assert source_quality_scores[0]["traceability_score"] == 1.0
    assert result.output["source_quality_scores"] == source_quality_scores

    quality_summary_report = json.loads(
        (run_dir / "source_quality_summary_report.json").read_text(encoding="utf-8")
    )
    assert quality_summary_report["item_count"] == 2
    assert quality_summary_report["low_quality_count"] == 0
    assert quality_summary_report["weak_traceability_count"] == 0
    assert quality_summary_report["average_quality_score"] > 0.8
    assert result.output["source_quality_summary_report"].item_count == 2

    source_ranking_scores = json.loads((run_dir / "source_ranking_scores.json").read_text(encoding="utf-8"))
    assert len(source_ranking_scores) == 2
    assert source_ranking_scores[0]["source_id"] == "fixture-ai"
    assert source_ranking_scores[0]["final_score"] == result.output["ranked_items"][0].final_score
    assert "authority_score" in source_ranking_scores[0]

    freshness_report = json.loads((run_dir / "source_freshness_report.json").read_text(encoding="utf-8"))
    assert freshness_report["freshness_status"] == "fresh"
    assert freshness_report["ranked_item_count"] == 2
    assert freshness_report["stale_item_count"] == 0
    assert freshness_report["rows"][0]["source_id"] == "fixture-ai"
    assert freshness_report["rows"][0]["timestamp_basis"] == "published_at"
    assert result.output["source_freshness_report"].freshness_status == "fresh"

    traceability_report = json.loads((run_dir / "source_traceability_report.json").read_text(encoding="utf-8"))
    assert traceability_report["traceability_status"] == "complete"
    assert traceability_report["ranked_item_count"] == 2
    assert traceability_report["traceable_item_count"] == 2
    assert traceability_report["issue_count"] == 0
    assert traceability_report["rows"][0]["source_id"] == "fixture-ai"
    assert result.output["source_traceability_report"].traceability_status == "complete"

    governance_report = json.loads((run_dir / "source_governance_report.json").read_text(encoding="utf-8"))
    assert governance_report["finding_count"] == 0
    assert governance_report["blocking_finding_count"] == 0

    source_fetch_requests = json.loads((run_dir / "source_fetch_requests.json").read_text())
    assert source_fetch_requests[0]["request_id"] == result.output["source_fetch_results"][0].request_id
    assert source_fetch_requests[0]["metadata"]["profile"] == "live-offline"

    source_artifacts = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    first_item = source_artifacts["entries"][0]
    assert first_item["artifact_type"] == "source_item"
    assert first_item["raw_artifact_ref"]["artifact_type"] == "source_raw_content"
    assert first_item["parse_artifact_ref"]["artifact_type"] == "source_item"
    assert (run_dir / first_item["path"]).exists()
    first_raw = next(entry for entry in source_artifacts["entries"] if entry["artifact_type"] == "source_raw_content")
    assert (run_dir / first_raw["path"]).exists()

    evidence_scores = json.loads((run_dir / "evidence_scores.json").read_text())
    candidate_claims = json.loads((run_dir / "candidate_claims.json").read_text())
    verified_findings = json.loads((run_dir / "verified_findings.json").read_text())
    evidence_source_map = json.loads((run_dir / "evidence_source_map.json").read_text())
    assert len(evidence_scores) == len(result.output["evidence_bundle"].items)
    assert len(candidate_claims) == len(result.output["evidence_bundle"].items)
    assert len(verified_findings["accepted_claims"]) == len(result.output["evidence_bundle"].items)
    assert set(evidence_source_map) == result.output["evidence_bundle"].source_urls

    quality_events = json.loads((run_dir / "quality_events.json").read_text())
    assert [event["event_type"] for event in quality_events] == [
        "evidence_build_succeeded",
        "claim_verification_succeeded",
        "citation_check_started",
        "citation_check_succeeded",
        "editor_gate_started",
        "editor_gate_passed",
    ]
    quality_metrics = json.loads((run_dir / "quality_gate_metrics.json").read_text())
    assert quality_metrics["blocked"] is False
    assert quality_metrics["quality_score"] == 1.0
    assert quality_metrics["accepted_claims_count"] == len(result.output["evidence_bundle"].items)
    assert quality_metrics["claim_support_score"] == 1.0
    assert quality_metrics["citation_failure_category_count"] == 0
    assert quality_metrics["citation_failure_categories"] == []
    quality_result = json.loads((run_dir / "quality_result.json").read_text())
    assert quality_result["decision"] == "pass"
    assert quality_result["route"] == "final"
    assert quality_result["artifact_refs"]["citation_check_result"] == "citation_check_result.json"

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
                fetch_interval_seconds=1800,
                user_agent="NewsRoomLiveTest/1.0",
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
    run_dir = Path(result.artifact_dir)
    assert (run_dir / "report.json").exists()
    source_fetch_requests = json.loads((run_dir / "source_fetch_requests.json").read_text())
    assert source_fetch_requests[0]["user_agent"] == "NewsRoomLiveTest/1.0"
    assert source_fetch_requests[0]["metadata"]["fetch_interval_seconds"] == 1800
    assert source_fetch_requests[0]["metadata"]["respect_robots"] is True


def test_daily_intelligence_runner_rewrites_duplicate_supported_report(tmp_path) -> None:
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
        llm_client=_DuplicateReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-duplicate")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["editor_review"].decision == EditorDecision.PASS
    assert result.output["quality_gate_metrics"].rewrite_attempts == 1
    assert "rewritten_report_draft" in result.output
    assert len(result.output["final_report"].sections) == 1

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["rewritten_report_draft"] == "rewritten_report_draft.json"
    event_types = [
        event["event_type"]
        for event in json.loads((run_dir / "quality_events.json").read_text(encoding="utf-8"))
    ]
    assert "editor_gate_rewrite_required" in event_types
    assert "rewrite_succeeded" in event_types


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
    assert result.output["quality_result"].route == "human_review"
    assert result.output["quality_result"].route_history == ["blocked", "human_review"]
    assert any(event.event_type == "editor_gate_blocked" for event in result.output["quality_events"])

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["quality_events"] == "quality_events.json"
    assert manifest["artifacts"]["quality_gate_metrics"] == "quality_gate_metrics.json"
    assert manifest["artifacts"]["quality_result"] == "quality_result.json"
    assert manifest["quality_route"] == "human_review"
    assert manifest["artifacts"]["blocked_report"] == "blocked_report.json"
    assert manifest["artifacts"]["human_review_request"] == "human_review_request.json"


def test_daily_intelligence_runner_rewrites_unsupported_claim_before_final_report(tmp_path) -> None:
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
        llm_client=_UnsupportedClaimLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-unsupported-claim")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["editor_review"].decision == EditorDecision.PASS
    assert result.output["quality_result"].route == "rewrite"
    assert result.output["quality_result"].route_history == ["rewrite"]
    assert result.output["quality_gate_metrics"].rewrite_attempts == 1
    assert "final_report" in result.output
    final_content = " ".join(
        str(section.get("content", "")) for section in result.output["final_report"].sections
    )
    assert "quantum chip acquisition" not in final_content

    run_dir = Path(result.artifact_dir)
    quality_result = json.loads((run_dir / "quality_result.json").read_text(encoding="utf-8"))
    assert quality_result["route"] == "rewrite"
    assert quality_result["rewrite_attempts"] == 1
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["quality_result"] == "quality_result.json"


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


def test_daily_intelligence_runner_loads_source_config_path(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "configured-feed",
                        "name": "Configured Feed",
                        "source_type": "rss",
                        "url": "https://example.com/configured.xml",
                        "reliability": "high",
                        "topics": ["ai", "policy"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    fetched_urls = []

    def fetch_text(url: str) -> str:
        fetched_urls.append(url)
        return RSS_FIXTURE

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_config_path=config_path,
        feed_connector=FeedConnector(fetch_text=fetch_text),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-configured-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert fetched_urls == ["https://example.com/configured.xml"]
    assert result.output["raw_items"][0].source_id == "configured-feed"


def test_daily_intelligence_runner_applies_configured_fetch_policy_to_default_connectors(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
fetch:
  timeout_seconds: 7.5
  max_bytes: 5000
  max_redirects: 5
  user_agent: NewsRoomConfiguredPolicy/1.0
  respect_robots: false
  rate_limit_per_domain_per_minute: 20
  retry_times: 1
  retry_on_status_codes: [429, 503]
rss_feeds:
  - source_id: configured-feed
    name: Configured Feed
    url: https://example.com/configured.xml
    reliability: high
    topics: [ai, policy]
""".strip(),
        encoding="utf-8",
    )
    captured = {}

    class Headers:
        def get_content_type(self):
            return "application/rss+xml"

        def items(self):
            return [("Content-Type", "application/rss+xml")]

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def geturl(self):
            return "https://example.com/configured.xml"

        def read(self, size):
            captured["read_size"] = size
            return RSS_FIXTURE.encode("utf-8")

    def fake_open_request(request, policy):
        captured["user_agent"] = request.headers["User-agent"]
        captured["timeout_seconds"] = policy.timeout_seconds
        captured["max_redirects"] = policy.max_redirects
        return Response()

    monkeypatch.setattr("infrastructure.external.sources.feed.open_request_with_fetch_policy", fake_open_request)

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_config_path=config_path,
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-configured-policy")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert captured == {
        "user_agent": "NewsRoomConfiguredPolicy/1.0",
        "timeout_seconds": 7.5,
        "max_redirects": 5,
        "read_size": 5001,
    }
    fetch_request = result.output["source_fetch_requests"][0]
    assert fetch_request.timeout_seconds == 7.5
    assert fetch_request.max_bytes == 5000
    assert fetch_request.max_redirects == 5
    assert fetch_request.user_agent == "NewsRoomConfiguredPolicy/1.0"
    assert fetch_request.headers == {"User-Agent": "NewsRoomConfiguredPolicy/1.0"}
    assert fetch_request.metadata["robots_policy"] is False
    assert fetch_request.metadata["rate_limit_per_domain_per_minute"] == 20
    assert fetch_request.metadata["retry_on_status_codes"] == [429, 503]


def test_daily_intelligence_runner_shares_rate_limiter_across_default_connectors(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
fetch:
  rate_limit_per_domain_per_minute: 1
  respect_robots: false
rss_feeds:
  - source_id: a-feed
    name: Feed
    url: https://example.com/feed.xml
    reliability: high
    topics: [ai, policy]
web_pages:
  - source_id: b-page
    name: Page
    url: https://example.com/page
    reliability: high
    topics: [ai, policy]
""".strip(),
        encoding="utf-8",
    )
    opened_urls = []

    class Headers:
        def get_content_type(self):
            return "application/rss+xml"

        def items(self):
            return [("Content-Type", "application/rss+xml")]

    class Response:
        status = 200
        headers = Headers()

        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def geturl(self):
            return self.url

        def read(self, size):
            return RSS_FIXTURE.encode("utf-8")

    def fake_feed_open_request(request, policy):
        opened_urls.append(request.full_url)
        return Response(request.full_url)

    def fail_html_open_request(request, policy):
        raise AssertionError("HTML source should be rate-limited before fetch")

    monkeypatch.setattr(
        "infrastructure.external.sources.feed.open_request_with_fetch_policy",
        fake_feed_open_request,
    )
    monkeypatch.setattr(
        "infrastructure.external.sources.html.open_request_with_fetch_policy",
        fail_html_open_request,
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_config_path=config_path,
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=2, run_id="daily-shared-rate-limit")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert opened_urls == ["https://example.com/feed.xml"]
    rate_limited = next(error for error in result.output["source_errors"] if error.error_type == "rate_limited")
    assert rate_limited.source_id == "b-page"
    assert rate_limited.metadata["domain"] == "example.com"
    assert rate_limited.metadata["source_health_affecting"] is False


def test_daily_intelligence_runner_dispatches_registered_sync_connector(tmp_path) -> None:
    connector = _RegistrySyncConnector()
    source_url = "https://example.com/registry-sync"
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="registry-rss",
                name="Registry RSS",
                source_type="rss",
                url="https://example.com/registry.xml",
                reliability="high",
                topics=["ai", "policy"],
            )
        ],
        connectors={"rss": connector},
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(
            fetch_text=lambda url: (_ for _ in ()).throw(
                AssertionError("built-in feed called")
            )
        ),
        llm_client=_CitedReportLLM(source_url),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-registry-sync")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert connector.calls == [{"source_id": "registry-rss", "limit": 1}]
    assert result.output["raw_items"][0].url == source_url
    assert result.output["source_fetch_requests"][0].metadata["connector_name"] == "_RegistrySyncConnector"
    assert result.output["source_connector_dispatch_report"].connector_counts == {
        "_RegistrySyncConnector": 1
    }


def test_daily_intelligence_runner_dispatches_registered_protocol_connector(tmp_path) -> None:
    connector = _ProtocolBackedSyncConnector()
    adapter = SyncSourceConnectorAdapter(connector, source_type="rss")
    source_url = "https://example.com/registry-protocol"
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="protocol-rss",
                name="Protocol RSS",
                source_type="rss",
                url="https://example.com/protocol.xml",
                reliability="high",
                topics=["ai", "policy"],
            )
        ],
        connectors={"rss": adapter},
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        llm_client=_CitedReportLLM(source_url),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-registry-protocol")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert connector.calls == [{"source_id": "protocol-rss", "limit": 1}]
    fetch_request = result.output["source_fetch_requests"][0]
    fetch_result = result.output["source_fetch_results"][0]
    assert fetch_request.metadata["connector_name"] == "_ProtocolBackedSyncConnector"
    assert fetch_result.metadata["connector_name"] == "_ProtocolBackedSyncConnector"
    assert fetch_result.metadata["context"]["profile"] == "live"
    assert fetch_result.metadata["context"]["topic"] == "AI policy"


def test_daily_intelligence_runner_persists_response_headers_from_default_fetch(tmp_path, monkeypatch) -> None:
    class Headers:
        def get_content_type(self):
            return "application/rss+xml"

        def items(self):
            return [
                ("Content-Type", "application/rss+xml"),
                ("Cache-Control", "max-age=60"),
            ]

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def geturl(self):
            return "https://example.com/ai.xml"

        def read(self, size):
            return RSS_FIXTURE.encode("utf-8")

    def fake_open_request(request, policy):
        return Response()

    monkeypatch.setattr("infrastructure.external.sources.feed.open_request_with_fetch_policy", fake_open_request)
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="ai",
                name="AI",
                source_type="rss",
                url="https://example.com/ai.xml",
                reliability="high",
                respect_robots=False,
                topics=["ai", "policy"],
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-response-headers")

    assert result.status == WorkflowStatus.SUCCEEDED
    fetch_result = result.output["source_fetch_results"][0]
    assert fetch_result.status_code == 200
    assert fetch_result.content_type == "application/rss+xml"
    assert fetch_result.metadata["response_headers"]["Content-Type"] == "application/rss+xml"

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_artifacts"]["response_headers_count"] == 1
    source_artifacts = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    response_headers_entry = next(
        entry for entry in source_artifacts["entries"] if entry["artifact_type"] == "source_response_headers"
    )
    response_headers_payload = json.loads((run_dir / response_headers_entry["path"]).read_text())
    assert response_headers_payload["headers"]["Content-Type"] == "application/rss+xml"
    assert response_headers_payload["headers"]["Cache-Control"] == "max-age=60"
    fetch_result_artifact = next(
        entry for entry in source_artifacts["entries"] if entry["artifact_type"] == "source_fetch_result"
    )
    fetch_result_payload = json.loads((run_dir / fetch_result_artifact["path"]).read_text())
    assert fetch_result_payload["response_headers_ref"] == response_headers_entry["artifact_ref"]


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


def test_daily_intelligence_runner_live_collects_official_blog_source_from_feed(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="official-blog",
                name="Official Blog",
                source_type="official_blog",
                url="https://example.com/blog/rss.xml",
                reliability="high",
                topics=["ai", "policy"],
            )
        ]
    )

    def fail_html(url: str) -> str:
        raise AssertionError("html fallback should not run when feed succeeds")

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=lambda url: RSS_FIXTURE),
        html_connector=HtmlConnector(fetch_text=fail_html),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-official-blog-feed")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "official_blog"
    assert result.output["raw_items"][0].metadata["official_blog"] is True
    assert result.output["raw_items"][0].metadata["official_blog_fetch_mode"] == "feed"
    assert "official_blog_fallback" not in result.output["raw_items"][0].metadata
    assert result.output["source_pipeline_metrics"].items_by_source_type == {"official_blog": 1}


def test_daily_intelligence_runner_live_falls_back_official_blog_to_html(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="official-blog",
                name="Official Blog",
                source_type="official_blog",
                url="https://example.com/blog",
                reliability="high",
                topics=["ai", "policy"],
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=lambda url: (_ for _ in ()).throw(RuntimeError("feed down"))),
        html_connector=HtmlConnector(fetch_text=lambda url: HTML_FIXTURE),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-official-blog-html-fallback")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "official_blog"
    assert result.output["raw_items"][0].metadata["official_blog"] is True
    assert result.output["raw_items"][0].metadata["official_blog_fetch_mode"] == "html_fallback"
    assert result.output["raw_items"][0].metadata["official_blog_fallback"] == {
        "from": "feed",
        "to": "html",
        "feed_error_types": ["fetch_connection_error"],
    }
    assert result.output["source_pipeline_metrics"].items_by_source_type == {"official_blog": 1}
    fallback_report = result.output["source_fallback_report"]
    assert fallback_report.total_fallback_count == 1
    assert fallback_report.item_fallback_count == 1
    assert fallback_report.rows[0]["fallback_type"] == "official_blog_fetch"
    assert fallback_report.rows[0]["feed_error_types"] == ["fetch_connection_error"]


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


def test_daily_intelligence_runner_live_collects_hackernews_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="hackernews",
                name="Hacker News",
                source_type="hackernews",
                url=HACKERNEWS_API_URL,
                reliability="medium",
                topics=["ai", "technology"],
                metadata={"story_list": "topstories"},
            )
        ]
    )

    def fetch_text(url: str) -> str:
        if url.endswith("/topstories.json"):
            return HACKERNEWS_STORY_IDS
        return HACKERNEWS_ITEM

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        hackernews_connector=HackerNewsConnector(fetch_text=fetch_text),
        llm_client=_CitedReportLLM("https://example.com/hackernews-ai-policy"),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-hackernews-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "hackernews"
    assert result.output["raw_items"][0].metadata["hackernews_item_id"] == 123
    assert result.output["source_pipeline_metrics"].items_by_source_type == {"hackernews": 1}


def test_daily_intelligence_runner_live_collects_reddit_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="reddit",
                name="Reddit MachineLearning",
                source_type="reddit",
                url=REDDIT_BASE_URL,
                reliability="medium",
                topics=["ai", "machine learning"],
                metadata={"subreddit": "MachineLearning", "listing": "new"},
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        reddit_connector=RedditConnector(fetch_text=lambda url: REDDIT_LISTING),
        llm_client=_CitedReportLLM("https://example.com/reddit-ai-policy"),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-reddit-source")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["raw_items"][0].source_type.value == "reddit"
    assert result.output["raw_items"][0].metadata["subreddit"] == "MachineLearning"
    assert result.output["source_pipeline_metrics"].items_by_source_type == {"reddit": 1}


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
    assert metrics.sources_by_type == {"rss": 2}
    assert metrics.sources_by_reliability == {"high": 1, "medium": 1}
    assert metrics.fetched_by_type == {"rss": 1}
    assert metrics.failed_by_type == {"rss": 1}
    assert metrics.items_by_source_type == {"rss": 1}
    assert metrics.items_by_reliability == {"high": 1}
    assert result.output["source_coverage_report"].coverage_status == "partial"
    assert result.output["source_coverage_report"].selected_source_count == 2
    assert result.output["source_coverage_report"].fetched_source_count == 1
    assert result.output["source_coverage_report"].failed_source_count == 1
    assert result.output["source_coverage_report"].fetch_success_ratio == 0.5
    assert result.output["source_coverage_report"].failed_source_ids == ["failing"]
    assert result.output["failed_sources"][0]["source_id"] == "failing"
    assert result.output["failed_sources"][0]["source_name"] == "Failing"
    assert result.output["failed_sources"][0]["retryable"] is True
    failing_health = next(
        health for health in result.output["source_health_updates"] if health.source_id == "failing"
    )
    assert failing_health.source_name == "Failing"
    assert failing_health.url == "https://example.com/failing.xml"
    assert failing_health.failure_count_24h == 1
    assert failing_health.avg_latency_ms_24h >= 0
    source_notes = next(
        section for section in result.output["final_report"].sections if section["title"] == "Source Notes"
    )
    assert "1 source(s) failed" in source_notes["content"]
    assert "fetch_connection_error" in source_notes["content"]
    assert source_notes["sources"] == ["https://example.com/ai-policy"]

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["source_errors"] == "source_errors.json"
    assert manifest["artifacts"]["failed_sources"] == "failed_sources.json"
    assert manifest["artifacts"]["source_fetch_requests"] == "source_fetch_requests.json"
    assert manifest["artifacts"]["source_fetch_results"] == "source_fetch_results.json"
    assert manifest["artifacts"]["source_events"] == "source_events.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert manifest["artifacts"]["source_selection_report"] == "source_selection_report.json"
    assert manifest["artifacts"]["source_coverage_report"] == "source_coverage_report.json"
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 12
    assert manifest["source_artifacts"] == {
        "item_count": 1,
        "error_count": 1,
        "raw_content_count": 1,
        "fetch_request_count": 2,
        "fetch_result_count": 2,
        "total_count": 8,
        "parsed_items_count": 1,
    }

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
    assert any(
        event["event_type"] == "source_parse_started" and event["source_id"] == "failing"
        for event in source_events
    )
    assert any(
        event["event_type"] == "source_parse_succeeded" and event["source_id"] == "working"
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
    source_fetch_requests = json.loads((run_dir / "source_fetch_requests.json").read_text())
    assert [request["source_id"] for request in source_fetch_requests] == ["failing", "working"]
    assert [request["request_id"] for request in source_fetch_requests] == [
        result["request_id"] for result in source_fetch_results
    ]
    assert [result["source_id"] for result in source_fetch_results] == ["failing", "working"]
    assert source_fetch_results[0]["success"] is False
    assert source_fetch_results[0]["error_type"] == "fetch_connection_error"
    assert source_fetch_results[1]["success"] is True
    assert result.output["source_errors"][0].metadata["request_id"] == source_fetch_requests[0]["request_id"]
    assert result.output["failed_sources"][0]["metadata"]["request_id"] == source_fetch_requests[0]["request_id"]
    assert error_entry["request_id"] == source_fetch_requests[0]["request_id"]
    assert error_entry["request_ref"]["artifact_type"] == "source_fetch_request"
    assert error_entry["request_ref"]["artifact_id"] == "source-fetch-request-failing-source-fetch-0001-failing"
    assert error_entry["response_ref"]["artifact_type"] == "source_fetch_result"
    assert error_entry["response_ref"]["artifact_id"] == "source-fetch-result-failing-source-fetch-0001-failing"
    assert error_payload["request_ref"] == error_entry["request_ref"]

    coverage_report = json.loads((run_dir / "source_coverage_report.json").read_text(encoding="utf-8"))
    assert coverage_report["coverage_status"] == "partial"
    assert coverage_report["failed_source_ids"] == ["failing"]
    assert coverage_report["errors_by_type"] == {"fetch_connection_error": 1}
    assert error_payload["response_ref"] == error_entry["response_ref"]
    assert error_payload["error"]["request_ref"] == error_entry["request_ref"]
    assert error_payload["error"]["response_ref"] == error_entry["response_ref"]
    fetch_result_artifacts = [
        entry for entry in source_artifacts["entries"] if entry["artifact_type"] == "source_fetch_result"
    ]
    assert [entry["source_id"] for entry in fetch_result_artifacts] == ["failing", "working"]
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert any(section["title"] == "Source Notes" for section in report["sections"])


def test_daily_intelligence_runner_dispatches_github_mode_metadata(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="github-commits",
                name="GitHub Commits",
                source_type="github",
                url=GITHUB_API_URL,
                reliability="high",
                topics=["AI"],
                metadata={"repository": "owner/repo", "mode": "commits"},
            )
        ]
    )
    github_connector = _FakeGithubModeConnector()

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        github_connector=github_connector,
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-github-mode")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert github_connector.calls == [
        {
            "source_id": "github-commits",
            "repository": "owner/repo",
            "query": "AI policy",
            "limit": 1,
            "mode": "commits",
        }
    ]


def test_daily_intelligence_runner_dispatches_devto_source(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="devto-ai",
                name="dev.to AI",
                source_type="devto",
                url="https://dev.to/api",
                reliability="medium",
                topics=["AI"],
                metadata={"tag": "ai"},
            )
        ]
    )
    devto_connector = _FakeCommunityConnector()

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        devto_connector=devto_connector,
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-devto")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert devto_connector.calls == [{"source_id": "devto-ai", "tag": "ai", "limit": 1}]


def test_daily_intelligence_runner_persists_source_duplicate_groups(tmp_path) -> None:
    duplicate_feed = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Duplicates</title>
    <item>
      <title>AI policy update</title>
      <link>https://example.com/ai-policy?utm_source=a</link>
      <description>Policy summary.</description>
      <pubDate>Mon, 11 May 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>AI policy update</title>
      <link>https://example.com/ai-policy</link>
      <description>Policy summary.</description>
      <pubDate>Mon, 11 May 2026 03:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="duplicates",
                name="Duplicates",
                source_type="rss",
                url="https://example.com/duplicates.xml",
                reliability="high",
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=lambda url: duplicate_feed),
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=2, run_id="daily-duplicate-groups")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["source_pipeline_metrics"].duplicate_count == 1
    assert len(result.output["source_duplicate_groups"]) == 1
    group = result.output["source_duplicate_groups"][0]
    assert group["kept_item_id"]
    assert len(group["duplicate_item_ids"]) == 1
    assert "canonical_url_hash" in group["reasons"]

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["source_duplicate_groups"] == "source_duplicate_groups.json"
    persisted_groups = json.loads((run_dir / "source_duplicate_groups.json").read_text(encoding="utf-8"))
    assert persisted_groups == result.output["source_duplicate_groups"]


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
    assert manifest["artifacts"]["source_fetch_requests"] == "source_fetch_requests.json"
    assert manifest["artifacts"]["source_events"] == "source_events.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert manifest["artifacts"]["source_selection_report"] == "source_selection_report.json"
    assert manifest["artifacts"]["source_coverage_report"] == "source_coverage_report.json"
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

    coverage_report = json.loads((run_dir / "source_coverage_report.json").read_text(encoding="utf-8"))
    assert coverage_report["coverage_status"] == "empty"
    assert coverage_report["raw_item_count"] == 0
    assert coverage_report["failed_source_count"] == 1
    assert coverage_report["errors_by_type"]["all_sources_failed"] == 1

    source_events = json.loads((run_dir / "source_events.json").read_text(encoding="utf-8"))
    assert any(
        event["event_type"] == "source_fetch_failed"
        and event["metadata"]["error_type"] == "all_sources_failed"
        for event in source_events
    )

    source_artifacts = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    assert source_artifacts["item_count"] == 0
    assert source_artifacts["error_count"] == 2
    assert source_artifacts["fetch_request_count"] == 1
    assert source_artifacts["fetch_result_count"] == 1
    failing_error_entry = next(
        entry
        for entry in source_artifacts["entries"]
        if entry["artifact_type"] == "source_error" and entry["source_id"] == "failing"
    )
    assert failing_error_entry["request_ref"]["artifact_type"] == "source_fetch_request"
    assert failing_error_entry["response_ref"]["artifact_type"] == "source_fetch_result"
    aggregate_error_entry = next(
        entry
        for entry in source_artifacts["entries"]
        if entry["artifact_type"] == "source_error" and entry["source_id"] == "source_pipeline"
    )
    assert "request_ref" not in aggregate_error_entry
    assert "response_ref" not in aggregate_error_entry


def test_daily_intelligence_runner_live_rejects_fixture_source_registry(tmp_path) -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="fixture",
                name="Fixture",
                source_type="rss",
                url="fixture://ai",
                reliability="high",
                topics=["ai"],
            )
        ]
    )

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        llm_client=_FailIfCalledLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="live-fixture-rejected")

    assert result.status == WorkflowStatus.FAILED
    assert result.error is not None
    assert result.error["error_type"] == SourceConfigError.__name__
    assert "fixture URLs are not allowed" in result.error["message"]
    assert (Path(result.artifact_dir) / "error.json").exists()


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
    assert result.output["source_pipeline_metrics"].skipped_by_type == {"rss": 1}
    assert result.output["source_coverage_report"].coverage_status == "partial"
    assert result.output["source_coverage_report"].skipped_source_ids == ["cooling"]
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


def test_daily_intelligence_runner_skips_source_inside_fetch_interval(tmp_path) -> None:
    clock = {"now": datetime(2026, 5, 11, tzinfo=UTC)}
    health_manager = BasicSourceHealthManager(now=lambda: clock["now"])
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="fresh",
                name="Fresh",
                source_type="rss",
                url="https://example.com/fresh.xml",
                reliability="high",
                fetch_interval_seconds=3600,
                topics=["ai", "policy"],
            ),
            SourceDefinition(
                source_id="working",
                name="Working",
                source_type="rss",
                url="https://example.com/working.xml",
                reliability="high",
                topics=["ai", "policy"],
            ),
        ]
    )
    health_manager.record_success(
        "fresh",
        source_name="Fresh",
        url="https://example.com/fresh.xml",
    )
    clock["now"] = clock["now"] + timedelta(minutes=30)
    fetched_urls = []

    result = DailyIntelligenceRunner(
        artifact_root=tmp_path,
        source_registry=registry,
        feed_connector=FeedConnector(fetch_text=lambda url: fetched_urls.append(url) or RSS_FIXTURE),
        llm_client=_FakeReportLLM(),
        source_health_manager=health_manager,
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-fetch-interval")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert fetched_urls == ["https://example.com/working.xml"]
    assert result.output["skipped_sources"][0]["source_id"] == "fresh"
    assert result.output["skipped_sources"][0]["reason"] == "fetch_interval"
    assert result.output["skipped_sources"][0]["next_fetch_at"] == "2026-05-11T01:00:00Z"
    skipped_result = next(
        fetch_result
        for fetch_result in result.output["source_fetch_results"]
        if fetch_result.source_id == "fresh"
    )
    assert skipped_result.skipped is True
    assert skipped_result.skip_reason == "fetch_interval"
    assert skipped_result.metadata["skip"]["next_fetch_at"] == "2026-05-11T01:00:00Z"
    skipped_event = next(
        event
        for event in result.output["source_events"]
        if event.event_type == "source_fetch_skipped" and event.source_id == "fresh"
    )
    assert skipped_event.metadata["reason"] == "fetch_interval"


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
    assert "source_cooldown_started" in event_types
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


class _RegistrySyncConnector:
    def __init__(self) -> None:
        self.calls = []

    def fetch(self, source, *, limit=None):
        self.calls.append({"source_id": source.source_id, "limit": limit})
        return [
            RawSourceItem(
                source_item_id="raw-registry-sync",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Registry connector AI policy update",
                url="https://example.com/registry-sync",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                summary="Source-grounded summary.",
                raw_content="Source-grounded summary.",
            )
        ], []


class _ProtocolBackedSyncConnector:
    def __init__(self) -> None:
        self.calls = []

    def fetch(self, source, *, limit=None):
        self.calls.append({"source_id": source.source_id, "limit": limit})
        return [
            RawSourceItem(
                source_item_id="raw-registry-protocol",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Protocol connector AI policy update",
                url="https://example.com/registry-protocol",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                summary="Source-grounded summary.",
                raw_content="Source-grounded summary.",
            )
        ], []


class _DuplicateReportLLM:
    def complete(self, request):
        return LLMResponse(
            content=json.dumps(
                {
                    "title": "Duplicate Live Report",
                    "sections": [
                        {
                            "title": "Summary",
                            "content": "Policy summary.",
                            "sources": ["https://example.com/ai-policy"],
                        },
                        {
                            "title": "Repeated",
                            "content": "Policy summary.",
                            "sources": ["https://example.com/ai-policy"],
                        },
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


class _FakeGithubModeConnector:
    def __init__(self) -> None:
        self.calls = []

    def fetch(self, source, *, repository, query, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "repository": repository,
                "query": query,
                "limit": limit,
                "mode": source.metadata.get("mode"),
            }
        )
        return [
            RawSourceItem(
                source_item_id="raw-github-commit",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Commit title",
                url="https://github.com/owner/repo/commit/abcdef1",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                published_at=datetime(2026, 5, 11, tzinfo=UTC),
                summary="Commit summary",
                raw_content="{}",
                authors=["alice"],
                tags=["commit"],
                language="en",
                metadata={"github_surface": "commits", "repository": repository},
            )
        ], []


class _FakeCommunityConnector:
    def __init__(self) -> None:
        self.calls = []

    def fetch(self, source, *, tag, limit):
        self.calls.append({"source_id": source.source_id, "tag": tag, "limit": limit})
        return [
            RawSourceItem(
                source_item_id="raw-community",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Community article",
                url="https://dev.to/example/community-article",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                published_at=datetime(2026, 5, 11, tzinfo=UTC),
                summary="Community summary",
                raw_content="{}",
                authors=["alice"],
                tags=["devto", "ai"],
                language="en",
                metadata={"community_surface": "devto"},
            )
        ], []


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


class _UnsupportedClaimLLM:
    def complete(self, request):
        return LLMResponse(
            content=json.dumps(
                {
                    "title": "Unsupported Claim Live Report",
                    "sections": [
                        {
                            "title": "Summary",
                            "content": (
                                "Policy summary. "
                                "The vendor completed a quantum chip acquisition."
                            ),
                            "sources": ["https://example.com/ai-policy"],
                        }
                    ],
                }
            ),
            usage=TokenUsage(input_tokens=3, output_tokens=4),
        )


class _FailIfCalledLLM:
    def complete(self, request):
        raise AssertionError("LLM should not be called when all sources fail")

