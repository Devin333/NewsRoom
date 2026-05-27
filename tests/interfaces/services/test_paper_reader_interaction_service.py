from interfaces.services.paper_reader_interaction_service import (
    LocalJsonPaperReaderInteractionRepository,
    PaperReaderInteractionApplicationService,
)


def test_reader_selection_state_transitions_and_material_summary(tmp_path) -> None:
    service = PaperReaderInteractionApplicationService(store_path=tmp_path / "reader-interactions.json")

    created = service.create_selection(
        user_id="user-1",
        paper_id="paper-1",
        payload={
            "target": {"targetType": "text_selection", "sectionId": "method", "paragraphId": "p7"},
            "selectedText": "The verifier checks claims.",
            "surroundingText": "The verifier checks claims against evidence.",
            "payload": {"sectionTitle": "Method"},
        },
    )
    selection_id = created.selection.selectionId
    assert created.materialSummary.to_dict()["stats"]["materialCount"] == 0

    noted = service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=selection_id,
        patch={"noteText": "Verifier is the evidence checker."},
    )
    assert noted.selection.noteText == "Verifier is the evidence checker."
    assert noted.materialSummary.to_dict()["stats"] == {
        "noteCount": 1,
        "explainedCount": 0,
        "exampledCount": 0,
        "confusedCount": 0,
        "materialCount": 1,
    }

    confused = service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=selection_id,
        patch={"confused": True},
    )
    assert confused.selection.status == "confused"

    unmarked = service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=selection_id,
        patch={"confused": False},
    )
    assert unmarked.selection.status == "has_note"
    assert unmarked.materialSummary.to_dict()["stats"]["materialCount"] == 1

    temp = service.create_selection(
        user_id="user-1",
        paper_id="paper-1",
        payload={
            "selectedText": "A temporary confusion.",
            "surroundingText": "A temporary confusion.",
        },
    )
    temp_id = temp.selection.selectionId
    service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=temp_id,
        patch={"confused": True},
    )
    removed = service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=temp_id,
        patch={"confused": False},
    )
    assert removed.selection is None
    assert service.material_summary(user_id="user-1", paper_id="paper-1").to_dict()["stats"]["materialCount"] == 1


def test_reader_targets_cover_text_paragraph_figure_table_and_equation(tmp_path) -> None:
    service = PaperReaderInteractionApplicationService(store_path=tmp_path / "reader-interactions.json")
    target_types = ["text_selection", "paragraph", "figure", "table", "equation"]

    for target_type in target_types:
        service.record_event(
            user_id="user-1",
            paper_id="paper-1",
            payload={
                "type": "selection_created",
                "target": {"targetType": target_type, "blockId": f"{target_type}-1", "pageNumber": 1},
                "selectedText": f"{target_type} content",
                "surroundingText": f"{target_type} surrounding content",
            },
        )

    events = service.material_summary(user_id="user-1", paper_id="paper-1").events
    assert [event.target.targetType for event in events] == target_types


def test_reader_repository_isolates_users_and_marks_processed_events(tmp_path) -> None:
    repository = LocalJsonPaperReaderInteractionRepository(tmp_path / "reader-interactions.json")
    first = PaperReaderInteractionApplicationService(
        event_repository=repository,
        selection_repository=repository,
    )
    second = PaperReaderInteractionApplicationService(
        event_repository=repository,
        selection_repository=repository,
    )

    first.create_selection(
        user_id="user-1",
        paper_id="paper-1",
        payload={"selectedText": "first", "surroundingText": "first"},
    )
    second.create_selection(
        user_id="user-2",
        paper_id="paper-1",
        payload={"selectedText": "second", "surroundingText": "second"},
    )

    first_events = repository.list_events("user-1", "paper-1")
    second_events = repository.list_events("user-2", "paper-1")
    assert len(first_events) == 1
    assert len(second_events) == 1
    assert first_events[0].selectedText == "first"
    assert second_events[0].selectedText == "second"

    repository.mark_events_processed([first_events[0].eventId])
    remaining = repository.list_unprocessed_events(paper_id="paper-1")
    assert [event.eventId for event in remaining] == [second_events[0].eventId]
