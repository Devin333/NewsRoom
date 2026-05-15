from core.framework.workflow import ScopedDataBuffer, StepDataScope


def test_buffer_diff_added_modified_deleted() -> None:
    before = {
        "a": 1,
        "b": 2,
        "c": 3,
    }

    after = {
        "a": 1,
        "b": 20,
        "d": 4,
    }

    diff = ScopedDataBuffer.diff_snapshots(before, after)

    assert diff.added == {"d": 4}
    assert set(diff.modified.keys()) == {"b"}
    assert diff.modified["b"]["before"] == 2
    assert diff.modified["b"]["after"] == 20
    assert diff.modified["b"]["before_hash"] != diff.modified["b"]["after_hash"]
    assert diff.deleted == {"c": 3}


def test_instance_diff_uses_current_unredacted_snapshot() -> None:
    buffer = ScopedDataBuffer({"a": 1, "b": 2})
    before = buffer.snapshot(redacted=False)
    buffer.register_scope(StepDataScope(step_id="edit", write_keys={"b", "c", "a"}))

    buffer.write(step_id="edit", key="b", value=20)
    buffer.write(step_id="edit", key="c", value=30)
    buffer.delete(step_id="edit", key="a")

    diff = buffer.diff(before)

    assert diff.added == {"c": 30}
    assert set(diff.modified) == {"b"}
    assert diff.deleted == {"a": 1}


def test_unchanged_key_is_not_in_diff() -> None:
    diff = ScopedDataBuffer.diff_snapshots({"a": 1}, {"a": 1})

    assert diff.added == {}
    assert diff.modified == {}
    assert diff.deleted == {}


def test_snapshot_hash_is_stable_for_same_content() -> None:
    first = ScopedDataBuffer({"nested": {"b": 2, "a": 1}})
    second = ScopedDataBuffer({"nested": {"a": 1, "b": 2}})

    assert first.snapshot_hash(redacted=False) == second.snapshot_hash(redacted=False)


def test_snapshot_hash_changes_after_content_change() -> None:
    buffer = ScopedDataBuffer({"value": 1})
    before_hash = buffer.snapshot_hash(redacted=False)
    buffer.register_scope(StepDataScope(step_id="edit", write_keys={"value"}))

    buffer.write(step_id="edit", key="value", value=2)

    assert buffer.snapshot_hash(redacted=False) != before_hash


def test_legacy_diff_to_dict_keeps_existing_artifact_shape() -> None:
    diff = ScopedDataBuffer.diff_snapshots({"a": 1}, {"a": 2})

    assert diff.to_dict() == {
        "added": {},
        "changed": {
            "a": {
                "previous": 1,
                "current": 2,
            }
        },
        "removed": {},
    }
