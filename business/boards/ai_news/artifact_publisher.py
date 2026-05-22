from __future__ import annotations

from business.boards._artifact_publisher import BOARD_ARTIFACTS, BoardArtifactPublisher


def build_ai_news_artifact_publisher() -> BoardArtifactPublisher:
    return BoardArtifactPublisher("ai_news")


__all__ = ["BOARD_ARTIFACTS", "BoardArtifactPublisher", "build_ai_news_artifact_publisher"]
