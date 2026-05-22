from __future__ import annotations

from business.boards._artifact_publisher import BOARD_ARTIFACTS, BoardArtifactPublisher


def build_paper_radar_artifact_publisher() -> BoardArtifactPublisher:
    return BoardArtifactPublisher("paper_radar")


__all__ = ["BOARD_ARTIFACTS", "BoardArtifactPublisher", "build_paper_radar_artifact_publisher"]
