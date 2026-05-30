from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Literal, Protocol


DEFAULT_PAPER_USER_STATE_PATH = ".newsroom/papers/user-state.json"
ReadingStatus = Literal["unread", "reading", "finished"]


@dataclass(frozen=True)
class PaperUserState:
    userId: str
    paperId: str
    favorite: bool = False
    subscribed: bool = False
    readingStatus: ReadingStatus = "unread"
    currentPage: int | None = None
    progressPercent: int = 0
    lastReadAt: datetime | None = None
    updatedAt: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        updated_at = self.updatedAt or datetime.now(UTC)
        payload = {
            "userId": self.userId,
            "paperId": self.paperId,
            "favorite": self.favorite,
            "subscribed": self.subscribed,
            "readingStatus": self.readingStatus,
            "progressPercent": self.progressPercent,
            "updatedAt": _format_datetime(updated_at),
        }
        if self.currentPage is not None:
            payload["currentPage"] = self.currentPage
        if self.lastReadAt is not None:
            payload["lastReadAt"] = _format_datetime(self.lastReadAt)
        return payload

    @classmethod
    def default(cls, *, user_id: str, paper_id: str) -> "PaperUserState":
        now = datetime.now(UTC)
        return cls(userId=user_id, paperId=paper_id, updatedAt=now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PaperUserState":
        return cls(
            userId=str(payload["userId"]),
            paperId=str(payload["paperId"]),
            favorite=bool(payload.get("favorite", False)),
            subscribed=bool(payload.get("subscribed", False)),
            readingStatus=_reading_status(payload.get("readingStatus") or "unread"),
            currentPage=_optional_int(payload.get("currentPage")),
            progressPercent=_clamp_progress(payload.get("progressPercent", 0)),
            lastReadAt=_parse_optional_datetime(payload.get("lastReadAt")),
            updatedAt=_parse_optional_datetime(payload.get("updatedAt")),
        )


class PaperUserStateRepository(Protocol):
    def get_state(self, user_id: str, paper_id: str) -> PaperUserState | None: ...
    def list_states(self, user_id: str, paper_ids: list[str] | None = None) -> list[PaperUserState]: ...
    def upsert_state(self, state: PaperUserState) -> PaperUserState: ...


class LocalJsonPaperUserStateRepository:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("NEWSROOM_PAPER_USER_STATE_PATH") or DEFAULT_PAPER_USER_STATE_PATH)

    def get_state(self, user_id: str, paper_id: str) -> PaperUserState | None:
        return self._read_records().get(_state_key(user_id, paper_id))

    def list_states(self, user_id: str, paper_ids: list[str] | None = None) -> list[PaperUserState]:
        records = [state for state in self._read_records().values() if state.userId == user_id]
        if paper_ids is not None:
            wanted = set(paper_ids)
            records = [state for state in records if state.paperId in wanted]
        return sorted(records, key=lambda item: item.paperId)

    def upsert_state(self, state: PaperUserState) -> PaperUserState:
        records = self._read_records()
        records[_state_key(state.userId, state.paperId)] = state
        self._write_records(records)
        return state

    def _read_records(self) -> dict[str, PaperUserState]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        states = [PaperUserState.from_dict(item) for item in payload.get("states", [])]
        return {_state_key(state.userId, state.paperId): state for state in states}

    def _write_records(self, records: dict[str, PaperUserState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": "paper_user_state.v1",
            "states": [
                record.to_dict()
                for record in sorted(records.values(), key=lambda item: (item.userId, item.paperId))
            ],
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.path)


class PaperUserStateApplicationService:
    def __init__(
        self,
        repository: PaperUserStateRepository | None = None,
        *,
        store_path: str | Path | None = None,
    ) -> None:
        self.repository = repository or LocalJsonPaperUserStateRepository(store_path)

    def get_state(self, *, user_id: str, paper_id: str) -> PaperUserState:
        return self.repository.get_state(user_id, paper_id) or PaperUserState.default(user_id=user_id, paper_id=paper_id)

    def list_states(self, *, user_id: str, paper_ids: list[str] | None = None) -> list[PaperUserState]:
        existing = {state.paperId: state for state in self.repository.list_states(user_id, paper_ids)}
        if paper_ids is None:
            return list(existing.values())
        return [existing.get(paper_id) or PaperUserState.default(user_id=user_id, paper_id=paper_id) for paper_id in paper_ids]

    def patch_state(self, *, user_id: str, paper_id: str, patch: dict[str, Any]) -> PaperUserState:
        current = self.get_state(user_id=user_id, paper_id=paper_id)
        now = datetime.now(UTC)
        next_state = current
        if "favorite" in patch:
            next_state = replace(next_state, favorite=bool(patch["favorite"]))
        if "subscribed" in patch:
            next_state = replace(next_state, subscribed=bool(patch["subscribed"]))
        if "readingStatus" in patch:
            next_state = replace(next_state, readingStatus=_reading_status(patch["readingStatus"]))
        if "currentPage" in patch:
            current_page = _optional_int(patch["currentPage"])
            if current_page is not None and current_page < 1:
                raise ValueError("currentPage must be greater than zero")
            next_state = replace(next_state, currentPage=current_page)
        if "progressPercent" in patch:
            next_state = replace(next_state, progressPercent=_progress_percent(patch["progressPercent"]))
        if next_state.readingStatus != "unread" or next_state.currentPage is not None or next_state.progressPercent > 0:
            next_state = replace(next_state, lastReadAt=now)
        if next_state.progressPercent >= 100:
            next_state = replace(next_state, readingStatus="finished")
        next_state = replace(next_state, updatedAt=now)
        return self.repository.upsert_state(next_state)


def _state_key(user_id: str, paper_id: str) -> str:
    return f"{user_id}::{paper_id}"


def _reading_status(value: Any) -> ReadingStatus:
    text = str(value).strip()
    if text not in {"unread", "reading", "finished"}:
        raise ValueError("readingStatus must be unread, reading, or finished")
    return text  # type: ignore[return-value]


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("currentPage must be an integer") from exc


def _progress_percent(value: Any) -> int:
    try:
        progress = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("progressPercent must be an integer") from exc
    if progress < 0 or progress > 100:
        raise ValueError("progressPercent must be between 0 and 100")
    return progress


def _clamp_progress(value: Any) -> int:
    try:
        return min(max(int(value), 0), 100)
    except (TypeError, ValueError):
        return 0


def _format_datetime(value: datetime) -> str:
    actual = value if value.tzinfo else value.replace(tzinfo=UTC)
    return actual.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
