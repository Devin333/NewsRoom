from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from framework.harness.rag.models import RAGTranscript
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, utc_now


DEFAULT_TRANSCRIPT_ROOT = Path(".newsroom") / "rag" / "transcripts"
SCHEMA_VERSION = "newsroom.paper_rag_transcript.v1"


@dataclass(frozen=True)
class PaperRagTranscriptArtifact:
    transcript_id: str
    path: Path
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transcript_id": self.transcript_id,
            "path": self.path.as_posix(),
        }


class PaperRagTranscriptFileStore:
    """File-backed audit store for gated Paper RAG transcripts."""

    def __init__(self, root: str | Path = DEFAULT_TRANSCRIPT_ROOT) -> None:
        self.root = Path(root)

    def persist(self, transcript: RAGTranscript | Mapping[str, Any]) -> PaperRagTranscriptArtifact:
        payload = _coerce_transcript_payload(transcript)
        transcript_id = _transcript_id(payload)
        path = self.path_for(transcript_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "transcript_id": transcript_id,
            "stored_at": format_datetime(utc_now()),
            "transcript": payload,
        }
        path.write_text(
            json.dumps(to_jsonable(envelope), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return PaperRagTranscriptArtifact(transcript_id=transcript_id, path=path)

    def load(self, transcript_id_or_path: str | Path) -> dict[str, Any]:
        path = self.resolve(transcript_id_or_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("RAG transcript artifact must be a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported RAG transcript artifact schema: {payload.get('schema_version')!r}")
        transcript = payload.get("transcript")
        if not isinstance(transcript, dict):
            raise ValueError("RAG transcript artifact requires a transcript object")
        return payload

    def transcript_payload(self, transcript_id_or_path: str | Path) -> dict[str, Any]:
        return dict(self.load(transcript_id_or_path)["transcript"])

    def resolve(self, transcript_id_or_path: str | Path) -> Path:
        if _looks_like_path(transcript_id_or_path):
            raw = Path(transcript_id_or_path)
            if raw.exists():
                return raw
            raise FileNotFoundError(f"RAG transcript artifact not found: {transcript_id_or_path}")
        path = self.path_for(str(transcript_id_or_path))
        if not path.exists():
            raise FileNotFoundError(f"RAG transcript artifact not found: {transcript_id_or_path}")
        return path

    def path_for(self, transcript_id: str) -> Path:
        normalized = _normalize_transcript_id(transcript_id)
        digest = sha256(normalized.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"


def _coerce_transcript_payload(transcript: RAGTranscript | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(transcript, RAGTranscript):
        return transcript.to_dict()
    return dict(transcript)


def _transcript_id(payload: Mapping[str, Any]) -> str:
    return _normalize_transcript_id(str(payload.get("transcript_id") or ""))


def _normalize_transcript_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("transcript_id is required")
    return normalized


def _looks_like_path(value: str | Path) -> bool:
    if isinstance(value, Path):
        return True
    text = str(value)
    if "://" in text:
        return False
    return text.endswith(".json") or "\\" in text or "/" in text


__all__ = [
    "DEFAULT_TRANSCRIPT_ROOT",
    "SCHEMA_VERSION",
    "PaperRagTranscriptArtifact",
    "PaperRagTranscriptFileStore",
]
