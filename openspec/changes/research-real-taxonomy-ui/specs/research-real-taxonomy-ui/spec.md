## ADDED Requirements

### Requirement: Real-only Research taxonomy
The Research runtime SHALL derive public task and method taxonomy only from published papers that carry real `taskRefs`, `methodRefs`, `benchmarks`, or `implementations`, and MUST NOT create user-visible taxonomy relationships from title, abstract, tag, or keyword heuristics.

#### Scenario: Cached paper has no taxonomy refs
- **WHEN** backend paper APIs are unavailable and a cached published paper has no `taskRefs` or `methodRefs`
- **THEN** the paper remains available in the paper stream
- **AND** the paper does not contribute to any task or method count

#### Scenario: Cached paper has real taxonomy refs
- **WHEN** backend paper APIs are unavailable and a cached published paper has real `taskRefs` and `methodRefs`
- **THEN** `/api/papers/tasks` and `/api/papers/methods` return taxonomy items derived from those refs
- **AND** counts, related refs, latest papers, and implementation totals are based on the matching published papers

### Requirement: Static catalog cannot fabricate taxonomy
The Research runtime SHALL use the local static paper catalog only to enrich display metadata for taxonomy slugs that already exist in real paper refs, and MUST NOT return catalog-only or zero-paper taxonomy cards as public items.

#### Scenario: Static taxonomy item has no real papers
- **WHEN** a task or method exists in the static catalog but no published paper carries its slug
- **THEN** list routes and pages omit that taxonomy item
- **AND** the corresponding task or method detail route returns not found

### Requirement: Research read routes are public
The frontend SHALL allow anonymous users to read `/papers`, paper detail routes, `/papers/{slug}/read`, `/papers/tasks`, `/papers/tasks/{slug}`, `/papers/methods`, and `/papers/methods/{slug}`.

#### Scenario: Anonymous user opens Research
- **WHEN** a request without a session cookie opens a Research read route
- **THEN** middleware allows the request to render the route instead of redirecting to `/login`

#### Scenario: Anonymous user uses personal paper state
- **WHEN** an anonymous request uses a user-specific paper state, note, material, selection, or reader event API
- **THEN** the request remains subject to authentication or backend session requirements

### Requirement: Truthful Research UI states
Research task and method pages SHALL hide zero-paper taxonomy cards, show localized notices and empty states, and avoid styling that makes the production research UI look like a mock surface.

#### Scenario: No verified taxonomy exists
- **WHEN** the paper stream has real papers but none have task or method refs
- **THEN** task and method pages show a localized empty state
- **AND** no static fallback list is displayed

#### Scenario: Chinese fallback notice renders
- **WHEN** a degraded Research result is shown in Chinese locale
- **THEN** fallback notices are readable Chinese strings without mojibake or hard-coded English

#### Scenario: Research typography renders
- **WHEN** the Research paper stream, microbar, sidebars, period tabs, or sort tabs render
- **THEN** those components use the normal product typography rather than Comic Sans-specific inline styles
