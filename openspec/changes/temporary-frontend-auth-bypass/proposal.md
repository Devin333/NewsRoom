## Why

Local frontend exploration is currently blocked by the login screen for Portal routes such as `/reports`. The product needs a temporary no-login mode so Research, reports, Studio inspection, and other frontend pages can be opened directly while auth work is not the focus.

## What Changes

- Temporarily bypass frontend route authentication by default.
- Redirect `/login` to a safe `next` path or the surface home so users do not land on the login form during the bypass.
- Keep cross-surface Portal/Admin routing behavior intact.
- Keep backend auth APIs and user-specific API behavior available for later restoration; setting `NEWSROOM_ENABLE_FRONTEND_AUTH=true` restores the old frontend route gate.

## Capabilities

### New Capabilities
- `temporary-frontend-auth-bypass`: Temporary frontend route auth bypass and login-page redirect behavior.

### Modified Capabilities

## Impact

- Frontend middleware and middleware tests.
- No backend auth service, session cookie, or protected API route contract changes.
