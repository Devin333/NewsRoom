from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import StoredEvent, checksum_for, thaw_canonical_json
from framework.events.errors import EventContractError
from framework.events.ports import EventReaderPort
from framework.events.projection import (
    GRAPH_EVENT_CONTEXT_EXTENSION,
    GraphEventProjection,
    GraphEventProjectionExporter,
    graph_event_context,
)
from framework.shared.graph_identity import GraphRunIdentity
from framework.events.runtime.models import (
    MAX_PAGE_LIMIT,
    EventPage,
    StreamReadRequest,
)
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import EventSecurityProjector


GRAPH_EVENT_PROJECTION_REQUEST_SCHEMA = (
    "newsroom.graph-event-projection-application-request/v1"
)
GRAPH_EVENT_HISTORY_DIAGNOSTIC_SCHEMA = (
    "newsroom.graph-event-history-diagnostic/v1"
)
_SHA256_PREFIX = "sha256:"


class GraphEventProjectionApplicationStatus(StrEnum):
    PROJECTED = "projected"
    HISTORY_ONLY = "history_only"


class GraphEventHistoryDiagnosticCode(StrEnum):
    EMPTY_HISTORY = "graph_event_history_empty"
    GRAPH_CONTEXT_MISSING = "graph_event_history_graph_context_missing"
    GRAPH_CONTEXT_INVALID = "graph_event_history_graph_context_invalid"
    ORCHESTRATION_ALIAS_PRESENT = (
        "graph_event_history_legacy_orchestration_alias"
    )
    GRAPH_IDENTITY_MISMATCH = "graph_event_history_graph_identity_mismatch"


@dataclass(frozen=True, slots=True)
class GraphEventProjectionApplicationRequest:
    graph_identity: GraphRunIdentity
    target: str | Path
    tenant_id: str | None = None
    through_sequence: int | None = None
    schema_version: str = GRAPH_EVENT_PROJECTION_REQUEST_SCHEMA
    request_ref: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.graph_identity, GraphRunIdentity):
            raise TypeError("graph_identity must be GraphRunIdentity")
        target = Path(self.target).resolve(strict=False)
        if not target.name:
            raise ValueError("Graph event projection target must name a file")
        object.__setattr__(self, "target", target)
        object.__setattr__(
            self,
            "tenant_id",
            _optional_text(self.tenant_id, "tenant_id"),
        )
        object.__setattr__(
            self,
            "through_sequence",
            _optional_positive_int(self.through_sequence, "through_sequence"),
        )
        if self.schema_version != GRAPH_EVENT_PROJECTION_REQUEST_SCHEMA:
            raise EventContractError(
                "Graph event projection application request schema is unsupported"
            )
        object.__setattr__(
            self,
            "request_ref",
            checksum_for(self.checksum_projection()),
        )

    @property
    def stream_id(self) -> str:
        return f"run:{self.graph_identity.run_id}"

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_identity": self.graph_identity.to_dict(),
            "target": self.target.as_posix(),
            "tenant_id": self.tenant_id,
            "through_sequence": self.through_sequence,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "request_ref": self.request_ref}

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> GraphEventProjectionApplicationRequest:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "graph_identity",
                "target",
                "tenant_id",
                "through_sequence",
                "request_ref",
            },
            "Graph event projection application request",
        )
        request = cls(
            graph_identity=_graph_identity_from_dict(payload["graph_identity"]),
            target=payload["target"],
            tenant_id=payload["tenant_id"],
            through_sequence=payload["through_sequence"],
            schema_version=payload["schema_version"],
        )
        if payload["request_ref"] != request.request_ref:
            raise EventContractError(
                "Graph event projection application request checksum is invalid"
            )
        return request


@dataclass(frozen=True, slots=True)
class GraphEventHistoryDiagnostic:
    graph_identity: GraphRunIdentity
    tenant_id: str | None
    high_watermark: int | None
    code: GraphEventHistoryDiagnosticCode | str
    observed_sequence: int | None = None
    observed_context_schema: str | None = None
    source_record_checksum: str | None = None
    disposition: str = "history_only"
    owner: str = "offline-graph-event-migrator"
    resumable: bool = False
    executable: bool = False
    projectable: bool = False
    schema_version: str = GRAPH_EVENT_HISTORY_DIAGNOSTIC_SCHEMA
    diagnostic_ref: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.graph_identity, GraphRunIdentity):
            raise TypeError("graph_identity must be GraphRunIdentity")
        object.__setattr__(
            self,
            "tenant_id",
            _optional_text(self.tenant_id, "tenant_id"),
        )
        high_watermark = _optional_positive_int(
            self.high_watermark,
            "high_watermark",
        )
        observed_sequence = _optional_positive_int(
            self.observed_sequence,
            "observed_sequence",
        )
        if (
            observed_sequence is not None
            and high_watermark is not None
            and observed_sequence > high_watermark
        ):
            raise EventContractError(
                "Graph event history diagnostic sequence exceeds its watermark"
            )
        object.__setattr__(self, "high_watermark", high_watermark)
        object.__setattr__(self, "observed_sequence", observed_sequence)
        object.__setattr__(
            self,
            "code",
            GraphEventHistoryDiagnosticCode(self.code),
        )
        object.__setattr__(
            self,
            "observed_context_schema",
            _optional_text(
                self.observed_context_schema,
                "observed_context_schema",
                max_length=256,
            ),
        )
        object.__setattr__(
            self,
            "source_record_checksum",
            _optional_checksum(
                self.source_record_checksum,
                "source_record_checksum",
            ),
        )
        if self.disposition != "history_only":
            raise EventContractError(
                "Graph event history diagnostic disposition is invalid"
            )
        if self.owner != "offline-graph-event-migrator":
            raise EventContractError(
                "Graph event history diagnostic owner is invalid"
            )
        for field_name in ("resumable", "executable", "projectable"):
            if not isinstance(getattr(self, field_name), bool):
                raise EventContractError(f"{field_name} must be a boolean")
        if self.resumable or self.executable or self.projectable:
            raise EventContractError(
                "history-only Graph event diagnostic cannot grant runtime authority"
            )
        if self.schema_version != GRAPH_EVENT_HISTORY_DIAGNOSTIC_SCHEMA:
            raise EventContractError(
                "Graph event history diagnostic schema is unsupported"
            )
        object.__setattr__(
            self,
            "diagnostic_ref",
            checksum_for(self.checksum_projection()),
        )

    @property
    def stream_id(self) -> str:
        return f"run:{self.graph_identity.run_id}"

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_identity": self.graph_identity.to_dict(),
            "stream_id": self.stream_id,
            "tenant_id": self.tenant_id,
            "high_watermark": self.high_watermark,
            "code": self.code.value,
            "observed_sequence": self.observed_sequence,
            "observed_context_schema": self.observed_context_schema,
            "source_record_checksum": self.source_record_checksum,
            "disposition": self.disposition,
            "owner": self.owner,
            "resumable": self.resumable,
            "executable": self.executable,
            "projectable": self.projectable,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "diagnostic_ref": self.diagnostic_ref,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> GraphEventHistoryDiagnostic:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "graph_identity",
                "stream_id",
                "tenant_id",
                "high_watermark",
                "code",
                "observed_sequence",
                "observed_context_schema",
                "source_record_checksum",
                "disposition",
                "owner",
                "resumable",
                "executable",
                "projectable",
                "diagnostic_ref",
            },
            "Graph event history diagnostic",
        )
        diagnostic = cls(
            graph_identity=_graph_identity_from_dict(payload["graph_identity"]),
            tenant_id=payload["tenant_id"],
            high_watermark=payload["high_watermark"],
            code=payload["code"],
            observed_sequence=payload["observed_sequence"],
            observed_context_schema=payload["observed_context_schema"],
            source_record_checksum=payload["source_record_checksum"],
            disposition=payload["disposition"],
            owner=payload["owner"],
            resumable=payload["resumable"],
            executable=payload["executable"],
            projectable=payload["projectable"],
            schema_version=payload["schema_version"],
        )
        if payload["stream_id"] != diagnostic.stream_id:
            raise EventContractError(
                "Graph event history diagnostic stream identity is invalid"
            )
        if payload["diagnostic_ref"] != diagnostic.diagnostic_ref:
            raise EventContractError(
                "Graph event history diagnostic checksum is invalid"
            )
        return diagnostic


@dataclass(frozen=True, slots=True)
class GraphEventProjectionApplicationResult:
    request: GraphEventProjectionApplicationRequest
    status: GraphEventProjectionApplicationStatus | str
    projection: GraphEventProjection | None = None
    diagnostic: GraphEventHistoryDiagnostic | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, GraphEventProjectionApplicationRequest):
            raise TypeError(
                "request must be GraphEventProjectionApplicationRequest"
            )
        status = GraphEventProjectionApplicationStatus(self.status)
        object.__setattr__(self, "status", status)
        if status is GraphEventProjectionApplicationStatus.PROJECTED:
            if not isinstance(self.projection, GraphEventProjection):
                raise EventContractError(
                    "projected Graph event application result requires a projection"
                )
            if self.diagnostic is not None:
                raise EventContractError(
                    "projected Graph event application result cannot be diagnostic"
                )
            if (
                self.projection.graph_identity != self.request.graph_identity
                or self.projection.stream_id != self.request.stream_id
                or self.projection.path.resolve(strict=False) != self.request.target
            ):
                raise EventContractError(
                    "Graph event projection result changed the application request"
                )
            if (
                self.request.through_sequence is not None
                and self.projection.high_watermark
                != self.request.through_sequence
            ):
                raise EventContractError(
                    "Graph event projection result changed the requested watermark"
                )
        else:
            if self.projection is not None:
                raise EventContractError(
                    "history-only Graph event result cannot contain a projection"
                )
            if not isinstance(self.diagnostic, GraphEventHistoryDiagnostic):
                raise EventContractError(
                    "history-only Graph event result requires a diagnostic"
                )
            if self.diagnostic.graph_identity != self.request.graph_identity:
                raise EventContractError(
                    "Graph event history diagnostic changed the requested identity"
                )
            if self.diagnostic.tenant_id != self.request.tenant_id:
                raise EventContractError(
                    "Graph event history diagnostic changed the tenant scope"
                )
            if (
                self.request.through_sequence is not None
                and self.diagnostic.high_watermark
                != self.request.through_sequence
            ):
                raise EventContractError(
                    "Graph event history diagnostic changed the requested watermark"
                )


@runtime_checkable
class GraphEventProjectionApplicationPort(Protocol):
    def project_graph_history(
        self,
        request: GraphEventProjectionApplicationRequest,
    ) -> GraphEventProjectionApplicationResult: ...

    def verify_graph_history(
        self,
        request: GraphEventProjectionApplicationRequest,
        *,
        event_count: int,
        checksum: str,
    ) -> GraphEventProjectionApplicationResult: ...


class DurableGraphEventProjectionAdapter:
    """Project one checksum-bound Graph history through the event port.

    The adapter owns the application boundary for Graph projections. It never
    appends events or infers orchestration identity; empty, legacy-shaped, or
    conflicting history is returned as a typed history-only diagnostic.
    """

    def __init__(
        self,
        *,
        reader: EventReaderPort,
        schema_catalog: EventSchemaCatalog,
        security_projector: EventSecurityProjector | None = None,
        page_size: int = 1_000,
    ) -> None:
        if not isinstance(reader, EventReaderPort):
            raise TypeError("reader must implement EventReaderPort")
        if not isinstance(schema_catalog, EventSchemaCatalog):
            raise TypeError("schema_catalog must be EventSchemaCatalog")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= MAX_PAGE_LIMIT
        ):
            raise ValueError(
                f"page_size must be between 1 and {MAX_PAGE_LIMIT}"
            )
        self._reader = reader
        self._schema_catalog = schema_catalog
        self._security_projector = security_projector
        self._page_size = page_size

    def project_graph_history(
        self,
        request: GraphEventProjectionApplicationRequest,
    ) -> GraphEventProjectionApplicationResult:
        if not isinstance(request, GraphEventProjectionApplicationRequest):
            raise TypeError(
                "request must be GraphEventProjectionApplicationRequest"
            )
        durable_high_watermark = self._reader.get_stream_high_watermark(
            request.stream_id,
            tenant_id=request.tenant_id,
        )
        durable_high_watermark = _optional_positive_int(
            durable_high_watermark,
            "durable_high_watermark",
        )
        through_sequence = request.through_sequence or durable_high_watermark
        if request.through_sequence is not None and (
            durable_high_watermark is None
            or request.through_sequence > durable_high_watermark
        ):
            raise EventContractError(
                "requested Graph event projection exceeds durable history"
            )
        if through_sequence is None:
            return self._history_only_result(
                request,
                GraphEventHistoryDiagnostic(
                    graph_identity=request.graph_identity,
                    tenant_id=request.tenant_id,
                    high_watermark=None,
                    code=GraphEventHistoryDiagnosticCode.EMPTY_HISTORY,
                ),
            )

        first_page = self._reader.read_stream(
            StreamReadRequest(
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                limit=1,
                through_sequence=through_sequence,
            )
        )
        _validate_first_page(
            first_page,
            stream_id=request.stream_id,
            tenant_id=request.tenant_id,
            high_watermark=through_sequence,
        )
        first_diagnostic = _diagnostic_for_event(
            first_page.events[0],
            expected=request.graph_identity,
            tenant_id=request.tenant_id,
            high_watermark=through_sequence,
        )
        if first_diagnostic is not None:
            return self._history_only_result(request, first_diagnostic)

        validating_reader = _GraphHistoryValidatingReader(
            reader=self._reader,
            expected=request.graph_identity,
            tenant_id=request.tenant_id,
            high_watermark=through_sequence,
        )
        exporter = GraphEventProjectionExporter(
            reader=validating_reader,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
            page_size=self._page_size,
        )
        try:
            projection = exporter.export(
                stream_id=request.stream_id,
                target=request.target,
                tenant_id=request.tenant_id,
                through_sequence=through_sequence,
            )
        except _GraphHistoryDiagnosticSignal as signal:
            return self._history_only_result(request, signal.diagnostic)
        return GraphEventProjectionApplicationResult(
            request=request,
            status=GraphEventProjectionApplicationStatus.PROJECTED,
            projection=projection,
        )

    def verify_graph_history(
        self,
        request: GraphEventProjectionApplicationRequest,
        *,
        event_count: int,
        checksum: str,
    ) -> GraphEventProjectionApplicationResult:
        """Verify an existing Graph projection against durable history."""

        if not isinstance(request, GraphEventProjectionApplicationRequest):
            raise TypeError(
                "request must be GraphEventProjectionApplicationRequest"
            )
        if isinstance(event_count, bool) or not isinstance(event_count, int):
            raise TypeError("event_count must be an integer")
        durable_high_watermark = _optional_positive_int(
            self._reader.get_stream_high_watermark(
                request.stream_id,
                tenant_id=request.tenant_id,
            ),
            "durable_high_watermark",
        )
        through_sequence = request.through_sequence
        if through_sequence is None:
            through_sequence = durable_high_watermark
        if through_sequence is None:
            if event_count != 0:
                raise EventContractError(
                    "empty Graph event history cannot contain projection rows"
                )
            return self._history_only_result(
                request,
                GraphEventHistoryDiagnostic(
                    graph_identity=request.graph_identity,
                    tenant_id=request.tenant_id,
                    high_watermark=None,
                    code=GraphEventHistoryDiagnosticCode.EMPTY_HISTORY,
                ),
            )
        if durable_high_watermark is None or through_sequence > durable_high_watermark:
            raise EventContractError(
                "requested Graph event projection exceeds durable history"
            )
        validating_reader = _GraphHistoryValidatingReader(
            reader=self._reader,
            expected=request.graph_identity,
            tenant_id=request.tenant_id,
            high_watermark=through_sequence,
        )
        exporter = GraphEventProjectionExporter(
            reader=validating_reader,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
            page_size=self._page_size,
        )
        try:
            projection = exporter.verify_existing(
                stream_id=request.stream_id,
                target=request.target,
                tenant_id=request.tenant_id,
                high_watermark=through_sequence,
                event_count=event_count,
                checksum=checksum,
            )
        except _GraphHistoryDiagnosticSignal as signal:
            return self._history_only_result(request, signal.diagnostic)
        return GraphEventProjectionApplicationResult(
            request=request,
            status=GraphEventProjectionApplicationStatus.PROJECTED,
            projection=projection,
        )

    @staticmethod
    def _history_only_result(
        request: GraphEventProjectionApplicationRequest,
        diagnostic: GraphEventHistoryDiagnostic,
    ) -> GraphEventProjectionApplicationResult:
        return GraphEventProjectionApplicationResult(
            request=request,
            status=GraphEventProjectionApplicationStatus.HISTORY_ONLY,
            diagnostic=diagnostic,
        )


@dataclass(frozen=True, slots=True)
class _GraphHistoryValidatingReader:
    reader: EventReaderPort
    expected: GraphRunIdentity
    tenant_id: str | None
    high_watermark: int

    def get_event(
        self,
        event_id: str,
        *,
        tenant_id: str | None = None,
    ) -> StoredEvent | None:
        event = self.reader.get_event(event_id, tenant_id=tenant_id)
        if event is not None:
            self._validate(event)
        return event

    def get_stream_high_watermark(
        self,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ) -> int | None:
        self._require_scope(stream_id, tenant_id)
        return self.high_watermark

    def read_stream(self, request: StreamReadRequest) -> EventPage:
        self._require_scope(request.stream_id, request.tenant_id)
        if request.through_sequence != self.high_watermark:
            raise EventContractError(
                "Graph event projection reader changed the pinned watermark"
            )
        page = self.reader.read_stream(request)
        if not isinstance(page, EventPage):
            raise EventContractError(
                "Graph event reader returned an invalid page contract"
            )
        if (
            page.stream_id != request.stream_id
            or page.tenant_id != request.tenant_id
            or page.high_watermark != self.high_watermark
        ):
            raise EventContractError(
                "Graph event reader returned another pinned stream scope"
            )
        for event in page.events:
            self._validate(event)
        return page

    def _validate(self, event: StoredEvent) -> None:
        diagnostic = _diagnostic_for_event(
            event,
            expected=self.expected,
            tenant_id=self.tenant_id,
            high_watermark=self.high_watermark,
        )
        if diagnostic is not None:
            raise _GraphHistoryDiagnosticSignal(diagnostic)

    def _require_scope(self, stream_id: str, tenant_id: str | None) -> None:
        if stream_id != f"run:{self.expected.run_id}" or tenant_id != self.tenant_id:
            raise EventContractError(
                "Graph event projection reader crossed the requested scope"
            )


class _GraphHistoryDiagnosticSignal(RuntimeError):
    def __init__(self, diagnostic: GraphEventHistoryDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.code.value)


def _validate_first_page(
    page: EventPage,
    *,
    stream_id: str,
    tenant_id: str | None,
    high_watermark: int,
) -> None:
    if not isinstance(page, EventPage):
        raise EventContractError(
            "Graph event reader returned an invalid page contract"
        )
    if (
        page.stream_id != stream_id
        or page.tenant_id != tenant_id
        or page.high_watermark != high_watermark
        or len(page.events) != 1
        or page.events[0].stream_sequence != 1
    ):
        raise EventContractError(
            "Graph event reader did not return the first durable event"
        )


def _diagnostic_for_event(
    event: StoredEvent,
    *,
    expected: GraphRunIdentity,
    tenant_id: str | None,
    high_watermark: int,
) -> GraphEventHistoryDiagnostic | None:
    event.verify_integrity()
    if (
        event.stream_id != f"run:{expected.run_id}"
        or event.tenant_id != tenant_id
    ):
        raise EventContractError(
            "Graph event history crossed the requested stream or tenant scope"
        )
    raw_context = thaw_canonical_json(
        event.extensions.get(GRAPH_EVENT_CONTEXT_EXTENSION)
    )
    observed_schema = _observed_context_schema(raw_context)
    if not isinstance(raw_context, Mapping):
        code = GraphEventHistoryDiagnosticCode.GRAPH_CONTEXT_MISSING
    else:
        try:
            context = graph_event_context(event)
        except (EventContractError, TypeError, ValueError):
            code = GraphEventHistoryDiagnosticCode.GRAPH_CONTEXT_INVALID
        else:
            if context.identity == expected:
                return None
            code = GraphEventHistoryDiagnosticCode.GRAPH_IDENTITY_MISMATCH
    return GraphEventHistoryDiagnostic(
        graph_identity=expected,
        tenant_id=tenant_id,
        high_watermark=high_watermark,
        code=code,
        observed_sequence=event.stream_sequence,
        observed_context_schema=observed_schema,
        source_record_checksum=event.record_checksum,
    )


def _optional_text(
    value: Any,
    field_name: str,
    *,
    max_length: int = 512,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EventContractError(f"{field_name} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise EventContractError(f"{field_name} is too long")
    return normalized


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EventContractError(f"{field_name} must be a positive integer")
    return value


def _optional_checksum(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventContractError(f"{field_name} must be a checksum")
    digest = value.removeprefix(_SHA256_PREFIX)
    if (
        not value.startswith(_SHA256_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise EventContractError(f"{field_name} must be a sha256 checksum")
    return value


def _observed_context_schema(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    schema = value.get("schema")
    if not isinstance(schema, str):
        return None
    normalized = schema.strip()
    if not normalized or len(normalized) > 256:
        return None
    return normalized


def _graph_identity_from_dict(value: Any) -> GraphRunIdentity:
    payload = _exact_mapping(
        value,
        {
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
        },
        "Graph run identity",
    )
    return GraphRunIdentity(
        run_id=payload["run_id"],
        graph_id=payload["graph_id"],
        graph_version=payload["graph_version"],
        graph_ref=payload["graph_ref"],
        graph_checksum=payload["graph_checksum"],
    )


def _exact_mapping(
    value: Any,
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise EventContractError(f"{model} fields are invalid")
    return dict(value)


__all__ = [
    "GRAPH_EVENT_HISTORY_DIAGNOSTIC_SCHEMA",
    "GRAPH_EVENT_PROJECTION_REQUEST_SCHEMA",
    "GraphEventHistoryDiagnostic",
    "GraphEventHistoryDiagnosticCode",
    "GraphEventProjectionApplicationPort",
    "GraphEventProjectionApplicationRequest",
    "GraphEventProjectionApplicationResult",
    "GraphEventProjectionApplicationStatus",
    "DurableGraphEventProjectionAdapter",
]
