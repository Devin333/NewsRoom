from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.api.rate_limit import InMemoryRateLimiter


def test_in_memory_rate_limiter_blocks_until_window_expires() -> None:
    now = [100.0]
    limiter = InMemoryRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.check("client").allowed is True
    assert limiter.check("client").allowed is True

    blocked = limiter.check("client")
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 10

    now[0] = 111.0
    assert limiter.check("client").allowed is True


def test_api_rate_limit_returns_common_429_envelope() -> None:
    now = [100.0]
    client = TestClient(
        create_app(
            api_rate_limit_per_minute=1,
            rate_limit_clock=lambda: now[0],
        )
    )

    first = client.get("/api/v1/mcp/catalog", headers={"X-Request-ID": "rate-1"})
    second = client.get("/api/v1/mcp/catalog", headers={"X-Request-ID": "rate-2"})
    payload = second.json()

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert second.headers["x-request-id"] == "rate-2"
    assert payload["success"] is False
    assert payload["request_id"] == "rate-2"
    assert payload["error"]["code"] == "rate_limited"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["details"] == {
        "limit": 1,
        "remaining": 0,
        "window_seconds": 60,
    }


def test_api_health_does_not_consume_rate_limit() -> None:
    now = [100.0]
    client = TestClient(
        create_app(
            api_rate_limit_per_minute=1,
            rate_limit_clock=lambda: now[0],
        )
    )

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/mcp/catalog").status_code == 200
