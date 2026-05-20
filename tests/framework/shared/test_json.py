from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from framework.shared import canonical_json, json_loads, stable_json_dumps, to_jsonable


class _Kind(Enum):
    PAPER = "paper"
    PROJECT = "project"


@dataclass(frozen=True)
class _Payload:
    kind: _Kind
    created_at: datetime
    path: Path


class _DictLike:
    def to_dict(self) -> dict[str, object]:
        return {"kind": _Kind.PROJECT, "items": {2, 1}}


def test_to_jsonable_normalizes_runtime_values() -> None:
    created_at = datetime(2026, 5, 20, 1, 2, 3, tzinfo=UTC)
    payload = {
        _Kind.PAPER: _Payload(
            kind=_Kind.PAPER,
            created_at=created_at,
            path=Path("runs/run-1/report.json"),
        ),
        created_at: _DictLike(),
        "tuple": (_Kind.PROJECT, Path("x/y")),
    }

    assert to_jsonable(payload) == {
        "paper": {
            "kind": "paper",
            "created_at": "2026-05-20T01:02:03Z",
            "path": "runs/run-1/report.json",
        },
        "2026-05-20T01:02:03Z": {"kind": "project", "items": [1, 2]},
        "tuple": ["project", "x/y"],
    }


def test_stable_json_dumps_and_canonical_json_are_sorted_and_compact() -> None:
    payload = {"b": 2, "a": 1}

    assert stable_json_dumps(payload) == '{"a":1,"b":2}'
    assert canonical_json(payload) == stable_json_dumps(payload)
    assert json_loads(stable_json_dumps(payload)) == {"a": 1, "b": 2}
