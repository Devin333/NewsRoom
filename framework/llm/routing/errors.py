from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from framework.llm.redaction import redact_sensitive_values


class LLMRouteError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        route_id: str,
        error_type: str,
        retryable: bool = False,
        attempted_deployments: Iterable[str] = (),
        errors: Iterable[dict[str, Any]] = (),
        events: Iterable[dict[str, Any]] = (),
        manifest: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.route_id = route_id
        self.error_type = error_type
        self.retryable = retryable
        self.attempted_deployments = tuple(attempted_deployments)
        self.errors = tuple(dict(error) for error in errors)
        self.events = tuple(dict(event) for event in events)
        self.manifest = dict(manifest or {})

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": str(self),
            "route_id": self.route_id,
            "error_type": self.error_type,
            "retryable": self.retryable,
            "attempted_deployments": list(self.attempted_deployments),
            "errors": [dict(error) for error in self.errors],
            "events": [dict(event) for event in self.events],
            "manifest": dict(self.manifest),
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload
