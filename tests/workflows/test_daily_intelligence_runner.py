import json
from pathlib import Path

from core.framework.llm import LLMResponse, TokenUsage
from core.framework.specs import WorkflowStatus
from domain.sources import SourceDefinition
from sources import SourceRegistry
from sources.connectors import FeedConnector
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
    assert manifest["artifacts"]["citation_check_result"] == "citation_check_result.json"
    assert manifest["artifacts"]["editor_review"] == "editor_review.json"
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert (run_dir / "report.md").exists()


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
        llm_client=_FakeReportLLM(),
    ).run(profile="live", topic="AI policy", source_limit=1, run_id="daily-live-injected")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["final_report"].title == "Injected Live Report"
    assert (Path(result.artifact_dir) / "report.json").exists()


class _FakeReportLLM:
    def complete(self, request):
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
