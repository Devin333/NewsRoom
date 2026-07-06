from __future__ import annotations

from typing import Any


def request_filters(request: Any) -> dict[str, Any]:
    raw = getattr(request, "filters", {}) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def merge_request_filters(request: Any, extra_filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = request_filters(request)
    if extra_filters:
        filters.update(extra_filters)
    return filters


__all__ = ["merge_request_filters", "request_filters"]
