from __future__ import annotations

from business.boards.productized import ProductizedArtifactMetadataService
from business.foundation import BoardType


def test_productized_artifact_metadata_service_builds_step_outputs() -> None:
    result = ProductizedArtifactMetadataService(board_type=BoardType.AI_NEWS).build_outputs(
        request={"run_id": "artifact-run", "topic": "Agent Memory", "signals": [{"id": "sig-1"}]},
        cards=[{"card_id": "card-1"}],
        quality_summary={"score": 0.88},
        subscription_payload={"delivery_hints": {"subscription_ready": True}},
    )

    metadata = result["artifact_metadata"]
    assert metadata["schema_version"] == "business.board.productized.v1"
    assert metadata["run_id"] == "artifact-run"
    assert metadata["source_count"] == 1
    assert metadata["card_count"] == 1
    assert metadata["quality_score"] == 0.88
    assert metadata["subscription_ready"] is True


def test_productized_artifact_metadata_service_keeps_explicit_board_type_compatibility() -> None:
    result = ProductizedArtifactMetadataService().build_outputs(
        board_type=BoardType.PROJECT_RADAR,
        request={"run_id": "artifact-compat"},
        cards=[],
        quality_summary={},
        subscription_payload={},
    )

    assert result["artifact_metadata"]["board_type"] == "project_radar"


def test_productized_artifact_metadata_service_requires_board_type_for_outputs() -> None:
    try:
        ProductizedArtifactMetadataService().build_outputs(
            request={},
            cards=[],
            quality_summary={},
            subscription_payload={},
        )
    except ValueError as exc:
        assert "board_type" in str(exc)
    else:
        raise AssertionError("expected board_type validation error")
