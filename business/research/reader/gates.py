from __future__ import annotations

from business.research.domain.common import GateResult
from business.research.domain.reader import ResearchReaderPayload


def validate_reader_payload_schema(payload: ResearchReaderPayload) -> GateResult:
    if payload.paper.paper_id != payload.document.paper_id:
        return GateResult.fail("ReaderPayloadSchemaGate", "reader payload paper/document mismatch")
    return GateResult.pass_("ReaderPayloadSchemaGate")


def validate_reader_source_lineage(payload: ResearchReaderPayload) -> GateResult:
    if not payload.source_lineage.source_refs:
        return GateResult.fail("ReaderSourceLineageGate", "reader payload requires source lineage")
    return GateResult.pass_("ReaderSourceLineageGate")


def validate_reader_navigation(payload: ResearchReaderPayload) -> GateResult:
    if payload.document.sections and not payload.navigation:
        return GateResult.fail("ReaderNavigationGate", "reader payload requires navigation for sectioned document")
    return GateResult.pass_("ReaderNavigationGate")


__all__ = ["validate_reader_navigation", "validate_reader_payload_schema", "validate_reader_source_lineage"]
