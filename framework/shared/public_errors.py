from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal
from uuid import uuid4


PublicErrorContext = Literal["mcp", "worker", "http"]
DiagnosticHook = Callable[[dict[str, Any]], None]

_INTERNAL_ERROR_TYPES: dict[PublicErrorContext, str] = {
    "mcp": "MCPInternalError",
    "worker": "WorkerInternalError",
    "http": "InternalError",
}
_INTERNAL_ERROR_MESSAGES: dict[PublicErrorContext, str] = {
    "mcp": "internal error",
    "worker": "task execution failed",
    "http": "internal server error",
}
_ARTIFACT_ERROR_TYPES = frozenset(
    {
        "ArtifactChecksumMismatchError",
        "ArtifactNotFoundError",
        "ArtifactPathError",
        "ArtifactStoreMetadataError",
        "ArtifactStoreRequiredError",
    }
)
_MCP_NOT_FOUND_TYPES = frozenset(
    {"MCPPromptNotFound", "MCPResourceNotFound", "MCPToolNotFound"}
)
_MCP_SAFE_ERROR_TYPES = _ARTIFACT_ERROR_TYPES | _MCP_NOT_FOUND_TYPES | frozenset(
    {
        "EventAuthorizationError",
        "EventContractError",
        "EventOperationCapabilityUnavailableError",
        "EventOperationNotFoundError",
        "EventRuntimeError",
        "EventStoreUnavailableError",
        "PermissionError",
        "ResearchActorAuthorizationError",
        "ResearchConfigurationError",
        "ResearchQualityGateError",
        "ResearchRuntimeUnavailableError",
        "ResearchSourceError",
        "ValueError",
    }
)
_FIXED_MCP_MESSAGES = {
    "ArtifactChecksumMismatchError": "artifact integrity verification failed",
    "ArtifactNotFoundError": "artifact not found",
    "ArtifactPathError": "invalid artifact path",
    "ArtifactStoreMetadataError": "artifact integrity verification failed",
    "ArtifactStoreRequiredError": "artifact integrity verification failed",
    "EventAuthorizationError": "event operator action is not authorized",
    "EventContractError": (
        "event operator data conflicts with the durable event contract"
    ),
    "EventOperationCapabilityUnavailableError": (
        "event operator capability is unavailable"
    ),
    "EventOperationNotFoundError": "event operator resource not found",
    "EventRuntimeError": "event runtime operation failed",
    "EventStoreUnavailableError": "event store is unavailable",
    "PermissionError": "MCP request is not authorized",
    "ResearchActorAuthorizationError": (
        "Research actor scope does not match the authenticated principal"
    ),
    "ResearchConfigurationError": "research runtime configuration is invalid",
    "ResearchQualityGateError": "research quality gate failed",
    "ResearchRuntimeUnavailableError": "research runtime is unavailable",
    "ResearchSourceError": "research source acquisition failed",
    "ValueError": "invalid MCP request",
}
_FIXED_WORKER_MESSAGES = {
    "StaleTaskLeaseError": "task lease is stale",
    "WorkerInternalError": _INTERNAL_ERROR_MESSAGES["worker"],
}
_SAFE_MCP_NAME = re.compile(r"news\.[a-z0-9][a-z0-9_.-]{0,239}\Z")
_SAFE_MCP_RESOURCE = re.compile(r"news://[a-z0-9][a-z0-9._/-]{0,239}\Z")
_SERVER_ERROR_ID = re.compile(r"err_[0-9a-f]{16}\Z")
_LOGGER = logging.getLogger("newsroom.public_errors")


@dataclass(frozen=True)
class PublicErrorProjection:
    error_type: str
    error_message: str
    error_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_id": self.error_id,
        }


class ApprovedPublicError(RuntimeError):
    """Explicit marker for fixed-message errors approved at one boundary."""

    def __init__(
        self,
        internal_message: str,
        *,
        context: PublicErrorContext,
        error_type: str,
        error_message: str,
    ) -> None:
        super().__init__(internal_message)
        self.public_context = context
        self.public_error_type = error_type
        self.public_error_message = error_message


def project_public_error(
    exc: BaseException,
    *,
    context: PublicErrorContext = "mcp",
    operation: str | None = None,
    diagnostic_hook: DiagnosticHook | None = None,
) -> PublicErrorProjection:
    """Project an exception into an explicitly approved public error contract.

    Unknown exception names and messages never cross the boundary. Their raw
    diagnostics are emitted only through the server-side hook/logger and are
    correlated by a bounded identifier.
    """

    error_type = type(exc).__name__
    if (
        isinstance(exc, ApprovedPublicError)
        and exc.public_context == context
    ):
        error_id = _new_error_id()
        diagnostic = {
            "event": "approved_error_projected",
            "error_id": error_id,
            "context": context,
            "operation": _bounded_identifier(operation),
            "exception_type": error_type,
        }
        if diagnostic_hook is not None:
            diagnostic_hook(diagnostic)
        else:
            _LOGGER.warning(
                "approved runtime error projected",
                extra={"public_error": diagnostic},
            )
        return PublicErrorProjection(
            error_type=exc.public_error_type,
            error_message=exc.public_error_message,
            error_id=error_id,
        )
    if context == "mcp" and _is_approved_mcp_exception(exc):
        return PublicErrorProjection(
            error_type=error_type,
            error_message=_safe_mcp_message(error_type, None),
        )

    error_id = _new_error_id()
    diagnostic = {
        "error_id": error_id,
        "context": context,
        "operation": _bounded_identifier(operation),
        "exception_type": error_type,
    }
    if diagnostic_hook is not None:
        diagnostic_hook(diagnostic)
    else:
        _LOGGER.error(
            "unknown runtime error projected",
            extra={"public_error": diagnostic},
        )
    return PublicErrorProjection(
        error_type=_INTERNAL_ERROR_TYPES[context],
        error_message=_INTERNAL_ERROR_MESSAGES[context],
        error_id=error_id,
    )


def sanitize_public_error_fields(
    *,
    error_type: str | None,
    error_message: str | None,
    error_id: str | None = None,
    context: PublicErrorContext = "mcp",
    expected_not_found_type: str | None = None,
    expected_identifier: str | None = None,
    operation: str | None = None,
    diagnostic_hook: DiagnosticHook | None = None,
) -> dict[str, str | None]:
    """Apply a final defense-in-depth projection to already assembled fields."""

    normalized_type = str(error_type or "").strip()
    if context == "worker" and normalized_type in _FIXED_WORKER_MESSAGES:
        return {
            "error_type": normalized_type,
            "error_message": _FIXED_WORKER_MESSAGES[normalized_type],
            "error_id": _projection_error_id(
                error_id,
                context=context,
                operation=operation,
                reported_error_type=normalized_type,
                diagnostic_hook=diagnostic_hook,
            ),
        }
    if context == "mcp" and normalized_type in _MCP_NOT_FOUND_TYPES:
        if normalized_type != expected_not_found_type:
            return {
                "error_type": _INTERNAL_ERROR_TYPES[context],
                "error_message": _INTERNAL_ERROR_MESSAGES[context],
                "error_id": _projection_error_id(
                    error_id,
                    context=context,
                    operation=operation,
                    reported_error_type=normalized_type,
                    diagnostic_hook=diagnostic_hook,
                ),
            }
        return {
            "error_type": normalized_type,
            "error_message": _safe_mcp_not_found_message(
                normalized_type,
                expected_identifier,
            ),
            "error_id": None,
        }
    if context == "mcp" and normalized_type in _MCP_SAFE_ERROR_TYPES:
        return {
            "error_type": normalized_type,
            "error_message": _safe_mcp_message(normalized_type, error_message),
            "error_id": None,
        }
    return {
        "error_type": _INTERNAL_ERROR_TYPES[context],
        "error_message": _INTERNAL_ERROR_MESSAGES[context],
        "error_id": _projection_error_id(
            error_id,
            context=context,
            operation=operation,
            reported_error_type=normalized_type,
            diagnostic_hook=diagnostic_hook,
        ),
    }


def sanitize_mcp_result_payload(
    payload: dict[str, Any],
    *,
    expected_not_found_type: str | None = None,
    expected_identifier: str | None = None,
    operation: str | None = None,
    diagnostic_hook: DiagnosticHook | None = None,
) -> dict[str, Any]:
    """Sanitize a failed MCP result without changing successful payloads."""

    if payload.get("success") is True:
        return dict(payload)
    fields = sanitize_public_error_fields(
        error_type=_optional_text(payload.get("error_type")),
        error_message=_optional_text(payload.get("error_message")),
        error_id=_optional_text(payload.get("error_id")),
        context="mcp",
        expected_not_found_type=expected_not_found_type,
        expected_identifier=expected_identifier,
        operation=operation,
        diagnostic_hook=diagnostic_hook,
    )

    # Rebuild failed results from a closed set of structural fields. A caller
    # may hand this boundary a malformed result containing exception payloads
    # outside ``data`` (for example in prompt messages, descriptions, URIs, or
    # custom extension fields), so copying the input and redacting selected
    # keys is not a sufficient final wire-boundary guarantee.
    projected: dict[str, Any] = {
        "success": False,
        "error_type": fields["error_type"],
        "error_message": fields["error_message"],
    }
    safe_expected_identifier = _safe_mcp_not_found_identifier(
        expected_not_found_type,
        expected_identifier,
    )
    expected_identifier_field = {
        "MCPPromptNotFound": "name",
        "MCPResourceNotFound": "uri",
        "MCPToolNotFound": "tool_name",
    }.get(expected_not_found_type)
    for identifier_field in ("name", "tool_name", "uri"):
        if identifier_field in payload:
            projected[identifier_field] = (
                safe_expected_identifier
                if identifier_field == expected_identifier_field
                and safe_expected_identifier is not None
                else ""
            )
    if "description" in payload:
        projected["description"] = None
    if "messages" in payload:
        projected["messages"] = []
    if "mime_type" in payload:
        projected["mime_type"] = None
    if "data" in payload:
        projected["data"] = None
    if fields["error_id"] is None:
        projected.pop("error_id", None)
    else:
        projected["error_id"] = fields["error_id"]
    return projected


def _is_approved_mcp_exception(exc: BaseException) -> bool:
    if type(exc) in {PermissionError, ValueError}:
        return True
    error_type = type(exc).__name__
    module = type(exc).__module__
    return error_type in _ARTIFACT_ERROR_TYPES and module.startswith("framework.agent.artifacts.")


def _safe_mcp_message(error_type: str, error_message: str | None) -> str:
    return _FIXED_MCP_MESSAGES[error_type]


def _safe_mcp_not_found_message(
    error_type: str,
    identifier: str | None,
) -> str:
    prefix = {
        "MCPPromptNotFound": "unknown MCP prompt",
        "MCPResourceNotFound": "unknown MCP resource",
        "MCPToolNotFound": "unknown MCP tool",
    }[error_type]
    candidate = _safe_mcp_not_found_identifier(error_type, identifier)
    if candidate is None:
        return prefix
    return f"{prefix}: {candidate}"


def _safe_mcp_not_found_identifier(
    error_type: str | None,
    identifier: str | None,
) -> str | None:
    if error_type not in _MCP_NOT_FOUND_TYPES:
        return None
    candidate = str(identifier or "").strip()
    pattern = (
        _SAFE_MCP_RESOURCE
        if error_type == "MCPResourceNotFound"
        else _SAFE_MCP_NAME
    )
    return candidate if pattern.fullmatch(candidate) else None


def _bounded_identifier(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:128]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _new_error_id() -> str:
    return f"err_{uuid4().hex[:16]}"


def _valid_error_id(value: str | None) -> str | None:
    if value is None:
        return None
    return value if _SERVER_ERROR_ID.fullmatch(value) else None


def _projection_error_id(
    value: str | None,
    *,
    context: PublicErrorContext,
    operation: str | None,
    reported_error_type: str,
    diagnostic_hook: DiagnosticHook | None,
) -> str:
    existing = _valid_error_id(value)
    if existing is not None:
        return existing
    error_id = _new_error_id()
    diagnostic = {
        "event": "projection_rejected",
        "error_id": error_id,
        "context": context,
        "operation": _bounded_identifier(operation),
        "reported_error_type": _bounded_identifier(reported_error_type),
    }
    if diagnostic_hook is not None:
        diagnostic_hook(diagnostic)
    else:
        _LOGGER.warning(
            "unsafe preassembled error projection rejected",
            extra={"public_error": diagnostic},
        )
    return error_id


__all__ = [
    "ApprovedPublicError",
    "DiagnosticHook",
    "PublicErrorContext",
    "PublicErrorProjection",
    "project_public_error",
    "sanitize_mcp_result_payload",
    "sanitize_public_error_fields",
]
