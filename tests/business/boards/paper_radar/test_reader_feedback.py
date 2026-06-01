import pytest

from business.boards.paper_radar.reader_feedback import PaperReaderFeedbackService
from business.boards.paper_radar.source_comparison_memory import PaperSourceComparisonMemoryService
from business.boards.paper_radar.worker_handlers import PaperReaderFeedbackTaskHandler
from business.boards.paper_radar.visual_compiler.models import PaperCompileInfo, PaperSourceComparisonReport
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


def test_source_comparison_memory_ingests_lessons_as_evidence_decision_and_event() -> None:
    repository = _MemoryRepository()
    service = PaperSourceComparisonMemoryService(repository=repository)

    result = service.ingest_source_comparison(
        report=_source_comparison_report(passed=False),
        compile_info=_compile_info(),
        paper={"id": "paper-1", "title": "Paper One"},
        artifact_ref="visual-compiler/paper-1/source-comparison-report.json",
    )

    assert result.saved is True
    assert result.evidence_count == 2
    assert result.decision_count == 1
    assert result.event_count == 1
    assert {item.category for item in repository.evidence} == {"paper_reader_source_comparison"}
    assert repository.decisions[0].decision == "block"
    assert repository.decisions[0].workflow_id == "paper_reader_source_comparison"
    assert repository.events[0].event_type == "engineering_practice"
    assert repository.events[0].evidence_ids == [item.evidence_id for item in repository.evidence]


def test_source_comparison_memory_failure_is_non_throwing() -> None:
    service = PaperSourceComparisonMemoryService(repository=_FailingMemoryRepository())

    result = service.ingest_source_comparison(
        report=_source_comparison_report(passed=True),
        compile_info=_compile_info(),
        paper={"id": "paper-1"},
        artifact_ref="visual-compiler/paper-1/source-comparison-report.json",
    )

    assert result.attempted is True
    assert result.saved is False
    assert result.error == "memory unavailable"


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


def _compile_info() -> PaperCompileInfo:
    return PaperCompileInfo(
        paperId="paper-1",
        status="needs_review",
        provider="pymupdf-heuristic-v1",
        sourceHash="abc123sourcehash",
        startedAt="2026-05-28T00:00:00Z",
        finishedAt="2026-05-28T00:00:01Z",
        sourcePdfUrl="https://arxiv.org/pdf/2605.00001.pdf",
        pageCount=1,
        blockCount=3,
        assetCount=2,
    )


def _source_comparison_report(*, passed: bool) -> PaperSourceComparisonReport:
    errors = (
        {
            "severity": "error",
            "code": "visual_asset_unreferenced",
            "message": "figure/table assets must be represented by reader blocks",
        },
    ) if not passed else ()
    return PaperSourceComparisonReport(
        paperId="paper-1",
        passed=passed,
        comparer="paper-source-comparer-v1",
        createdAt="2026-05-28T00:00:01Z",
        summary="Source comparison passed." if passed else "Source comparison failed.",
        metrics={"blockCount": 3, "visualAssetCount": 1},
        errors=errors,
        warnings=(
            {
                "severity": "warning",
                "code": "synthetic_source_mapping",
                "message": "compiled blocks use synthetic source regions",
            },
        ),
        lessons=(
            {
                "lessonId": "lesson-1",
                "severity": "info" if passed else "error",
                "category": "source_comparison_passed" if passed else "publication_blocker",
                "code": "source_comparison_passed" if passed else "visual_asset_unreferenced",
                "message": "Remember the source comparison outcome.",
            },
            {
                "lessonId": "lesson-2",
                "severity": "warning",
                "category": "source_comparison_watch",
                "code": "synthetic_source_mapping",
                "message": "Track synthetic source mapping.",
            },
        ),
    )
