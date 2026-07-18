## Design

`SourceHealthChecker` accepts an optional `DomainRateLimiter`. Each source probe computes the effective fetch policy, reserves the source URL against the limiter, and skips with a non-health-affecting `rate_limited` source error when the limiter blocks.

The checker reports rate-limit skips as skipped entries, not failures, because rate limiting is an execution policy decision rather than evidence that the source is down.
