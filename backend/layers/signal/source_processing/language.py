from __future__ import annotations

import re


_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
_ENGLISH_STOPWORDS = {
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def detect_language(text: str) -> str | None:
    content = " ".join(text.split())
    if not content:
        return None

    zh_count = _count_range(content, 0x4E00, 0x9FFF)
    ja_count = _count_range(content, 0x3040, 0x30FF)
    ko_count = _count_range(content, 0xAC00, 0xD7AF)
    if zh_count >= 2 and zh_count >= ja_count and zh_count >= ko_count:
        return "zh"
    if ja_count >= 2 and ja_count >= ko_count:
        return "ja"
    if ko_count >= 2:
        return "ko"

    words = [word.casefold() for word in _LATIN_WORD_RE.findall(content)]
    stopword_hits = {word for word in words if word in _ENGLISH_STOPWORDS}
    if len(words) >= 8 and len(stopword_hits) >= 2:
        return "en"
    return None


def _count_range(text: str, start: int, end: int) -> int:
    return sum(1 for char in text if start <= ord(char) <= end)
