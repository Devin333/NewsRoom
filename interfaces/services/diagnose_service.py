from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


CheckStatus = Literal["ok", "warning", "error", "skipped"]
DiagnoseStatus = Literal["ok", "warning", "error"]


@dataclass(frozen=True)
class DiagnoseCheck:
    check_id: str
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class DiagnoseResult:
    status: DiagnoseStatus
    checks: list[DiagnoseCheck]
    summary: str

    @classmethod
    def from_checks(cls, checks: list[DiagnoseCheck]) -> "DiagnoseResult":
        if any(check.status == "error" for check in checks):
            status: DiagnoseStatus = "error"
        elif any(check.status == "warning" for check in checks):
            status = "warning"
        else:
            status = "ok"
        return cls(
            status=status,
            checks=checks,
            summary=f"{sum(1 for check in checks if check.status == 'ok')} ok, "
            f"{sum(1 for check in checks if check.status == 'warning')} warning, "
            f"{sum(1 for check in checks if check.status == 'error')} error, "
            f"{sum(1 for check in checks if check.status == 'skipped')} skipped",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "checks": [check.to_dict() for check in self.checks],
        }


class DiagnosticApplicationService:
    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        checks: list[Callable[[], DiagnoseCheck]] | None = None,
    ) -> None:
        self.env = env if env is not None else os.environ
        self.checks = checks or [
            self._check_dashscope_key,
            self._check_redis,
            self._check_qdrant,
            self._check_postgres,
        ]

    def run(self) -> DiagnoseResult:
        checks = []
        for check in self.checks:
            try:
                checks.append(check())
            except Exception as exc:
                checks.append(
                    DiagnoseCheck(
                        check_id="diagnostic_exception",
                        name="Diagnostic Check",
                        status="error",
                        message=f"{type(exc).__name__}: {exc}",
                        remediation="Inspect the failing diagnostic check and local service configuration.",
                    )
                )
        return DiagnoseResult.from_checks(checks)

    def _check_dashscope_key(self) -> DiagnoseCheck:
        if self.env.get("DASHSCOPE_API_KEY"):
            return DiagnoseCheck(
                check_id="dashscope_api_key",
                name="DashScope API key",
                status="ok",
                message="DashScope API key is configured.",
                details={"provider": "dashscope", "configured": True},
            )
        return DiagnoseCheck(
            check_id="dashscope_api_key",
            name="DashScope API key",
            status="warning",
            message="DashScope API key is not configured.",
            details={"provider": "dashscope", "configured": False},
            remediation="Set DASHSCOPE_API_KEY before using the live LLM profile.",
        )

    def _check_redis(self) -> DiagnoseCheck:
        import redis

        redis_url = self.env.get("NEWS_REDIS_URL", "redis://127.0.0.1:6379/0")
        client = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return DiagnoseCheck(
            check_id="redis",
            name="Redis",
            status="ok",
            message="Redis ping succeeded.",
            details={"configured": bool(self.env.get("NEWS_REDIS_URL"))},
        )

    def _check_qdrant(self) -> DiagnoseCheck:
        url = self.env.get("NEWS_QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
        with urllib.request.urlopen(f"{url}/healthz", timeout=2) as response:
            content = response.read().decode("utf-8", errors="replace")
        return DiagnoseCheck(
            check_id="qdrant",
            name="Qdrant",
            status="ok",
            message="Qdrant health check succeeded.",
            details={"configured": bool(self.env.get("NEWS_QDRANT_URL")), "response": content[:80]},
        )

    def _check_postgres(self) -> DiagnoseCheck:
        dsn = self.env.get("NEWS_DATABASE_DSN")
        if not dsn:
            return DiagnoseCheck(
                check_id="postgres",
                name="PostgreSQL",
                status="skipped",
                message="NEWS_DATABASE_DSN is not configured; local JSON fallback is active.",
                details={"configured": False},
            )

        import psycopg

        with psycopg.connect(dsn, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return DiagnoseCheck(
            check_id="postgres",
            name="PostgreSQL",
            status="ok",
            message="PostgreSQL connection check succeeded.",
            details={"configured": True},
        )
