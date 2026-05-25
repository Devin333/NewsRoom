from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from business.boards.paper_radar.public_mapper import sanitize_public_payload


PAPERS_READER_CACHE_DIR_ENV = "NEWSROOM_PAPERS_READER_CACHE_DIR"
PAPERS_TEXT_EXTRACTION_DIR_ENV = "NEWSROOM_PAPERS_TEXT_EXTRACTION_DIR"

PUBLIC_EXTRACTION_SECTION_FIELDS = {
    "title",
    "level",
    "pageStart",
    "pageEnd",
    "textExcerpt",
    "summary",
    "sectionType",
}


class PaperReaderCacheRepository:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = _runtime_dir(
            configured_path=cache_dir,
            env_name=PAPERS_READER_CACHE_DIR_ENV,
            default_parts=("reader-cache",),
        )

    def read(self, paper_id: str, source_hash: str) -> Mapping[str, Any] | None:
        payload = _read_json_object(self.path_for(paper_id))
        if payload is None:
            return None
        if _text(payload.get("paperId")) != paper_id or _text(payload.get("sourceHash")) != source_hash:
            return None
        reader_payload = payload.get("payload")
        if not isinstance(reader_payload, Mapping):
            reader_payload = payload
        sanitized = sanitize_public_payload(reader_payload)
        return dict(sanitized) if isinstance(sanitized, Mapping) else None

    def write(
        self,
        paper_id: str,
        source_hash: str,
        payload: Mapping[str, Any],
        *,
        cached_at: str,
        base_source_hash: str | None = None,
    ) -> bool:
        sanitized = sanitize_public_payload(payload)
        if not isinstance(sanitized, Mapping):
            return False
        record: dict[str, Any] = {
            "paperId": paper_id,
            "sourceHash": source_hash,
            "cachedAt": cached_at,
            "payload": dict(sanitized),
        }
        if base_source_hash:
            record["baseSourceHash"] = base_source_hash
        return _write_json_object(self.path_for(paper_id), record)

    def path_for(self, paper_id: str) -> Path:
        return self.cache_dir / f"{_safe_file_key(paper_id)}.json"


class TextExtractionRepository:
    def __init__(self, extraction_dir: str | Path | None = None) -> None:
        self.extraction_dir = _runtime_dir(
            configured_path=extraction_dir,
            env_name=PAPERS_TEXT_EXTRACTION_DIR_ENV,
            default_parts=("text-extractions",),
        )

    def read_sections(self, paper_id: str, source_hash: str) -> tuple[Mapping[str, Any], ...]:
        payload = _read_json_object(self.path_for(paper_id))
        if payload is None:
            return ()
        if _text(payload.get("paperId")) != paper_id or _text(payload.get("sourceHash")) != source_hash:
            return ()
        sections: list[Mapping[str, Any]] = []
        for item in _sequence(payload.get("sections")):
            if not isinstance(item, Mapping):
                continue
            sanitized = sanitize_public_payload(item)
            if not isinstance(sanitized, Mapping):
                continue
            public_section = {
                key: sanitized[key]
                for key in PUBLIC_EXTRACTION_SECTION_FIELDS
                if key in sanitized and sanitized[key] not in (None, "", [], {})
            }
            if _text(public_section.get("textExcerpt")) or _text(public_section.get("summary")):
                sections.append(public_section)
        return tuple(sections)

    def path_for(self, paper_id: str) -> Path:
        return self.extraction_dir / f"{_safe_file_key(paper_id)}.json"


def reader_cache_source_hash(base_source_hash: str, extraction_sections: Sequence[Mapping[str, Any]]) -> str:
    import hashlib

    payload = {
        "baseSourceHash": base_source_hash,
        "extractionSections": sanitize_public_payload(list(extraction_sections)),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _runtime_dir(*, configured_path: str | Path | None, env_name: str, default_parts: Sequence[str]) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(env_name)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / Path(*default_parts)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json_object(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _write_json_object(path: Path, payload: Mapping[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _safe_file_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    if normalized:
        return normalized[:120]
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
