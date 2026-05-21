from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

from business.foundation import canonicalize_url


def normalize_url(url: str | None) -> str:
    return canonicalize_url(url or "")


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = fallback or datetime.now(UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def detect_language(title: str | None, content: str | None = None) -> str:
    text = f"{title or ''} {content or ''}"
    if not text:
        return "en"
    zh_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return "zh" if zh_count / max(1, len(text)) > 0.3 else "en"
