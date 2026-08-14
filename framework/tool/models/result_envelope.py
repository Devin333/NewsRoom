from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Self

from framework.events.canonical import (
    canonical_json_bytes,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventCanonicalizationError
from framework.shared.redaction import DEFAULT_SENSITIVE_KEY_TOKENS
from framework.tool.governance.redaction import redact_sensitive_values
from framework.tool.models.definition import ToolDefinition
from framework.tool.models.observation import ToolObservation
from framework.tool.models.result import ToolPolicyTrace
from framework.tool.models.status import ToolStatus
from framework.tool.runtime.errors import ToolRuntimeError


TOOL_RESULT_ENVELOPE_SCHEMA = "newsroom.tool-result-envelope@1"
TOOL_SIDE_EFFECT_RECEIPT_SCHEMA = "newsroom.tool-side-effect-receipt@1"
_READ_ONLY_EFFECTS = frozenset({"", "none", "read_only"})
_NON_MATERIALIZABLE_STATUSES = frozenset(
    {ToolStatus.BLOCKED, ToolStatus.DENIED, ToolStatus.APPROVAL_REQUIRED}
)
_MAX_SUMMARY_BYTES = 8 * 1024
_REQUIRED_POLICY_CHECKS = ("tool.permission", "tool.approval")
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)
_EXACT_TOOL_REF = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:/+-]*@"
    r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z"
)


@dataclass(frozen=True, slots=True)
class ToolSideEffectReceipt:
    tool_id: str
    call_id: str
    attempt_id: str | None
    idempotency_key: str
    operation_id: str
    operation_kind: str
    local_attempt_no: int | None
    physical_attempt_started: bool
    status: str
    effect_kind: str
    effect_determinate: bool
    gate_checksum: str
    response_checksum: str
    receipt_schema: str = TOOL_SIDE_EFFECT_RECEIPT_SCHEMA
    receipt_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "tool_id",
            "call_id",
            "idempotency_key",
            "operation_id",
            "operation_kind",
            "status",
            "effect_kind",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ToolRuntimeError(
                    f"tool side-effect receipt {field_name} is required"
                )
            object.__setattr__(self, field_name, value)
        try:
            status = ToolStatus(self.status)
        except ValueError as exc:
            raise ToolRuntimeError(
                "tool side-effect receipt status is invalid"
            ) from exc
        if status in _NON_MATERIALIZABLE_STATUSES:
            raise ToolRuntimeError(
                "unauthorized or unapproved tool receipt cannot be materialized"
            )
        object.__setattr__(self, "status", status.value)
        if _EXACT_TOOL_REF.fullmatch(self.tool_id) is None:
            raise ToolRuntimeError(
                "tool side-effect receipt tool_id must be an exact reference"
            )
        if not isinstance(self.physical_attempt_started, bool):
            raise ToolRuntimeError(
                "tool side-effect receipt physical_attempt_started must be boolean"
            )
        attempt_id = self.attempt_id
        local_attempt_no = self.local_attempt_no
        if self.physical_attempt_started:
            attempt_id = str(attempt_id or "").strip()
            if not attempt_id:
                raise ToolRuntimeError(
                    "started tool side-effect receipt requires attempt_id"
                )
            if (
                not isinstance(local_attempt_no, int)
                or isinstance(local_attempt_no, bool)
                or local_attempt_no < 1
            ):
                raise ToolRuntimeError(
                    "started tool side-effect receipt requires positive local_attempt_no"
                )
        elif attempt_id is not None or local_attempt_no is not None:
            raise ToolRuntimeError(
                "not-started tool side-effect receipt cannot carry physical attempt identity"
            )
        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "local_attempt_no", local_attempt_no)
        if not isinstance(self.effect_determinate, bool):
            raise ToolRuntimeError(
                "tool side-effect receipt effect_determinate must be boolean"
            )
        _checksum(self.gate_checksum, "gate_checksum")
        _checksum(self.response_checksum, "response_checksum")
        if self.receipt_schema != TOOL_SIDE_EFFECT_RECEIPT_SCHEMA:
            raise ToolRuntimeError("unsupported tool side-effect receipt schema")
        object.__setattr__(
            self,
            "receipt_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "receipt_schema": self.receipt_schema,
            "tool_id": self.tool_id,
            "call_id": self.call_id,
            "attempt_id": self.attempt_id,
            "idempotency_key": self.idempotency_key,
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "physical_attempt_started": self.physical_attempt_started,
            "local_attempt_no": self.local_attempt_no,
            "status": self.status,
            "effect_kind": self.effect_kind,
            "effect_determinate": self.effect_determinate,
            "gate_checksum": self.gate_checksum,
            "response_checksum": self.response_checksum,
        }

    def control_projection(self) -> dict[str, Any]:
        return {
            "receipt_checksum": self.receipt_checksum,
            "effect_kind": self.effect_kind,
            "effect_determinate": self.effect_determinate,
            "attempt_id": self.attempt_id,
            "idempotency_key": self.idempotency_key,
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "physical_attempt_started": self.physical_attempt_started,
            "local_attempt_no": self.local_attempt_no,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_checksum": self.receipt_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected = {
            "receipt_schema",
            "tool_id",
            "call_id",
            "attempt_id",
            "idempotency_key",
            "operation_id",
            "operation_kind",
            "physical_attempt_started",
            "local_attempt_no",
            "status",
            "effect_kind",
            "effect_determinate",
            "gate_checksum",
            "response_checksum",
            "receipt_checksum",
        }
        _exact_keys(value, expected, "tool side-effect receipt")
        payload = dict(value)
        supplied = payload.pop("receipt_checksum")
        receipt = cls(**payload)
        if supplied != receipt.receipt_checksum:
            raise ToolRuntimeError("tool side-effect receipt checksum is invalid")
        return receipt


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    call_id: str
    tool_id: str
    status: str
    media_type: str
    response: Any = field(repr=False, compare=False)
    response_checksum: str
    response_bytes: int
    summary: str
    control_projection: Mapping[str, Any]
    policy_trace_checksum: str
    gate_checksum: str
    retry_count: int
    timeout: bool
    termination_confirmed: bool | None
    indeterminate: bool
    error_code: str | None = None
    side_effect_receipt: ToolSideEffectReceipt | None = None
    envelope_schema: str = TOOL_RESULT_ENVELOPE_SCHEMA
    envelope_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("call_id", "tool_id", "status", "media_type"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ToolRuntimeError(f"tool result envelope {field_name} is required")
            object.__setattr__(self, field_name, value)
        try:
            status = ToolStatus(self.status)
        except ValueError as exc:
            raise ToolRuntimeError("tool result envelope status is invalid") from exc
        if status in _NON_MATERIALIZABLE_STATUSES:
            raise ToolRuntimeError(
                "unauthorized or unapproved tool result cannot be materialized"
            )
        if _EXACT_TOOL_REF.fullmatch(self.tool_id) is None:
            raise ToolRuntimeError(
                "tool result envelope tool_id must be an exact reference"
            )
        normalized_media_type = self.media_type.casefold()
        if _MEDIA_TYPE.fullmatch(normalized_media_type) is None:
            raise ToolRuntimeError("tool result envelope media_type is invalid")
        object.__setattr__(self, "status", status.value)
        object.__setattr__(self, "media_type", normalized_media_type)
        if (
            not isinstance(self.response_bytes, int)
            or isinstance(self.response_bytes, bool)
            or self.response_bytes < 0
        ):
            raise ToolRuntimeError(
                "tool result envelope response_bytes is invalid"
            )
        canonical, response_bytes = _serialize_response(self.response, self.media_type)
        actual_checksum = _sha256(response_bytes)
        if (
            self.response_checksum != actual_checksum
            or self.response_bytes != len(response_bytes)
        ):
            raise ToolRuntimeError("tool result envelope response integrity is invalid")
        object.__setattr__(self, "response", canonical)
        summary = str(self.summary).strip()
        if not summary or len(summary.encode("utf-8")) > _MAX_SUMMARY_BYTES:
            raise ToolRuntimeError("tool result envelope summary is invalid")
        object.__setattr__(self, "summary", summary)
        try:
            projection = normalize_canonical_json(
                self.control_projection,
                path="tool_result.control_projection",
            )
        except EventCanonicalizationError as exc:
            raise ToolRuntimeError(
                "tool result control projection must be canonical JSON"
            ) from exc
        if not isinstance(projection, Mapping):
            raise ToolRuntimeError("tool result control projection must be an object")
        object.__setattr__(self, "control_projection", projection)
        _checksum(self.policy_trace_checksum, "policy_trace_checksum")
        _checksum(self.gate_checksum, "gate_checksum")
        if (
            not isinstance(self.retry_count, int)
            or isinstance(self.retry_count, bool)
            or self.retry_count < 0
        ):
            raise ToolRuntimeError("tool result envelope retry_count is invalid")
        if not isinstance(self.timeout, bool):
            raise ToolRuntimeError("tool result envelope timeout must be boolean")
        if self.timeout is not (status is ToolStatus.TIMEOUT):
            raise ToolRuntimeError(
                "tool result envelope timeout conflicts with status"
            )
        if self.termination_confirmed is not None and not isinstance(
            self.termination_confirmed,
            bool,
        ):
            raise ToolRuntimeError(
                "tool result envelope termination_confirmed must be boolean or null"
            )
        if not isinstance(self.indeterminate, bool):
            raise ToolRuntimeError(
                "tool result envelope indeterminate must be boolean"
            )
        if self.indeterminate and self.termination_confirmed is True:
            raise ToolRuntimeError(
                "indeterminate Tool result cannot confirm termination"
            )
        if self.error_code is not None:
            object.__setattr__(self, "error_code", str(self.error_code).strip() or None)
        if status in {ToolStatus.FAILED, ToolStatus.TIMEOUT} and self.error_code is None:
            raise ToolRuntimeError(
                "failed Tool result envelope requires an error_code"
            )
        if status is ToolStatus.SUCCEEDED and self.error_code is not None:
            raise ToolRuntimeError(
                "successful Tool result envelope cannot carry an error_code"
            )
        if self.side_effect_receipt is not None:
            if not isinstance(self.side_effect_receipt, ToolSideEffectReceipt):
                raise ToolRuntimeError("tool result side_effect_receipt is invalid")
            if (
                self.side_effect_receipt.tool_id != self.tool_id
                or self.side_effect_receipt.call_id != self.call_id
                or self.side_effect_receipt.status != self.status
                or self.side_effect_receipt.gate_checksum != self.gate_checksum
                or self.side_effect_receipt.response_checksum
                != self.response_checksum
            ):
                raise ToolRuntimeError(
                    "tool result side-effect receipt conflicts with its envelope"
                )
        if self.envelope_schema != TOOL_RESULT_ENVELOPE_SCHEMA:
            raise ToolRuntimeError("unsupported tool result envelope schema")
        object.__setattr__(
            self,
            "envelope_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_observation(
        cls,
        observation: ToolObservation,
        definition: ToolDefinition,
    ) -> Self:
        if not isinstance(observation, ToolObservation):
            raise TypeError("observation must be ToolObservation")
        if not isinstance(definition, ToolDefinition):
            raise TypeError("definition must be ToolDefinition")
        result = observation.result
        if (
            observation.call.tool_name != definition.name
            or result.tool_name != definition.name
            or result.call_id != observation.call.call_id
            or result.metadata.get("resolved_tool_id") != definition.tool_id
        ):
            raise ToolRuntimeError(
                "tool result identity conflicts with its resolved definition"
            )
        if result.status in _NON_MATERIALIZABLE_STATUSES:
            raise ToolRuntimeError(
                "unauthorized or unapproved tool result cannot be materialized"
            )
        if result.artifact_refs or result.metadata.get("artifact_spill") == "spilled":
            raise ToolRuntimeError(
                "legacy pre-spilled tool result cannot enter Harness materialization"
            )
        policy_trace = ToolPolicyTrace.from_any(result.policy_trace)
        _validate_policy_trace(policy_trace, definition)
        gate_result = result.gate_result
        gate_result = _validated_gate_result(
            gate_result,
            call_id=observation.call.call_id,
            tool_name=definition.name,
        )
        if result.status is ToolStatus.SUCCEEDED and gate_result["passed"] is not True:
            raise ToolRuntimeError(
                "successful tool result requires a passing deterministic gate"
            )
        if (
            result.status in {ToolStatus.FAILED, ToolStatus.TIMEOUT}
            and gate_result["passed"] is not False
        ):
            raise ToolRuntimeError(
                "failed tool result requires a blocking deterministic gate"
            )
        policy_checksum = checksum_for(policy_trace.to_dict())
        gate_checksum = checksum_for(gate_result)
        contract = definition.result_persistence
        if result.status is ToolStatus.SUCCEEDED:
            safe_response = _safe_response(result.redacted_output, contract.media_type)
            media_type = contract.media_type
            control_fields = contract.control_projection(safe_response)
        else:
            safe_response = {
                "error_code": str(result.error_type or "ToolRuntimeError"),
                "error_message": redact_sensitive_values(
                    str(result.error_message or "tool execution did not succeed")
                ),
                "indeterminate": bool(result.indeterminate),
                "termination_confirmed": result.termination_confirmed,
            }
            media_type = "application/json"
            control_fields = {}
        canonical, response_bytes = _serialize_response(safe_response, media_type)
        response_checksum = _sha256(response_bytes)
        receipt = (
            _side_effect_receipt(
                observation,
                definition,
                gate_checksum=gate_checksum,
                response_checksum=response_checksum,
            )
            if definition.side_effect_value.casefold() not in _READ_ONLY_EFFECTS
            else None
        )
        projection = {
            "tool_call_id": observation.call.call_id,
            "tool_id": definition.tool_id,
            "tool_status": result.status.value,
            "response_checksum": response_checksum,
            "gate_checksum": gate_checksum,
            "policy_trace_checksum": policy_checksum,
            "retry_count": result.retry_count,
            "timeout": result.timeout,
            **control_fields,
        }
        if receipt is not None:
            projection["side_effect_receipt"] = receipt.control_projection()
        return cls(
            call_id=observation.call.call_id,
            tool_id=definition.tool_id,
            status=result.status.value,
            media_type=media_type,
            response=canonical,
            response_checksum=response_checksum,
            response_bytes=len(response_bytes),
            summary=_bounded_summary(observation),
            control_projection=projection,
            policy_trace_checksum=policy_checksum,
            gate_checksum=gate_checksum,
            retry_count=result.retry_count,
            timeout=result.timeout,
            termination_confirmed=result.termination_confirmed,
            indeterminate=result.indeterminate,
            error_code=result.error_type,
            side_effect_receipt=receipt,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "envelope_schema": self.envelope_schema,
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "status": self.status,
            "media_type": self.media_type,
            "response_checksum": self.response_checksum,
            "response_bytes": self.response_bytes,
            "summary": self.summary,
            "control_projection": thaw_canonical_json(self.control_projection),
            "policy_trace_checksum": self.policy_trace_checksum,
            "gate_checksum": self.gate_checksum,
            "retry_count": self.retry_count,
            "timeout": self.timeout,
            "termination_confirmed": self.termination_confirmed,
            "indeterminate": self.indeterminate,
            "error_code": self.error_code,
            "side_effect_receipt": (
                self.side_effect_receipt.to_dict()
                if self.side_effect_receipt is not None
                else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        encoding, value = _encoded_response(self.response, self.media_type)
        return {
            **self.checksum_projection(),
            "response_encoding": encoding,
            "response": value,
            "envelope_checksum": self.envelope_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected = {
            "envelope_schema",
            "call_id",
            "tool_id",
            "status",
            "media_type",
            "response_checksum",
            "response_bytes",
            "summary",
            "control_projection",
            "policy_trace_checksum",
            "gate_checksum",
            "retry_count",
            "timeout",
            "termination_confirmed",
            "indeterminate",
            "error_code",
            "side_effect_receipt",
            "response_encoding",
            "response",
            "envelope_checksum",
        }
        _exact_keys(value, expected, "tool result envelope")
        payload = dict(value)
        supplied_checksum = payload.pop("envelope_checksum")
        encoding = payload.pop("response_encoding")
        response = payload.pop("response")
        payload["response"] = _decoded_response(
            encoding,
            response,
            payload["media_type"],
        )
        receipt = payload.get("side_effect_receipt")
        if receipt is not None and not isinstance(receipt, Mapping):
            raise ToolRuntimeError("tool result side_effect_receipt is invalid")
        payload["side_effect_receipt"] = (
            ToolSideEffectReceipt.from_dict(receipt)
            if isinstance(receipt, Mapping)
            else None
        )
        result = cls(**payload)
        if supplied_checksum != result.envelope_checksum:
            raise ToolRuntimeError("tool result envelope checksum is invalid")
        return result


def _validate_policy_trace(
    trace: ToolPolicyTrace | None,
    definition: ToolDefinition,
) -> None:
    if trace is None or trace.tool_name != definition.name or not trace.allowed:
        raise ToolRuntimeError("tool result lacks an allowed policy trace")
    checks = {
        str(check.get("check_id")): bool(check.get("passed"))
        for check in trace.checks
    }
    if any(checks.get(check_id) is not True for check_id in _REQUIRED_POLICY_CHECKS):
        raise ToolRuntimeError(
            "tool result lacks completed permission and approval checks"
        )
    if trace.requires_approval and trace.approval_granted is not True:
        raise ToolRuntimeError("tool result lacks required approval evidence")


def _validated_gate_result(
    value: Any,
    *,
    call_id: str,
    tool_name: str,
) -> dict[str, Any]:
    root_fields = {
        "gate_id",
        "passed",
        "mode",
        "checks",
        "failed_dimensions",
        "decision",
        "reason",
        "metadata",
    }
    if not isinstance(value, Mapping) or set(value) != root_fields:
        raise ToolRuntimeError(
            "tool result requires a completed deterministic gate"
        )
    if value["gate_id"] != f"tool:{call_id}:gate" or value["mode"] != "and":
        raise ToolRuntimeError("tool result deterministic gate identity is invalid")
    if not isinstance(value["passed"], bool):
        raise ToolRuntimeError("tool result deterministic gate outcome is invalid")
    checks = value["checks"]
    if (
        isinstance(checks, (str, bytes, bytearray))
        or not isinstance(checks, Sequence)
        or not checks
    ):
        raise ToolRuntimeError("tool result deterministic gate checks are invalid")
    check_fields = {
        "check_id",
        "dimension",
        "passed",
        "severity",
        "reason",
        "metadata",
    }
    normalized_checks: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, Mapping) or set(check) != check_fields:
            raise ToolRuntimeError("tool result deterministic gate checks are invalid")
        if (
            not isinstance(check["check_id"], str)
            or not check["check_id"].strip()
            or not isinstance(check["dimension"], str)
            or not check["dimension"].strip()
            or not isinstance(check["passed"], bool)
            or check["severity"] not in {"warning", "error", "critical"}
            or not isinstance(check["reason"], str)
            or not isinstance(check["metadata"], Mapping)
        ):
            raise ToolRuntimeError("tool result deterministic gate checks are invalid")
        normalized_checks.append(
            {
                **dict(check),
                "metadata": dict(check["metadata"]),
            }
        )
    failed_dimensions = sorted(
        {
            check["dimension"]
            for check in normalized_checks
            if check["passed"] is False
        }
    )
    if value["failed_dimensions"] != failed_dimensions:
        raise ToolRuntimeError("tool result deterministic gate outcome is invalid")
    blocking = any(
        check["passed"] is False
        and check["severity"] in {"error", "critical"}
        for check in normalized_checks
    )
    expected_decision = "block" if blocking else (
        "warn" if failed_dimensions else "pass"
    )
    if (
        value["passed"] is blocking
        or value["decision"] != expected_decision
        or not isinstance(value["reason"], str)
    ):
        raise ToolRuntimeError("tool result deterministic gate outcome is invalid")
    metadata = value["metadata"]
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("call_id") != call_id
        or metadata.get("tool_name") != tool_name
    ):
        raise ToolRuntimeError("tool result deterministic gate identity is invalid")
    return {
        **dict(value),
        "checks": normalized_checks,
        "failed_dimensions": failed_dimensions,
        "metadata": dict(metadata),
    }


def _side_effect_receipt(
    observation: ToolObservation,
    definition: ToolDefinition,
    *,
    gate_checksum: str,
    response_checksum: str,
) -> ToolSideEffectReceipt:
    result = observation.result
    return ToolSideEffectReceipt(
        tool_id=definition.tool_id,
        call_id=observation.call.call_id,
        attempt_id=result.attempt_id,
        idempotency_key=result.idempotency_key or "",
        operation_id=result.operation_id or "",
        operation_kind=result.operation_kind or "",
        local_attempt_no=result.local_attempt_no,
        physical_attempt_started=result.attempt_id is not None,
        status=result.status.value,
        effect_kind=definition.side_effect_value,
        effect_determinate=(
            result.termination_confirmed is not False and not result.indeterminate
        ),
        gate_checksum=gate_checksum,
        response_checksum=response_checksum,
    )


def _safe_response(value: Any, media_type: str) -> Any:
    if media_type == "application/json" or media_type.endswith("+json"):
        return _prune_sensitive_json(redact_sensitive_values(value))
    if media_type.startswith("text/"):
        return redact_sensitive_values(str(value))
    if not isinstance(value, (bytes, bytearray)):
        raise ToolRuntimeError("binary tool result is missing exact response bytes")
    return bytes(value)


def _prune_sensitive_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(token in normalized for token in DEFAULT_SENSITIVE_KEY_TOKENS):
                continue
            result[str(key)] = _prune_sensitive_json(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_prune_sensitive_json(item) for item in value]
    return value


def _bounded_summary(observation: ToolObservation) -> str:
    text = str(redact_sensitive_values(observation.summary)).strip() or (
        f"Tool {observation.call.tool_name} {observation.status.value}"
    )
    encoded = text.encode("utf-8")
    if len(encoded) <= _MAX_SUMMARY_BYTES:
        return text
    truncated = encoded[: _MAX_SUMMARY_BYTES - 3]
    while True:
        try:
            return truncated.decode("utf-8") + "..."
        except UnicodeDecodeError:
            truncated = truncated[:-1]


def _serialize_response(value: Any, media_type: str) -> tuple[Any, bytes]:
    normalized = str(media_type).strip().casefold()
    if normalized == "application/json" or normalized.endswith("+json"):
        try:
            canonical = normalize_canonical_json(value, path="tool_result.response")
        except EventCanonicalizationError as exc:
            raise ToolRuntimeError("tool result response must be canonical JSON") from exc
        return canonical, canonical_json_bytes(canonical)
    if normalized.startswith("text/"):
        if not isinstance(value, str):
            raise ToolRuntimeError("tool result text response must be a string")
        return value, value.encode("utf-8")
    if not isinstance(value, (bytes, bytearray)):
        raise ToolRuntimeError("tool result binary response must be bytes")
    detached = bytes(value)
    return detached, detached


def _encoded_response(value: Any, media_type: str) -> tuple[str, Any]:
    if media_type == "application/json" or media_type.endswith("+json"):
        return "json", thaw_canonical_json(value)
    if media_type.startswith("text/"):
        return "text", value
    return "base64", base64.b64encode(value).decode("ascii")


def _decoded_response(encoding: Any, value: Any, media_type: Any) -> Any:
    normalized = str(media_type).strip().casefold()
    if encoding == "json" and (
        normalized == "application/json" or normalized.endswith("+json")
    ):
        return value
    if encoding == "text" and normalized.startswith("text/"):
        return value
    if encoding == "base64" and not normalized.startswith("text/"):
        try:
            return base64.b64decode(value, validate=True)
        except (TypeError, ValueError, base64.binascii.Error) as exc:
            raise ToolRuntimeError("tool result base64 response is invalid") from exc
    raise ToolRuntimeError("tool result response encoding conflicts with media_type")


def _sha256(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def _checksum(value: Any, field_name: str) -> str:
    text = str(value)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise ToolRuntimeError(f"tool result {field_name} is invalid")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise ToolRuntimeError(f"tool result {field_name} is invalid") from exc
    if text != text.casefold():
        raise ToolRuntimeError(f"tool result {field_name} is invalid")
    return text


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ToolRuntimeError(f"{label} fields are invalid")


__all__ = [
    "TOOL_RESULT_ENVELOPE_SCHEMA",
    "TOOL_SIDE_EFFECT_RECEIPT_SCHEMA",
    "ToolResultEnvelope",
    "ToolSideEffectReceipt",
]
