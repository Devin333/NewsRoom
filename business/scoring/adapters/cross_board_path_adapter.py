from __future__ import annotations

from business.boards.cross_board.graph_models import CrossBoardPath
from framework.scoring import FeatureVector, ScoringTarget


def cross_board_path_scoring_target(path: CrossBoardPath) -> ScoringTarget:
    return ScoringTarget.from_object(
        path,
        target_id=path.path_id,
        target_type="cross_board_path",
        metadata={
            "technology_ref": path.technology_ref.model_dump(mode="json"),
            "board_sequence": list(path.board_sequence),
        },
    )


def cross_board_path_feature_vector(path: CrossBoardPath) -> FeatureVector:
    from business.scoring.features.cross_board_path_features import cross_board_path_features

    return FeatureVector.from_scores(
        cross_board_path_features(path),
        source="cross_board_path",
        metadata={"path_id": path.path_id, "board_sequence": list(path.board_sequence)},
    )
