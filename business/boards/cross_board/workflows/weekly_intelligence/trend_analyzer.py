from __future__ import annotations

from collections import Counter
from typing import Any


class WeeklyTrendAnalyzer:
    def analyze(self, source_reports: list[dict[str, Any]]) -> dict[str, Any]:
        entity_counts = Counter()
        topic_counts = Counter()
        for report in source_reports:
            text = _report_text(report)
            for entity in _known_entities(text):
                entity_counts[entity] += 1
            for topic in _topics(text):
                topic_counts[topic] += 1
        recurring = [
            {"entity": entity, "count": count}
            for entity, count in entity_counts.most_common()
            if count >= 2
        ]
        emerging = [
            {"topic": topic, "count": count}
            for topic, count in topic_counts.most_common(6)
        ]
        high_confidence = [
            {
                "trend_id": f"weekly-trend-{index}",
                "topic": item["topic"],
                "confidence": min(1.0, 0.55 + item["count"] * 0.12),
                "source_report_count": item["count"],
            }
            for index, item in enumerate(emerging, start=1)
            if item["count"] >= 1
        ]
        weak_signal = [
            {
                "trend_id": f"weekly-weak-{index}",
                "topic": item["topic"],
                "confidence": 0.42,
                "source_report_count": item["count"],
            }
            for index, item in enumerate(emerging, start=1)
            if item["count"] == 1
        ]
        return {
            "recurring_entities": recurring,
            "emerging_topics": emerging,
            "declining_topics": [],
            "high_confidence_trends": high_confidence,
            "weak_signal_trends": weak_signal,
            "anomaly_trends": _anomalies(source_reports),
        }


def _report_text(report: dict[str, Any]) -> str:
    parts = [str(report.get("title") or ""), str(report.get("report_markdown") or "")]
    for section in report.get("sections") or []:
        if isinstance(section, dict):
            parts.append(str(section.get("title") or ""))
            parts.append(str(section.get("content") or ""))
    return " ".join(parts)


def _known_entities(text: str) -> list[str]:
    hints = ["OpenAI", "Anthropic", "Google", "Meta", "Microsoft", "Agent Memory", "LangChain", "RAG", "MCP"]
    lowered = text.casefold()
    return [hint for hint in hints if hint.casefold() in lowered]


def _topics(text: str) -> list[str]:
    lowered = text.casefold()
    candidates = {
        "agent_memory": ["agent memory", "memory"],
        "workflow": ["workflow", "orchestration"],
        "evidence": ["evidence", "citation"],
        "policy": ["policy", "governance"],
        "benchmark": ["benchmark", "evaluation"],
        "release": ["release", "launch"],
    }
    return [topic for topic, needles in candidates.items() if any(needle in lowered for needle in needles)] or ["general"]


def _anomalies(source_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies = []
    for report in source_reports:
        if report.get("quality_score") is not None and float(report["quality_score"]) < 0.5:
            anomalies.append(
                {
                    "report_id": report.get("report_id"),
                    "anomaly_type": "low_quality_daily_report",
                    "quality_score": report.get("quality_score"),
                }
            )
    return anomalies


__all__ = ["WeeklyTrendAnalyzer"]
