## Why

Source collection currently has three URL canonicalizers, three independent per-domain limiters, two retry classifiers, two nearly identical error taxonomies, field-losing DTO mappers, and eight connector-local error constructors. The same source can therefore receive a different identity, quota, retry outcome, or lineage record depending on whether it entered through a connector, tool, health probe, or interface service.

## What Changes

- Establish one business-owned Source URL identity contract and make SourceRef, signal processing, HTML extraction, and infrastructure adapters consume it through explicit compatibility boundaries.
- **BREAKING**: new Source URL identities use one golden canonical form across all entry points. Existing persisted URLs and artifact refs remain readable and are never rewritten; migration readers retain aliases for previously emitted forms.
- Establish one infrastructure-owned Source fetch policy for rate limiting and retry classification, with one explicitly injected reservation ledger shared by connector, source-tool, and health-probe composition.
- Remove business and health-check copies of limiter/retry algorithms; business modules depend on Source policy ports and deterministic decision DTOs rather than concrete infrastructure.
- Establish one business-owned error taxonomy with explicit connector extension inputs, then replace connector-local classifier copies and `_source_error()` constructors with shared adapters.
- Establish one explicit infrastructure-to-business Source mapper and preserve every `SourceError` field, including `request_ref`, `response_ref`, `occurred_at`, timezone, metadata, and retry semantics.
- Preserve public Source DTO shapes, artifact types, event fields, connector variants, offline behavior, and existing source configuration formats.
- Add golden URL, cross-entry quota, retry matrix, taxonomy parity, mapper round-trip, and connector error-construction contract tests before deleting compatibility exports.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `source-canonical-url-default-port`: make default-port handling part of the single Source URL identity contract used by every entry point.
- `source-canonical-url-relative-resolution`: freeze relative resolution, path, fragment, tracking-query, duplicate-query, and invalid-input behavior in one golden contract.
- `source-html-canonical-url-normalize`: require HTML canonical URL projection to delegate to the same business-owned identity contract.
- `source-fetch-rate-limit-policy`: make one deterministic limiter decision and domain key authoritative across connector, tool, and health execution.
- `source-fetch-retry-policy`: make one exception/status/budget matrix authoritative for every Source fetch path.
- `source-pipeline`: require default composition to share one reservation ledger across connectors, source tools, health probes, and Research arXiv package/PDF adapters before network access.
- `source-error-taxonomy`: make one classifier and shared connector error construction path authoritative while preserving explicit connector extensions.
- `source-error-top-level-policy-fields`: require lossless business/infrastructure mapping and stable retry defaults.
- `source-error-artifact-refs`: require request/response refs and occurrence time to survive all Source mapper round trips.

## Impact

- Business ownership: `business/foundation/primitives/source_ref.py`, `business/layers/signal/source_processing`, `source_tool_runtime.py`, and `source_health/checker.py`.
- Source-identity consumers: Research paper, repository, and paper-card URL fields that currently import the foundation canonicalizer; their persisted values require explicit compatibility fixtures rather than silent behavior changes.
- Infrastructure ownership: `infrastructure/external/sources/fetch_policy.py`, `url_utils.py`, error taxonomy adapters, connector error construction, and connector composition.
- Interface composition: `interfaces/services/source_service.py`, `source_tool_runtime.py`, `source_health_probe.py`, and a Source-specific composition boundary. Existing dirty Tool/Research composition files are excluded until their active owners release them.
- Tests: Source business/infra/interface suites gain shared golden corpora and cross-entry contract matrices; architecture tests gain only precise Source contract dependencies, not blanket infrastructure-to-business access.
- No new third-party dependency, external service, database migration, or public transport schema is introduced.
