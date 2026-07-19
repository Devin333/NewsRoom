## MODIFIED Requirements

### Requirement: Research results are stored as validated versioned JSON
The production Research run store SHALL persist each completed or terminal runtime result as atomic versioned JSON with run id, paper id, complete typed result projection, artifact references, and a checksum. New version-2 records SHALL additionally contain an identity-scope reference, explicit accepted or quarantine disposition, and publication-authority reference. Reads SHALL validate the schema, identity/scope evidence required by that schema version, checksum, canonical path containment, regular-file kind, and disposition evidence before reconstruction. Version-1 records SHALL remain byte-stable and readable; new writes SHALL use version 2 only after a dual-read deployment.

#### Scenario: Accepted analysis completes
- **WHEN** `ResearchSinglePaperRuntime` returns a succeeded result with passing quality and matching publication authority evidence
- **THEN** the service MUST durably commit the validated accepted run record before returning success
- **AND** no pickle, unsafe deserialization, or process-global map may be the production source of truth

#### Scenario: Terminal or non-passing analysis completes
- **WHEN** the runtime returns failed, halted, blocked, cancelled, approval-waiting, missing-quality, or non-passing output
- **THEN** the store MUST retain it with quarantine disposition for scoped by-run diagnostics
- **AND** it MUST NOT enter the accepted latest index or normal analysis/reader/ask path

#### Scenario: Runtime fails after durable run creation
- **WHEN** a worker, side-effect handler, artifact member, or terminal publication raises after the Harness run or authority decision is durable but before a Research result returns
- **THEN** the application boundary MUST reconstruct a validated terminal diagnostic from the durable Harness history and commit it with quarantine disposition before returning the typed service error
- **AND** partial candidate or legacy artifact state MUST NOT enter the accepted latest index or normal artifact reader

#### Scenario: Finalized manifest has no accepted run disposition
- **WHEN** a version-2 artifact manifest exists but its matching accepted run record is missing, quarantined, corrupt, or scope-mismatched
- **THEN** normal Research artifact resolution MUST reject the manifest until deterministic recovery reconciles the run disposition
- **AND** an explicit scoped diagnostic reader MAY inspect the retained manifest and candidate bytes

#### Scenario: Stored result is tampered
- **WHEN** the record bytes, checksum, run id, paper id, identity scope, disposition, publication authority, or acceptance evidence no longer match
- **THEN** the store MUST raise typed corruption before exposing analysis, reader, answer, trace, or artifact data

#### Scenario: Version-1 record is read by the dual reader
- **WHEN** a retained version-1 record has no explicit disposition
- **THEN** the reader MUST classify it from stored terminal status, quality, consistent artifact evidence, and an identity scope derived from validated actor metadata or an immutable single-scope storage-root binding without rewriting its bytes or trusting legacy manifest status
- **AND** absent, shared-root, conflicting, incomplete, malformed, or non-passing evidence MUST classify as quarantine

#### Scenario: Version-1 scope conflicts with the current reader
- **WHEN** a legacy record or manifest is opened under a tenant/identity scope that differs from its validated stored or storage-root-derived scope
- **THEN** the reader MUST fail closed or expose it only through an explicitly authorized quarantine diagnostic scope
- **AND** it MUST NOT expose analysis, reader, ask, trace, or artifact data across scopes

### Requirement: Research query behavior survives restart
The durable run store SHALL reconstruct the domain result required by accepted `get_analysis`, `get_reader`, `ask_paper`, and `get_trace` paths after a new service instance starts with the same storage root. Scoped by-run diagnostic reads SHALL retain quarantined terminal results, while both `get_latest_by_paper_id()` and the accepted-first `list_by_paper_id()` ordering consumed by `ResearchApplicationService._record_for_paper()` SHALL exclude quarantined records from normal selection.

#### Scenario: Service is reconstructed
- **WHEN** one process saves a successful accepted paper run and another service instance opens the same root
- **THEN** paper analysis, reader payload, trace, quality, and artifact references MUST match the committed accepted result

#### Scenario: Failed run follows an accepted paper run
- **WHEN** a quarantined run commits after an accepted run for the same paper
- **THEN** the store MUST return the earlier accepted run from the latest accepted query
- **AND** `get_analysis`, `get_reader`, and `ask_paper` MUST continue to resolve the earlier accepted run both in-process and after service reconstruction
- **AND** the later terminal result MUST remain available only through its scoped run/quarantine identity

#### Scenario: Process crashes after terminal completion but before run-record save
- **WHEN** terminal publication and `COMPLETE_RUN` are durable but the process exits before the matching accepted Research record is committed
- **THEN** bounded startup or lazy by-run/artifact reconciliation MUST derive accepted or quarantine disposition from the durable terminal outcome, quality/gate evidence, finalized manifest, publication authority, and identity scope
- **AND** reconciliation MUST be idempotent and MUST NOT call a worker or side-effect handler

#### Scenario: Only quarantined runs exist
- **WHEN** a paper has no accepted record after strict version-1/version-2 classification
- **THEN** the normal latest-by-paper query MUST return no record
- **AND** a scoped diagnostic reader MAY return the quarantined runs

#### Scenario: Mixed-version records are opened
- **WHEN** version-1 and version-2 records for one paper coexist after restart
- **THEN** index repair MUST classify both versions and select the latest accepted record deterministically
- **AND** it MUST NOT rewrite version-1 bytes or select a newer quarantined record

### Requirement: Harness artifact publication is run-scoped and integrity-protected
The production Harness artifact adapter SHALL bind one validated run and identity scope for the duration of a Research execution. A post-VERIFY step handler SHALL prepare immutable hidden artifact candidates and a durable prepared outcome without canonical visibility. Before `COMPLETE_RUN`, one controller-terminal handler SHALL add trace/transcript candidates, verify the complete atomic group, and commit one finalized manifest/index visibility update bound to the publication authority. Normal artifact resolution SHALL additionally require a matching accepted run disposition.

#### Scenario: Research prepares analysis artifacts
- **WHEN** the Research artifact step passes VERIFY and its preparation handler processes analysis, reader, quality, RAG, context, or other main artifacts
- **THEN** each candidate MUST remain under the bound run and identity scope with checksum-bearing hidden refs
- **AND** no canonical manifest/index or normal artifact reader may expose the prepared group

#### Scenario: Research publishes the terminal artifact group
- **WHEN** all step outcomes are durable and the controller-terminal handler prepares trace/transcript and verifies every member of the same atomic group
- **THEN** it MUST commit one finalized manifest/index visibility update containing all authorized main and terminal artifact paths, checksums, metadata, and authority refs
- **AND** the public refs MUST remain invisible to normal Research readers until the matching accepted run disposition is committed

#### Scenario: Concurrent runs publish the same artifact type
- **WHEN** two Research requests prepare or terminally publish `research-analysis` concurrently
- **THEN** each candidate, manifest, outcome, and disposition MUST remain under its own run and identity scope
- **AND** neither adapter may read shared mutable run-id or subject-scope state

#### Scenario: Artifact reference is read
- **WHEN** the adapter resolves a persisted Harness artifact reference through a normal Research reader
- **THEN** it MUST verify canonical path, checksum, finalized manifest, publication authority, identity scope, and matching accepted run disposition before decoding JSON
- **AND** prepared, quarantined, missing-disposition, or `legacy_quarantined` refs MUST require an explicit scoped diagnostic reader

#### Scenario: Terminal artifact group fails
- **WHEN** preparing or validating any main, trace, or transcript member fails before the terminal visibility commit
- **THEN** the canonical manifest and published artifact index MUST have zero new entries from the atomic group
- **AND** hidden candidates MAY be quarantined or removed by owned cleanup without becoming normal artifact refs

### Requirement: Research persistence writes are atomic and recoverable
Run records, accepted latest-by-paper indexes, quarantine indexes, and Research artifacts SHALL use temp-write, flush, atomic replace, and owned-temp cleanup semantics appropriate to the local filesystem. A failed update SHALL leave the last committed accepted record readable. Accepted indexes MUST reference accepted committed records only.

#### Scenario: Record replace fails
- **WHEN** an injected filesystem failure occurs before atomic replacement
- **THEN** the prior committed run/index MUST remain readable
- **AND** no partial record may be treated as accepted or current

#### Scenario: Concurrent writers update one paper index
- **WHEN** accepted and quarantined runs for the same paper commit concurrently
- **THEN** the accepted index MUST remain valid and reference only the deterministic latest accepted record
- **AND** quarantine diagnostics MUST remain addressable without replacing accepted latest

#### Scenario: Old index is repaired by a version-2 reader
- **WHEN** a retained version-1 latest index points to a record now classified as quarantine or omits a newer accepted version-2 record
- **THEN** the dual reader MUST rebuild the accepted index from validated records under the existing lock/atomic-replace boundary
- **AND** rollback MUST target only a build that can still read both schema versions
