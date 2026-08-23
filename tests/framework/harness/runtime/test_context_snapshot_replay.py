from __future__ import annotations

from framework.harness import (
    ContextEnvelope,
    ContextSnapshotStore,
)
from tests.framework.harness.context.test_context_models import _graph_identity


def test_context_snapshot_replay_uses_refs_without_reassembling_context() -> None:
    envelope = ContextEnvelope.for_graph(
        envelope_id="context://run/collect",
        graph_identity=_graph_identity(),
        phase="EXECUTE",
        worker_id="context-worker",
        worker_type="function",
    )
    store = ContextSnapshotStore()
    bound_envelope, snapshot = store.save_bound(envelope)

    replay = store.replay(snapshot.snapshot_id)

    assert replay == bound_envelope
    assert snapshot.refs
    assert snapshot.assembled_prompt_ref.startswith("artifact://assembled-context/")
