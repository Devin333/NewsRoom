from __future__ import annotations

from typing import Any


def build_paper_radar_quality_summary(output: Any) -> dict[str, Any]:
    quality = getattr(output, "quality_summary", None)
    if hasattr(quality, "to_dict"):
        return quality.to_dict()
    if isinstance(quality, dict):
        return dict(quality)
    return {"status": "unchecked", "score": None}


__all__ = ["build_paper_radar_quality_summary"]
