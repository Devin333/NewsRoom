from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from core.framework.tools.redaction import redact_sensitive_values
from interfaces.webhooks.signatures import build_signature_header


HttpOpener = Callable[[urllib.request.Request, int | None], Any]
DeadLetterSink = Callable[["OutgoingWebhookDeadLetter"], None]


@dataclass(frozen=True)
class OutgoingWebhookAttempt:
    attempt: int
    status_code: int | None = None
    response_body: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "status_code": self.status_code,
            "success": self.success,
            "response_body": self.response_body,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class OutgoingWebhookResult:
    url: str
    status_code: int
    response_body: str
    attempts: tuple[OutgoingWebhookAttempt, ...] = field(default_factory=tuple)
    dead_lettered: bool = False

    @property
    def success(self) -> bool:
        return 200 <= self.status_code < 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "success": self.success,
            "response_body": self.response_body,
            "attempt_count": len(self.attempts) or 1,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "dead_lettered": self.dead_lettered,
        }


@dataclass(frozen=True)
class OutgoingWebhookDeadLetter:
    url: str
    event_type: str
    payload: dict[str, Any]
    attempts: tuple[OutgoingWebhookAttempt, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "event_type": self.event_type,
            "payload": redact_sensitive_values(dict(self.payload)),
            "attempt_count": len(self.attempts),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "reason": self.reason,
        }


class OutgoingWebhookClient:
    def __init__(
        self,
        *,
        secret: str | None = None,
        timeout: int | None = 10,
        opener: HttpOpener | None = None,
        max_attempts: int = 1,
        dead_letter_sink: DeadLetterSink | None = None,
    ) -> None:
        self.secret = secret
        self.timeout = timeout
        self._opener = opener or _default_opener
        self.max_attempts = _max_attempts(max_attempts)
        self.dead_letter_sink = dead_letter_sink

    def send(self, url: str, event_type: str, payload: dict[str, Any]) -> OutgoingWebhookResult:
        body = json.dumps(
            {"event_type": event_type, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-News-Event-Type": event_type,
        }
        if self.secret:
            headers["X-News-Signature"] = build_signature_header(body, self.secret)
        attempts = []
        for attempt_number in range(1, self.max_attempts + 1):
            request = urllib.request.Request(url, data=body, method="POST", headers=headers)
            try:
                with self._opener(request, self.timeout) as response:
                    response_body = response.read().decode("utf-8", errors="replace")
                    attempt = OutgoingWebhookAttempt(
                        attempt=attempt_number,
                        status_code=int(getattr(response, "status", 200)),
                        response_body=response_body,
                    )
            except urllib.error.HTTPError as exc:
                response_body = exc.read().decode("utf-8", errors="replace")
                attempt = OutgoingWebhookAttempt(
                    attempt=attempt_number,
                    status_code=int(exc.code),
                    response_body=response_body,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            except Exception as exc:
                attempt = OutgoingWebhookAttempt(
                    attempt=attempt_number,
                    status_code=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            attempts.append(attempt)
            if attempt.success:
                return OutgoingWebhookResult(
                    url=url,
                    status_code=int(attempt.status_code or 0),
                    response_body=attempt.response_body or "",
                    attempts=tuple(attempts),
                    dead_lettered=False,
                )

        reason = _dead_letter_reason(attempts[-1])
        dead_letter = OutgoingWebhookDeadLetter(
            url=url,
            event_type=event_type,
            payload=payload,
            attempts=tuple(attempts),
            reason=reason,
        )
        if self.dead_letter_sink is not None:
            self.dead_letter_sink(dead_letter)
        return OutgoingWebhookResult(
            url=url,
            status_code=int(attempts[-1].status_code or 0),
            response_body=attempts[-1].response_body or attempts[-1].error_message or "",
            attempts=tuple(attempts),
            dead_lettered=True,
        )


def _default_opener(request: urllib.request.Request, timeout: int | None):
    return urllib.request.urlopen(request, timeout=timeout)


def _max_attempts(value: int) -> int:
    return max(1, int(value))


def _dead_letter_reason(attempt: OutgoingWebhookAttempt) -> str:
    if attempt.error_type:
        return f"{attempt.error_type}: {attempt.error_message or ''}".strip()
    return f"HTTP {attempt.status_code}"
