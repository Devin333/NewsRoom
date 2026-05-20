from framework.memory import MemoryJsonSerializer, MemoryRecord


def test_memory_json_serializer_round_trips_records() -> None:
    serializer = MemoryJsonSerializer()
    record = MemoryRecord(memory_id="mem-json", content="json memory", refs={"run_id": "run-1"})

    restored = serializer.loads_record(serializer.dumps_record(record))

    assert restored == record
