from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairStrategy
from interfaces.services.reader_repair_memory import PostgresReaderRepairMemoryPort
from tests.business.research.reader_repair._fixtures import make_repair_case


class _PayloadRepository:
    def __init__(self):
        self.calls = []
        self.payload = None

    def write_object(self, **kwargs):
        self.calls.append(("write_object", kwargs))
        self.payload = kwargs["payload"]
        return f"memory://{kwargs['namespace']}/{kwargs['object_type']}/{kwargs['object_id']}"

    def recall_case_payloads(self, **kwargs):
        self.calls.append(("recall_case_payloads", kwargs))
        return (self.payload,)

    def recall_strategy_payloads(self, **kwargs):
        self.calls.append(("recall_strategy_payloads", kwargs))
        return (self.payload,)

    def list_case_payloads(self, **kwargs):
        self.calls.append(("list_case_payloads", kwargs))
        return (self.payload,)

    def list_versions(self, **kwargs):
        self.calls.append(("list_versions", kwargs))
        return ()

    def version_payload(self, **kwargs):
        self.calls.append(("version_payload", kwargs))
        return self.payload


def test_postgres_reader_repair_memory_port_maps_case_domain_models() -> None:
    issue = _issue()
    case = make_repair_case("case-1", issue=issue, successful=True)
    repository = _PayloadRepository()
    port = PostgresReaderRepairMemoryPort(repository)

    ref = port.write_case(case)
    recalled = port.recall_cases(port_query(issue))

    assert ref == "memory://research.reader_repair/case/case-1"
    assert recalled[0].repair_case_id == "case-1"
    write_call = repository.calls[0][1]
    assert write_call["object_type"] == "case"
    assert write_call["error_signature"] == issue.error_signature


def test_postgres_reader_repair_memory_port_rolls_back_strategy_from_payload_version() -> None:
    strategy = ReaderRepairStrategy(
        strategy_id="strategy-1",
        issue_type="table_parse_error",
        applicability="Repeated table parse repair.",
        steps=["match table signature", "restore cells", "verify lineage"],
        confidence=0.9,
        source_case_refs=["case-1"],
        status="promoted_memory",
    )
    repository = _PayloadRepository()
    repository.payload = strategy.to_dict()
    port = PostgresReaderRepairMemoryPort(repository)

    ref = port.rollback_strategy("strategy-1", version=1)

    assert ref == "memory://research.reader_repair/strategy/strategy-1"
    assert repository.calls[-1][1]["operation"] == "rollback"


def _issue() -> ReaderIssue:
    return ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table_parse_error:build_reader_payload:pdf:missing_cells",
        symptom="Table dropped cells.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="reader-payload-1",
    )


def port_query(issue: ReaderIssue):
    from business.research.domain.reader_repair import ReaderRepairMemoryQuery

    return ReaderRepairMemoryQuery.from_issue(issue, source_format="pdf")
