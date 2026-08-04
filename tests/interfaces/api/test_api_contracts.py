from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.api.errors import ApiErrorCode, map_exception
from interfaces.api.responses import error, success
from interfaces.models import ApiMeta, PageRequest, ReportStatus, RunStatus
from interfaces.events import AuditEmitter, InMemoryAuditSink


def test_success_helper_builds_standard_envelope() -> None:
    payload = success({"ok": True})

    assert payload["success"] is True
    assert payload["data"] == {"ok": True}
    assert payload["error"] is None
    assert payload["request_id"].startswith("req_")
    assert payload["schema_version"] == "1.0"


def test_error_helper_builds_standard_envelope_with_matching_request_id() -> None:
    response = error(
        status_code=404,
        code=ApiErrorCode.RUN_NOT_FOUND.value,
        message="missing run",
        details={"path": "runs/missing"},
        user_action_required=True,
    )
    payload = response.body.decode("utf-8")

    assert response.status_code == 404
    assert "\"success\":false" in payload
    assert "\"code\":\"run_not_found\"" in payload
    assert "\"schema_version\":\"1.0\"" in payload


def test_api_success_envelope_preserves_client_request_id() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))

    response = client.get("/health", headers={"X-Request-ID": "contract-success"})
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "contract-success"
    assert payload["success"] is True
    assert payload["request_id"] == "contract-success"
    assert payload["schema_version"] == "1.0"


def test_api_validation_error_uses_contract_envelope() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={"sourceUrl": "https://arxiv.org/abs/2401.00001"},
        headers={"X-Request-ID": "contract-invalid"},
    )
    payload = response.json()

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "contract-invalid"
    assert payload["success"] is False
    assert payload["request_id"] == "contract-invalid"
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == ApiErrorCode.INVALID_REQUEST.value
    assert payload["error"]["request_id"] == payload["request_id"]
    assert payload["error"]["user_action_required"] is True
    assert payload["error"]["details"]["errors"][0]["loc"] == ["body", "paperId"]


def test_api_unknown_route_uses_contract_envelope() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))

    response = client.get("/api/v1/unknown-contract-route", headers={"X-Request-ID": "contract-404"})
    payload = response.json()

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "contract-404"
    assert payload["success"] is False
    assert payload["request_id"] == "contract-404"
    assert payload["schema_version"] == "1.0"
    assert payload["error"]["code"] == ApiErrorCode.NOT_FOUND.value
    assert payload["error"]["request_id"] == payload["request_id"]


def test_api_unhandled_exception_uses_safe_envelope_and_one_request_id() -> None:
    secret = "postgresql://operator:password@db.internal/news"
    sink = InMemoryAuditSink()
    client = TestClient(
        create_app(
            report_service_factory=lambda: _ExplodingReportService(secret),
            audit_emitter_factory=lambda: AuditEmitter(sink),
        ),
        raise_server_exceptions=False,
    )

    response = client.get(
        "/api/v1/reports/latest",
        headers={"X-Request-ID": "contract-internal"},
    )
    payload = response.json()

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "contract-internal"
    assert payload["success"] is False
    assert payload["request_id"] == "contract-internal"
    assert payload["error"]["request_id"] == "contract-internal"
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == "internal server error"
    assert payload["error"]["details"]["error_id"].startswith("err_")
    assert sink.records[-1].actor.request_id == "contract-internal"
    assert secret not in response.text
    assert secret not in str(sink.records[-1].to_dict())


def test_api_generated_request_id_survives_unhandled_exception_and_audit() -> None:
    sink = InMemoryAuditSink()
    client = TestClient(
        create_app(
            report_service_factory=lambda: _ExplodingReportService("unsafe detail"),
            audit_emitter_factory=lambda: AuditEmitter(sink),
        ),
        raise_server_exceptions=False,
    )

    response = client.get("/api/v1/reports/latest")
    payload = response.json()

    request_id = response.headers["x-request-id"]
    assert request_id.startswith("req_")
    assert payload["request_id"] == request_id
    assert payload["error"]["request_id"] == request_id
    assert sink.records[-1].actor.request_id == request_id


def test_contract_models_include_api_meta_pagination_and_status_aliases() -> None:
    meta = ApiMeta(request_id="contract-meta")
    page = PageRequest(limit=10, offset=0)
    run_status: RunStatus = "waiting_for_human"
    report_status: ReportStatus = "needs_review"

    assert meta.schema_version == "1.0"
    assert page.limit == 10
    assert page.offset == 0
    assert run_status == "waiting_for_human"
    assert report_status == "needs_review"


def test_map_exception_returns_structured_error_tuple() -> None:
    status_code, code, message, details = map_exception(ValueError("bad input"))

    assert status_code == 400
    assert code == ApiErrorCode.INVALID_REQUEST
    assert message == "bad input"
    assert details == {}


class _ExplodingReportService:
    def __init__(self, message: str) -> None:
        self.message = message

    def latest_report(self):
        raise RuntimeError(self.message)
