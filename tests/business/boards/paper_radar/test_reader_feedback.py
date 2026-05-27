import pytest

from business.boards.paper_radar.reader_feedback import PaperReaderFeedbackService
from business.boards.paper_radar.worker_handlers import PaperReaderFeedbackTaskHandler
from framework.workers.models import Task
from interfaces.services.paper_reader_interaction_service import (
    LocalJsonPaperReaderInteractionRepository,
    PaperReaderInteractionApplicationService,
)
from interfaces.services.worker_service import WorkerApplicationService


def test_reader_feedback_maps_high_value_events_and_skips_low_value_events() -> None:
    repository = _MemoryRepository()
    service = PaperReaderFeedbackService(repository=repository)

    result = service.ingest_reader_events(
        [
            {
                "eventId": "event-selection",
                "type": "selection_created",
                "paperId": "paper-1",
                "userId": "user-1",
                "selectedText": "temporary",
            },
            {
                "eventId": "event-note",
                "type": "note_updated",
                "paperId": "paper-1",
                "userId": "user-1",
                "selectionId": "sel-1",
                "selectedText": "The verifier checks claims.",
                "payload": {"noteText": "Verifier means evidence checker."},
            },
            {
                "eventId": "event-confused",
                "type": "confusion_marked",
                "paperId": "paper-1",
                "userId": "user-1",
                "selectionId": "sel-2",
                "target": {"targetType": "paragraph", "paragraphId": "p8"},
                "selectedText": "Verifier loop",
            },
            {
                "eventId": "event-example",
                "type": "example_generated",
                "paperId": "paper-1",
                "userId": "user-1",
                "selectionId": "sel-3",
                "selectedText": "Verifier loop",
                "payload": {"exampleQuestion": "Use an engineering example."},
            },
            {
                "eventId": "event-settings",
                "type": "reader_settings_changed",
                "paperId": "paper-1",
                "userId": "user-1",
                "payload": {"theme": "warm", "fontSize": 21},
            },
            {
                "eventId": "event-figure",
                "type": "figure_explanation_requested",
                "paperId": "paper-1",
                "userId": "user-1",
                "target": {"targetType": "figure", "blockId": "fig-1"},
                "payload": {"question": "Explain this architecture figure."},
            },
            {
                "eventId": "event-table",
                "type": "table_explanation_requested",
                "paperId": "paper-1",
                "userId": "user-1",
                "target": {"targetType": "table", "blockId": "table-1"},
                "payload": {"question": "Which row is the ablation?"},
            },
        ]
    )

    assert result.skipped_event_ids == ["event-selection"]
    assert set(result.processed_event_ids) == {
        "event-note",
        "event-confused",
        "event-example",
        "event-settings",
        "event-figure",
        "event-table",
    }
    assert {signal.signal_type for signal in result.signals} >= {
        "reader_note_insight",
        "reader_confusion_point",
        "reader_example_preference",
        "reader_settings_preference",
        "reader_figure_or_table_need",
    }
    assert len(repository.evidence) == 5
    assert len(repository.decisions) == 2
    assert len(repository.preferences) == 4
    assert len(repository.events) == 3


def test_reader_feedback_worker_is_idempotent_and_marks_low_value_events_processed(tmp_path) -> None:
    interaction_repository = LocalJsonPaperReaderInteractionRepository(tmp_path / "reader-interactions.json")
    interaction_service = PaperReaderInteractionApplicationService(
        event_repository=interaction_repository,
        selection_repository=interaction_repository,
    )
    interaction_service.create_selection(
        user_id="user-1",
        paper_id="paper-1",
        payload={"selectedText": "Temporary", "surroundingText": "Temporary"},
    )
    selection = interaction_service.create_selection(
        user_id="user-1",
        paper_id="paper-1",
        payload={"selectedText": "Important", "surroundingText": "Important context"},
    ).selection
    interaction_service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=selection.selectionId,
        patch={"noteText": "This is worth remembering."},
    )

    memory_repository = _MemoryRepository()
    handler = PaperReaderFeedbackTaskHandler(
        event_repository=interaction_repository,
        feedback_service=PaperReaderFeedbackService(repository=memory_repository),
    )
    task = Task(
        task_type=handler.task_type,
        payload={"paper_id": "paper-1", "user_id": "user-1", "limit": 20},
        task_id="task-1",
    )

    first = handler.handle(task)
    second = handler.handle(task)

    assert first.success is True
    assert first.output["processed_count"] == 1
    assert first.output["skipped_count"] == 2
    assert second.output["event_count"] == 0
    assert interaction_repository.list_unprocessed_events(paper_id="paper-1", user_id="user-1") == []
    assert len(memory_repository.evidence) == 1


def test_reader_feedback_worker_keeps_events_unprocessed_when_memory_fails(tmp_path) -> None:
    interaction_repository = LocalJsonPaperReaderInteractionRepository(tmp_path / "reader-interactions.json")
    interaction_service = PaperReaderInteractionApplicationService(
        event_repository=interaction_repository,
        selection_repository=interaction_repository,
    )
    selection = interaction_service.create_selection(
        user_id="user-1",
        paper_id="paper-1",
        payload={"selectedText": "Important", "surroundingText": "Important context"},
    ).selection
    interaction_service.patch_selection(
        user_id="user-1",
        paper_id="paper-1",
        selection_id=selection.selectionId,
        patch={"noteText": "This is worth remembering."},
    )
    handler = PaperReaderFeedbackTaskHandler(
        event_repository=interaction_repository,
        feedback_service=PaperReaderFeedbackService(repository=_FailingMemoryRepository()),
    )

    with pytest.raises(RuntimeError):
        handler.handle(Task(task_type=handler.task_type, payload={"paper_id": "paper-1"}, task_id="task-1"))

    unprocessed = interaction_repository.list_unprocessed_events(paper_id="paper-1")
    assert [event.type for event in unprocessed] == ["selection_created", "note_updated"]


def test_worker_service_enqueues_reader_feedback_with_stable_payload_and_dedup_key() -> None:
    queue = _CaptureQueue()
    service = WorkerApplicationService(queue=queue, worker_registry=None, handlers={})

    result = service.enqueue_paper_reader_feedback(paper_id="paper-1", user_id="user-1", limit=25)

    assert result.message_id == "message-1"
    task = queue.tasks[0]
    assert task.task_type == "paper_reader.feedback_ingest"
    assert task.queue_name == "news:queue:memory"
    assert task.payload == {"paper_id": "paper-1", "user_id": "user-1", "limit": 25}
    assert task.dedup_key.startswith("news:queue:memory:paper-reader-feedback:paper-1:user-1:")


class _MemoryRepository:
    def __init__(self) -> None:
        self.evidence = []
        self.decisions = []
        self.preferences = []
        self.events = []

    def save_evidence(self, items) -> None:
        self.evidence.extend(items)

    def save_claims(self, claims) -> None:
        pass

    def save_entities(self, entities) -> None:
        pass

    def save_events(self, events) -> None:
        self.events.extend(events)

    def save_decisions(self, decisions) -> None:
        self.decisions.extend(decisions)

    def save_preferences(self, preferences) -> None:
        self.preferences.extend(preferences)


class _FailingMemoryRepository(_MemoryRepository):
    def save_evidence(self, items) -> None:
        raise RuntimeError("memory unavailable")


class _CaptureQueue:
    def __init__(self) -> None:
        self.tasks = []

    def enqueue(self, task):
        self.tasks.append(task)
        return "message-1"
