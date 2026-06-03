from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.foundation.value_normalization import field_value, list_value


@dataclass(frozen=True)
class GroundedWriterEvidenceItemView:
    evidence_id: str
    title: str
    source_urls: tuple[str, ...]

    @classmethod
    def from_item(cls, item: Any) -> "GroundedWriterEvidenceItemView":
        source_url = field_value(item, "source_url", default="")
        source_urls = [
            source_url,
            *list_value(field_value(item, "source_urls", default=[])),
        ]
        return cls(
            evidence_id=str(field_value(item, "evidence_id", default="") or ""),
            title=str(field_value(item, "title", default="") or ""),
            source_urls=_stable_source_urls(source_urls),
        )


@dataclass(frozen=True)
class GroundedWriterEvidenceSelection:
    evidence_ids: tuple[str, ...]
    items: tuple[GroundedWriterEvidenceItemView, ...]

    @property
    def primary_title(self) -> str:
        if not self.items:
            return ""
        return self.items[0].title

    def source_urls(self, leading_sources: list[Any]) -> list[str]:
        return list(
            _stable_source_urls(
                [
                    *leading_sources,
                    *[
                        source_url
                        for item in self.items
                        for source_url in item.source_urls
                    ],
                ]
            )
        )


@dataclass(frozen=True)
class GroundedWriterEvidenceBundleView:
    items_by_id: dict[str, GroundedWriterEvidenceItemView]

    @classmethod
    def from_inputs(
        cls,
        inputs: dict[str, Any],
    ) -> "GroundedWriterEvidenceBundleView | None":
        for key in ("evidence_bundle", "bundle"):
            if key in inputs:
                return cls.from_bundle(inputs[key])
        request = inputs.get("request")
        if isinstance(request, dict):
            for key in ("evidence_bundle", "bundle"):
                if key in request:
                    return cls.from_bundle(request[key])
        return None

    @classmethod
    def from_bundle(
        cls,
        evidence_bundle: Any,
    ) -> "GroundedWriterEvidenceBundleView | None":
        if evidence_bundle is None:
            return None
        raw_items = field_value(evidence_bundle, "items", default=None)
        if raw_items is None:
            return None
        items_by_id: dict[str, GroundedWriterEvidenceItemView] = {}
        for item in list_value(raw_items):
            item_view = GroundedWriterEvidenceItemView.from_item(item)
            if item_view.evidence_id:
                items_by_id[item_view.evidence_id] = item_view
        return cls(items_by_id=items_by_id)

    def select(self, evidence_ids: list[Any]) -> GroundedWriterEvidenceSelection:
        selected_ids = tuple(
            evidence_id
            for value in evidence_ids
            if (evidence_id := str(value).strip()) and evidence_id in self.items_by_id
        )
        return GroundedWriterEvidenceSelection(
            evidence_ids=selected_ids,
            items=tuple(self.items_by_id[evidence_id] for evidence_id in selected_ids),
        )


def _stable_source_urls(values: list[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


__all__ = [
    "GroundedWriterEvidenceBundleView",
    "GroundedWriterEvidenceItemView",
    "GroundedWriterEvidenceSelection",
]
