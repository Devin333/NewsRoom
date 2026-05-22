from __future__ import annotations

from business.boards._artifact_publisher import BOARD_ARTIFACTS, BoardArtifactPublisher


def build_community_pulse_artifact_publisher() -> BoardArtifactPublisher:
    return BoardArtifactPublisher("community_pulse")


__all__ = ["BOARD_ARTIFACTS", "BoardArtifactPublisher", "build_community_pulse_artifact_publisher"]
