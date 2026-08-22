from pathlib import Path

from tests.framework.harness.control_plane.test_node_output_resource import (
    _NOW,
    _activity,
    _admission,
    _candidate,
    _success_guard,
)
from infrastructure.storage.harness import SQLiteHarnessNodeOutputResource


def test_sqlite_node_output_survives_restart_and_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "node-output.sqlite"
    resource = SQLiteHarnessNodeOutputResource(database)
    activity = _activity()
    admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    lease = resource.acquire_after_admission(activity, admission)
    assert resource.acquire_after_admission(activity, admission) == lease
    staged = resource.stage(lease, _candidate("first"), staged_at=_NOW)
    assert resource.stage(lease, _candidate("first"), staged_at=_NOW) == staged
    committed = resource.commit(staged, _success_guard(), committed_at=_NOW)
    assert resource.commit(staged, _success_guard(), committed_at=_NOW) == committed
    resource.close()

    restarted = SQLiteHarnessNodeOutputResource(database)
    assert restarted.current_lease(lease.resource) == lease
    assert restarted.committed_output(lease.resource) == committed
    assert restarted.discard(staged) is False
    restarted.close()


def test_sqlite_node_output_fences_superseded_owner(tmp_path: Path) -> None:
    from framework.harness.control_plane.node_output import HarnessNodeOutputStaleOwnerError

    resource = SQLiteHarnessNodeOutputResource(tmp_path / "node-output.sqlite")
    activity = _activity()
    first = resource.acquire_after_admission(
        activity, _admission(activity, owner_attempt_id="physical-attempt-1")
    )
    first_staged = resource.stage(first, _candidate("first"), staged_at=_NOW)
    second = resource.acquire_after_admission(
        activity, _admission(activity, owner_attempt_id="physical-attempt-2")
    )
    assert second.generation == first.generation + 1
    try:
        resource.commit(first_staged, _success_guard(), committed_at=_NOW)
    except HarnessNodeOutputStaleOwnerError as exc:
        assert exc.code == "graph_node_output_stale_owner"
    else:
        raise AssertionError("superseded owner committed output")
    resource.close()
