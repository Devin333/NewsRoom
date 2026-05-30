from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REDACTED_VALUE = "[redacted]"
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SECRET_RE = re.compile(r"(?i)sk-[A-Za-z0-9_-]{8,}")
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "signature",
    "database_url",
    "dsn",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RedactionReport:
    run_id: str
    artifact_id: str
    redacted_fields: list[str] = field(default_factory=list)
    redaction_rules_applied: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "redacted_fields": list(self.redacted_fields),
            "redaction_rules_applied": list(self.redaction_rules_applied),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RedactionReport:
        return cls(
            run_id=str(payload["run_id"]),
            artifact_id=str(payload["artifact_id"]),
            redacted_fields=[str(item) for item in payload.get("redacted_fields", [])],
            redaction_rules_applied=[
                str(item) for item in payload.get("redaction_rules_applied", [])
            ],
            created_at=_parse_datetime(str(payload["created_at"])),
        )


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    report: RedactionReport

    @property
    def redacted(self) -> bool:
        return bool(self.report.redacted_fields)


class StorageRedactor:
    def redact(self, value: Any, *, run_id: str, artifact_id: str) -> RedactionResult:
        fields: set[str] = set()
        rules: set[str] = set()
        redacted_value = self._redact(value, path="$", fields=fields, rules=rules)
        return RedactionResult(
            value=redacted_value,
            report=RedactionReport(
                run_id=run_id,
                artifact_id=artifact_id,
                redacted_fields=sorted(fields),
                redaction_rules_applied=sorted(rules),
            ),
        )

    def _redact(self, value: Any, *, path: str, fields: set[str], rules: set[str]) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if _is_sensitive_key(key):
                    redacted[str(key)] = REDACTED_VALUE
                    fields.add(child_path)
                    rules.add("sensitive_key")
                else:
                    redacted[str(key)] = self._redact(
                        item,
                        path=child_path,
                        fields=fields,
                        rules=rules,
                    )
            return redacted
        if isinstance(value, list):
            return [
                self._redact(item, path=f"{path}[{index}]", fields=fields, rules=rules)
                for index, item in enumerate(value)
            ]
        if isinstance(value, str):
            return _redact_string(value, path=path, fields=fields, rules=rules)
        return value


def _redact_string(value: str, *, path: str, fields: set[str], rules: set[str]) -> str:
    redacted = value
    redacted, bearer_count = _BEARER_RE.subn(r"\1" + REDACTED_VALUE, redacted)
    if bearer_count:
        fields.add(path)
        rules.add("bearer_token")
    redacted, secret_count = _SECRET_RE.subn(REDACTED_VALUE, redacted)
    if secret_count:
        fields.add(path)
        rules.add("secret_like_string")
    url_redacted = _redact_url(redacted)
    if url_redacted != redacted:
        fields.add(path)
        rules.add("sensitive_url_query")
    return url_redacted


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc or not parsed.query:
        return value
    query = []
    changed = False
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_key(key):
            query.append((key, REDACTED_VALUE))
            changed = True
        else:
            query.append((key, item))
    if not changed:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).replace("-", "_").casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
