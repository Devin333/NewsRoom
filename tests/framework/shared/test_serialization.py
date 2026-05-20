from __future__ import annotations

from dataclasses import dataclass

from framework.shared import JsonDataclassSerializer


@dataclass(frozen=True)
class _Record:
    name: str
    count: int

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "count": self.count}


def test_json_dataclass_serializer_round_trips_through_factory() -> None:
    serializer = JsonDataclassSerializer(lambda payload: _Record(**payload))

    text = serializer.dumps(_Record(name="paper", count=2))
    record = serializer.loads(text)

    assert text == '{"count":2,"name":"paper"}'
    assert record == _Record(name="paper", count=2)
