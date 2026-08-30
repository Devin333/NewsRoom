from __future__ import annotations

from backend.foundation import BoardType
from backend.foundation.models.source import RawSourceItem
from backend.layers.signal.models import RawSignalInput
from backend.layers.signal.normalizer import clean_text, normalize_datetime, normalize_url
from backend.layers.signal.signal_classifier import board_type_for_signal, signal_type_for_source


def raw_signal_input_to_source_item(raw: RawSignalInput) -> RawSourceItem:
    payload = dict(raw.raw_payload)
    signal_type = signal_type_for_source(raw.source_type)
    board_type = raw.board_hint or board_type_for_signal(signal_type)
    title = clean_text(payload.get("title") or payload.get("full_name") or payload.get("headline") or "")
    url = normalize_url(payload.get("url") or payload.get("link") or payload.get("html_url") or payload.get("pdf_url") or "")
    summary = clean_text(payload.get("summary") or payload.get("description") or payload.get("abstract") or payload.get("text") or "")
    content = clean_text(payload.get("content") or payload.get("readme") or payload.get("content_html") or summary)
    return RawSourceItem(
        source_item_id=str(payload.get("source_item_id") or payload.get("id") or payload.get("thread_id") or payload.get("paper_id") or title or "item"),
        source_id=str(payload.get("source_id") or raw.source_name),
        source_name=raw.source_name,
        source_type=raw.source_type.value,
        title=title or "Untitled",
        url=url or "manual://signal",
        fetched_at=raw.collected_at,
        published_at=normalize_datetime(payload.get("published_at") or payload.get("published") or payload.get("created_at"), fallback=raw.collected_at),
        summary=summary or None,
        raw_content=content or None,
        authors=_string_list(payload.get("authors") or payload.get("author")),
        tags=_string_list(payload.get("tags") or payload.get("categories") or payload.get("topics")),
        language=str(payload.get("language") or "en"),
        metadata={
            **payload,
            "board_hint": board_type.value if isinstance(board_type, BoardType) else str(board_type),
            "source_type": raw.source_type.value,
        },
    )


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []
