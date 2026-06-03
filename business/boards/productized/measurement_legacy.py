from __future__ import annotations

from typing import Any


def legacy_deduplication_result_from_board_result(result: Any) -> dict[str, Any] | None:
    metadata = getattr(result, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return None
    productized_state = metadata.get("productized_run_state")
    if (
        isinstance(productized_state, dict)
        and isinstance(productized_state.get("deduplication_result"), dict)
    ):
        return dict(productized_state["deduplication_result"])
    dedupe = metadata.get("deduplication_result")
    return dict(dedupe) if isinstance(dedupe, dict) else None


__all__ = ["legacy_deduplication_result_from_board_result"]
