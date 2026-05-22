from __future__ import annotations


def test_daily_artifact_publisher_uses_section_dispatcher() -> None:
    from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import (
        DailyIntelligenceArtifactPublisher,
    )
    from business.boards.cross_board.workflows.daily_intelligence.artifact_sections import (
        publish_daily_artifact_sections,
    )

    assert DailyIntelligenceArtifactPublisher.publisher_id == "daily_intelligence"
    assert callable(publish_daily_artifact_sections)
