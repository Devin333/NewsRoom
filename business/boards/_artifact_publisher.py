from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from framework.artifacts.models import ArtifactRef
from framework.workflow import ArtifactPublishContext, ArtifactPublishPhase, register_manifest_artifact_once


BOARD_ARTIFACTS: dict[str, str] = {
    "board_output": "board_output.json",
    "cards": "cards.json",
    "detail_pages": "detail_pages.json",
    "insights": "insights.json",
    "quality_summary": "quality_summary.json",
    "subscription_payload": "subscription_payload.json",
    "feedback_events": "feedback_events.json",
    "learning_signals": "learning_signals.json",
    "improvement_recommendations": "improvement_recommendations.json",
    "improvement_proposals": "improvement_proposals.json",
    "applied_overrides": "applied_overrides.json",
    "improvement_measurement": "improvement_measurement.json",
}


class BoardArtifactPublisher:
    publisher_id = "board_productized"

    def __init__(self, board_type: str) -> None:
        self.board_type = board_type

    def supports(self, context: ArtifactPublishContext) -> bool:
        return (
            context.phase == ArtifactPublishPhase.TERMINAL
            and context.workflow.workflow_id == f"{self.board_type}-productized-board"
        )

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        metadata = _artifact_metadata(context, self.board_type)
        context.manifest["business_productization"] = metadata
        for key, relative_path in BOARD_ARTIFACTS.items():
            if key not in context.output:
                continue
            refs.append(_write_json_artifact(context, key, relative_path, context.output[key], metadata))
        summary = context.output.get("summary_md")
        if isinstance(summary, str):
            refs.append(_write_text_artifact(context, "summary", "summary.md", summary, metadata))
        return refs


def _write_json_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    payload: Any,
    metadata: dict[str, Any],
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_json(context.run_id, relative_path, payload)
    return _artifact_ref(context, artifact_key, relative_path, path, "application/json", metadata)


def _write_text_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    payload: str,
    metadata: dict[str, Any],
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_text(context.run_id, relative_path, payload)
    return _artifact_ref(context, artifact_key, relative_path, path, "text/markdown", metadata)


def _artifact_ref(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    path: Path,
    content_type: str,
    metadata: dict[str, Any],
) -> ArtifactRef:
    data = path.read_bytes()
    return ArtifactRef(
        artifact_id=artifact_key,
        run_id=context.run_id,
        artifact_type=artifact_key,
        path=relative_path,
        content_type=content_type,
        size_bytes=len(data),
        checksum=sha256(data).hexdigest(),
        redacted=True,
        metadata={
            "artifact_key": artifact_key,
            "workflow_id": context.workflow.workflow_id,
            "workflow_version": context.workflow.version,
            **metadata,
        },
    )


def _artifact_metadata(context: ArtifactPublishContext, board_type: str) -> dict[str, Any]:
    quality = context.output.get("quality_summary")
    subscription = context.output.get("subscription_payload")
    cards = context.output.get("cards")
    source_count = len(context.request.get("signals") or [])
    return {
        "board_type": board_type,
        "run_id": context.run_id,
        "topic": context.request.get("topic"),
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "schema_version": "business.board.productized.v1",
        "source_count": source_count,
        "card_count": len(cards) if isinstance(cards, list) else 0,
        "quality_score": quality.get("score") if isinstance(quality, dict) else None,
        "subscription_ready": bool(subscription.get("delivery_hints", {}).get("subscription_ready")) if isinstance(subscription, dict) else False,
        "improvement_ready": bool(context.output.get("improvement_recommendations") is not None),
    }


__all__ = ["BOARD_ARTIFACTS", "BoardArtifactPublisher"]
