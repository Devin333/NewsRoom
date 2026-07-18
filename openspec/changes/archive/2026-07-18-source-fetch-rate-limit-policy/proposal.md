## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` requires source fetching to respect
per-domain rate limits. `SourceFetchPolicy` currently covers timeout, max bytes,
and user agent, but connector fetch paths do not enforce a rate limit before
network I/O.

## What Changes

- Add a shared in-memory per-domain rate limiter for source connectors.
- Extend `SourceFetchPolicy` with `rate_limit_per_domain_per_minute`.
- Return structured `rate_limited` `SourceError` results before calling the
  underlying fetcher.
- Apply the policy to RSS/Atom, arXiv, and GitHub connector fetch paths.

## Out Of Scope

- Distributed rate limiting across processes.
- Persistent rate-limit state.
- Robots.txt enforcement.
