from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from business.foundation.value_normalization import field_value, list_value


@dataclass(frozen=True)
class RewriteEvidenceItemView:
    source_url: str
    title: str
    summary: str

    @classmethod
    def from_item(cls, item: Any) -> "RewriteEvidenceItemView":
        return cls(
            source_url=str(field_value(item, "source_url", default="") or ""),
            title=str(field_value(item, "title", default="") or ""),
            summary=str(field_value(item, "summary", default="") or ""),
        )

    @property
    def match_text(self) -> str:
        return f"{self.title} {self.summary}"


@dataclass(frozen=True)
class RewriteEvidenceLookupView:
    items: tuple[RewriteEvidenceItemView, ...]

    @classmethod
    def from_bundle(cls, evidence_bundle: Any) -> "RewriteEvidenceLookupView":
        return cls(
            items=tuple(
                RewriteEvidenceItemView.from_item(item)
                for item in list_value(field_value(evidence_bundle, "items", default=[]))
            )
        )

    def matching_source_urls(self, content: str) -> list[str]:
        return sorted(
            item.source_url
            for item in self.items
            if item.source_url and _token_overlap(content, item.match_text) >= 0.25
        )


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", left.casefold())
        if len(token) > 2
    }
    if not left_tokens:
        return 0.0
    right_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", right.casefold())
        if len(token) > 2
    }
    if not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


__all__ = ["RewriteEvidenceItemView", "RewriteEvidenceLookupView"]
