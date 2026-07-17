import logging
import re

import pytest

from framework.artifacts import ArtifactChecksumMismatchError
from framework.shared.public_errors import (
    ApprovedPublicError,
    project_public_error,
    sanitize_mcp_result_payload,
    sanitize_public_error_fields,
)


def test_unknown_exception_projects_fixed_public_fields_and_safe_diagnostic() -> None:
    diagnostics = []
    secret = "postgresql://operator:password@db.internal/news"

    projection = project_public_error(
        RuntimeError(secret),
        context="mcp",
        operation="call_tool",
        diagnostic_hook=diagnostics.append,
    )

    assert projection.error_type == "MCPInternalError"
    assert projection.error_message == "internal error"
    assert projection.error_id.startswith("err_")
    assert diagnostics == [
        {
            "error_id": projection.error_id,
            "context": "mcp",
            "operation": "call_tool",
            "exception_type": "RuntimeError",
        }
    ]
    assert secret not in str(projection.to_dict())
    assert secret not in str(diagnostics)


def test_unknown_exception_never_writes_raw_exception_details_to_log(caplog) -> None:
    secret = "postgresql://operator:password@db.internal/news"

    with caplog.at_level(logging.ERROR, logger="newsroom.public_errors"):
        projection = project_public_error(RuntimeError(secret), context="mcp")

    assert projection.error_type == "MCPInternalError"
    assert secret not in caplog.text


def test_approved_artifact_integrity_error_preserves_typed_contract() -> None:
    projection = project_public_error(
        ArtifactChecksumMismatchError("artifact integrity verification failed"),
        context="mcp",
    )

    assert projection.to_dict() == {
        "error_type": "ArtifactChecksumMismatchError",
        "error_message": "artifact integrity verification failed",
        "error_id": None,
    }


def test_approved_fixed_error_does_not_render_hostile_exception_argument() -> None:
    class ExplodingText:
        def __str__(self) -> str:
            raise RuntimeError("hidden-valueerror-render-secret")

    projection = project_public_error(ValueError(ExplodingText()), context="mcp")

    assert projection.to_dict() == {
        "error_type": "ValueError",
        "error_message": "invalid MCP request",
        "error_id": None,
    }


def test_exception_name_spoof_does_not_enter_approved_allowlist() -> None:
    fake_artifact_error = type(
        "ArtifactChecksumMismatchError",
        (RuntimeError,),
        {"__module__": "third_party.driver"},
    )

    projection = project_public_error(
        fake_artifact_error("Bearer super-secret-token"),
        context="mcp",
        diagnostic_hook=lambda diagnostic: None,
    )

    assert projection.error_type == "MCPInternalError"
    assert projection.error_message == "internal error"


def test_final_mcp_and_worker_projection_reject_unapproved_error_fields() -> None:
    secret = "Bearer super-secret-token"

    mcp = sanitize_mcp_result_payload(
        {
            "success": False,
            "data": {"secret": secret},
            "error_type": "DatabaseDriverError",
            "error_message": secret,
            "error_id": "../../unsafe",
        }
    )
    worker = sanitize_public_error_fields(
        error_type="DatabaseDriverError",
        error_message=secret,
        context="worker",
    )

    assert mcp["data"] is None
    assert mcp["error_type"] == "MCPInternalError"
    assert mcp["error_message"] == "internal error"
    assert mcp["error_id"].startswith("err_")
    assert worker["error_type"] == "WorkerInternalError"
    assert worker["error_message"] == "task execution failed"
    assert worker["error_id"].startswith("err_")
    assert secret not in str(mcp)
    assert secret not in str(worker)


def test_mcp_projection_preserves_fixed_durable_event_error_contracts() -> None:
    secret = "postgresql://operator:password@db.internal/news"

    unavailable = sanitize_mcp_result_payload(
        {
            "success": False,
            "data": {"dsn": secret},
            "error_type": "EventStoreUnavailableError",
            "error_message": secret,
        },
        operation="call_tool",
    )
    conflict = sanitize_mcp_result_payload(
        {
            "success": False,
            "error_type": "EventContractError",
            "error_message": secret,
        },
        operation="call_tool",
    )

    assert unavailable == {
        "success": False,
        "data": None,
        "error_type": "EventStoreUnavailableError",
        "error_message": "event store is unavailable",
    }
    assert conflict == {
        "success": False,
        "error_type": "EventContractError",
        "error_message": (
            "event operator data conflicts with the durable event contract"
        ),
    }
    assert secret not in str(unavailable)
    assert secret not in str(conflict)


@pytest.mark.parametrize(
    ("error_type", "message"),
    (
        ("EventAuthorizationError", "event operator action is not authorized"),
        (
            "EventOperationCapabilityUnavailableError",
            "event operator capability is unavailable",
        ),
        ("EventOperationNotFoundError", "event operator resource not found"),
        ("EventRuntimeError", "event runtime operation failed"),
    ),
)
def test_mcp_projection_preserves_all_fixed_event_operator_errors(
    error_type,
    message,
) -> None:
    projected = sanitize_mcp_result_payload(
        {
            "success": False,
            "error_type": error_type,
            "error_message": "unsafe backend detail",
        },
        operation="call_tool",
    )

    assert projected == {
        "success": False,
        "error_type": error_type,
        "error_message": message,
    }


def test_failed_mcp_projection_drops_all_untrusted_payload_extensions() -> None:
    secret = "Bearer super-secret-token"

    projected = sanitize_mcp_result_payload(
        {
            "success": False,
            "name": secret,
            "tool_name": secret,
            "uri": f"news://missing?token={secret}",
            "description": secret,
            "messages": [{"role": "user", "content": secret}],
            "mime_type": secret,
            "data": {"secret": secret},
            "debug_extension": {"trace": secret},
            "error_type": "DatabaseDriverError",
            "error_message": secret,
        }
    )

    assert projected == {
        "success": False,
        "name": "",
        "tool_name": "",
        "uri": "",
        "description": None,
        "messages": [],
        "mime_type": None,
        "data": None,
        "error_type": "MCPInternalError",
        "error_message": "internal error",
        "error_id": projected["error_id"],
    }
    assert projected["error_id"].startswith("err_")
    assert secret not in str(projected)


def test_not_found_projection_rebuilds_message_from_expected_request() -> None:
    secret = "sk_live_ABC123456789"

    projected = sanitize_mcp_result_payload(
        {
            "success": False,
            "tool_name": secret,
            "error_type": "MCPToolNotFound",
            "error_message": f"unknown MCP tool: {secret}",
        },
        expected_not_found_type="MCPToolNotFound",
        expected_identifier="news.unknown",
    )

    assert projected["error_type"] == "MCPToolNotFound"
    assert projected["error_message"] == "unknown MCP tool: news.unknown"
    assert "error_id" not in projected
    assert secret not in str(projected)


def test_unknown_projection_rejects_forged_server_error_id() -> None:
    forged = "err_skLiveSecret123"
    diagnostics = []

    projected = sanitize_mcp_result_payload(
        {
            "success": False,
            "error_type": "DatabaseDriverError",
            "error_message": "unsafe detail",
            "error_id": forged,
        },
        operation="call_tool",
        diagnostic_hook=diagnostics.append,
    )

    assert projected["error_id"] != forged
    assert re.fullmatch(r"err_[0-9a-f]{16}", projected["error_id"])
    assert forged not in str(projected)
    assert diagnostics == [
        {
            "event": "projection_rejected",
            "error_id": projected["error_id"],
            "context": "mcp",
            "operation": "call_tool",
            "reported_error_type": "DatabaseDriverError",
        }
    ]


def test_malformed_mcp_result_fails_closed() -> None:
    payload = sanitize_mcp_result_payload(
        {
            "data": {"private": "raw result"},
            "error_message": "driver detail",
        }
    )

    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error_type"] == "MCPInternalError"
    assert payload["error_message"] == "internal error"
    assert payload["error_id"].startswith("err_")


def test_safe_worker_stale_lease_projection_has_fixed_message() -> None:
    projection = sanitize_public_error_fields(
        error_type="StaleTaskLeaseError",
        error_message="late owner secret details",
        error_id="err_1234abcd1234abcd",
        context="worker",
    )

    assert projection == {
        "error_type": "StaleTaskLeaseError",
        "error_message": "task lease is stale",
        "error_id": "err_1234abcd1234abcd",
    }


def test_approved_worker_exception_preserves_typed_contract_and_diagnostic() -> None:
    diagnostics = []
    exc = ApprovedPublicError(
        "internal ownership detail",
        context="worker",
        error_type="StaleTaskLeaseError",
        error_message="task lease is stale",
    )

    projection = project_public_error(
        exc,
        context="worker",
        operation="renew",
        diagnostic_hook=diagnostics.append,
    )

    assert projection.error_type == "StaleTaskLeaseError"
    assert projection.error_message == "task lease is stale"
    assert re.fullmatch(r"err_[0-9a-f]{16}", projection.error_id)
    assert diagnostics == [
        {
            "event": "approved_error_projected",
            "error_id": projection.error_id,
            "context": "worker",
            "operation": "renew",
            "exception_type": "ApprovedPublicError",
        }
    ]
