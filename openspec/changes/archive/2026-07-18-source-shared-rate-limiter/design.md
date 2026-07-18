# Design

## Runtime Assembly

`DailyIntelligenceRunner` creates one `DomainRateLimiter` and passes it to all default connectors it owns. `MediumConnector` receives a `FeedConnector` built with the same limiter.

`SourceApplicationService` applies the same pattern for default preview connectors.

## Compatibility

Injected connector instances are not modified. This keeps existing tests and custom connectors deterministic while ensuring production default assembly enforces source policy consistently.

## Scope

The limiter remains in-process. Distributed worker-level throttling can be added later under Worker/Scheduler scope.
