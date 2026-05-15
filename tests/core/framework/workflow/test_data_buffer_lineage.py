from core.framework.workflow import RedactionStatus, ScopedDataBuffer, StepDataScope


def test_request_key_lineage_is_seeded() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("items", [1, 2, 3])

    lineage = buffer.get_lineage("items")

    assert lineage is not None
    assert lineage.produced_by_step_id == "__request__"


def test_lineage_tracks_output_producer_step() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("items", [1, 2, 3])
    buffer.register_scope(
        StepDataScope(
            step_id="rank",
            read_keys={"items"},
            write_keys={"ranked_items"},
        )
    )

    buffer.write(
        step_id="rank",
        key="ranked_items",
        value=[3, 2, 1],
        source_keys=["items"],
    )

    lineage = buffer.get_lineage("ranked_items")

    assert lineage is not None
    assert lineage.produced_by_step_id == "rank"
    assert lineage.source_keys == ["items"]


def test_source_steps_track_source_key_producers() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("items", [1, 2, 3])
    buffer.register_scopes(
        [
            StepDataScope(step_id="collect", read_keys={"items"}, write_keys={"collected"}),
            StepDataScope(
                step_id="rank",
                read_keys={"collected"},
                write_keys={"ranked_items"},
            ),
        ]
    )

    buffer.write(
        step_id="collect",
        key="collected",
        value=[1, 2, 3],
        source_keys=["items"],
    )
    buffer.write(
        step_id="rank",
        key="ranked_items",
        value=[3, 2, 1],
        source_keys=["collected"],
    )

    lineage = buffer.get_lineage("ranked_items")

    assert lineage is not None
    assert lineage.source_steps == ["collect"]


def test_write_history_records_previous_and_new_hash() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="writer", write_keys={"summary"}))

    buffer.write(step_id="writer", key="summary", value="first")
    buffer.write(step_id="writer", key="summary", value="second")

    history = buffer.write_history("summary")

    assert len(history) == 2
    assert history[0].previous_hash is None
    assert history[0].new_hash is not None
    assert history[1].previous_hash == history[0].new_hash
    assert history[1].new_hash != history[0].new_hash
    assert history[1].redaction_status == RedactionStatus.NONE


def test_delete_records_history_and_removes_lineage() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="writer", write_keys={"summary"}))
    buffer.write(step_id="writer", key="summary", value="first")

    buffer.delete(step_id="writer", key="summary")

    history = buffer.write_history("summary")
    assert history[-1].value_type == "deleted"
    assert history[-1].previous_hash == history[0].new_hash
    assert buffer.get_lineage("summary") is None
