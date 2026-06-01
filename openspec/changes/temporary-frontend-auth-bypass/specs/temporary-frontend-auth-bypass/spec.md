## ADDED Requirements

### Requirement: Frontend auth is temporarily bypassed
The frontend middleware SHALL allow anonymous access to protected frontend pages while temporary auth bypass is active.

#### Scenario: Anonymous user opens a Portal route
- **WHEN** a request without a session cookie opens `/reports`
- **THEN** middleware SHALL NOT redirect to `/login`
- **AND** the page request SHALL continue.

#### Scenario: Anonymous user opens Studio on the Admin surface
- **WHEN** the frontend surface is `admin` and a request without a session cookie opens `/studio/runs`
- **THEN** middleware SHALL NOT redirect to `/login`
- **AND** the page request SHALL continue.

### Requirement: Login page does not block temporary access
The frontend middleware SHALL redirect login-page requests away from the login form while temporary auth bypass is active.

#### Scenario: Login request has a local next path
- **WHEN** a user opens `/login?next=%2Freports`
- **THEN** middleware SHALL redirect to `/reports`.

#### Scenario: Login request has an unsafe next path
- **WHEN** a user opens `/login?next=https%3A%2F%2Fexample.com`
- **THEN** middleware SHALL redirect to the local surface home.

### Requirement: Temporary bypass remains reversible
The frontend middleware SHALL keep the existing route auth gate restorable by environment configuration.

#### Scenario: Auth is explicitly re-enabled
- **WHEN** `NEWSROOM_ENABLE_FRONTEND_AUTH=true` is configured before the frontend process starts
- **THEN** middleware SHALL use the session-cookie login gate for protected routes.
