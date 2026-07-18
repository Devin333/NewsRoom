# Source Shared Rate Limiter

## Why

The Source Pipeline target state requires domain-level source rate limiting. Individual connectors already enforce `rate_limit_per_domain_per_minute`, but default runtime assembly creates separate limiter instances per connector. That means RSS and HTML sources on the same domain can bypass a domain limit by going through different connector classes.

## What Changes

- Assemble default daily source connectors with one shared `DomainRateLimiter`.
- Assemble source-service preview connectors with one shared `DomainRateLimiter`.
- Keep injected connectors untouched so tests and operators can supply explicit limiter behavior.
- Add a workflow test proving cross-connector same-domain rate limiting.

## Non-Goals

- Do not add Redis/distributed rate limiting in this change.
- Do not commit OpenSpec files or generated artifacts.
