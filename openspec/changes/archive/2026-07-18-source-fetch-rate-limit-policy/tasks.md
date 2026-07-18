## 1. OpenSpec Setup

- [x] 1.1 Create `source-fetch-rate-limit-policy` OpenSpec change.
- [x] 1.2 Define proposal, design, tasks, and spec delta.
- [x] 1.3 Keep OpenSpec files, local state, generated outputs, and secrets out of commits.

## 2. Source Fetch Rate Limit

- [x] 2.1 Add shared source fetch policy and per-domain rate limiter.
- [x] 2.2 Apply rate-limit checks before RSS/Atom fetches.
- [x] 2.3 Apply rate-limit checks before arXiv and GitHub fetches.
- [x] 2.4 Return structured non-health-affecting `rate_limited` source errors.

## 3. Validation

- [x] 3.1 Add focused connector rate-limit tests.
- [x] 3.2 Run OpenSpec validation and focused tests.
- [x] 3.3 Run full tests, diff checks, secret scan, and commit.
