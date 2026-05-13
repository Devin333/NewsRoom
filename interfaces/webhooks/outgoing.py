from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from interfaces.webhooks.signatures import build_signature_header


HttpOpener = Callable[[urllib.request.Request, int | None], Any]


@dataclass(frozen=True)
class OutgoingWebhookResult:
    url: str
    status_code: int
    response_body: str

    @property
    def success(self) -> bool:
        return 200 <= self.status_code < 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "success": self.success,
            "response_body": self.response_body,
        }


class OutgoingWebhookClient:
    def __init__(
        self,
        *,
        secret: str | None = None,
        timeout: int | None = 10,
        opener: HttpOpener | None = None,
    ) -> None:
        self.secret = secret
        self.timeout = timeout
        self._opener = opener or _default_opener

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
        request = urllib.request.Request(url, data=body, method="POST", headers=headers)
        with self._opener(request, self.timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return OutgoingWebhookResult(
                url=url,
                status_code=int(getattr(response, "status", 200)),
                response_body=response_body,
            )


def _default_opener(request: urllib.request.Request, timeout: int | None):
    return urllib.request.urlopen(request, timeout=timeout)
