from __future__ import annotations

from business.boards.productized import ProductizedArtifactMetadataService
from business.foundation import BoardType


def test_productized_artifact_metadata_service_builds_step_outputs() -> None:
    result = ProductizedArtifactMetadataService().build_outputs(
        board_type=BoardType.AI_NEWS,
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
