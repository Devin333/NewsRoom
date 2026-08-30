from __future__ import annotations

from backend.research.domain.reader import ReaderAnnotation, ReaderNavigationItem, ResearchReaderPayload
from backend.research.reader.gates import (
    validate_reader_navigation,
    validate_reader_payload_schema,
    validate_reader_source_lineage,
)
from backend.research.reader.payload_builder import ReaderPayloadBuilder

__all__ = [
    "ReaderAnnotation",
    "ReaderNavigationItem",
    "ReaderPayloadBuilder",
    "ResearchReaderPayload",
    "validate_reader_navigation",
    "validate_reader_payload_schema",
    "validate_reader_source_lineage",
]
