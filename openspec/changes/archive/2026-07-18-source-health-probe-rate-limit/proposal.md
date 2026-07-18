## Why

Source health checks perform external probe fetches. They already use fetch policy for timeout, redirects, max bytes, retry, and robots, but they do not share the domain rate limiter used by source collection and preview paths.

## What Changes

- Add shared `DomainRateLimiter` support to `SourceHealthChecker`.
- Pass the application service rate limiter into health checks.
- Skip rate-limited probes before network access and emit structured skip diagnostics.

## Impact

- Affects `sources/health/checker.py` and `interfaces/services/source_service.py`.
- Adds focused health checker tests.
