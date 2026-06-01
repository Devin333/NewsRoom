## Overview

The change is intentionally scoped to the frontend middleware gate. Route-level redirects that send anonymous users to `/login` are bypassed by default, but the existing session cookie flow, auth API routes, and backend enforcement remain in place.

## Middleware Behavior

- Add a temporary middleware flag derived from `NEWSROOM_ENABLE_FRONTEND_AUTH`.
- When the flag disables frontend auth, protected Portal and Admin paths return `NextResponse.next()`.
- `/login` redirects to a sanitized `next` value when present, otherwise to `/` for Portal or `/studio` for Admin.
- Cross-surface redirects still run before protected-route bypass so a Portal process does not become the Admin surface by accident.
- Setting `NEWSROOM_ENABLE_FRONTEND_AUTH=true` restores the previous login redirect path without removing this code.

## Safety

- `next` redirects accept only local paths beginning with `/`.
- External URLs, protocol-relative URLs, and login loops fall back to the surface home.
- This does not mint a fake session; user-specific writes can still fail if their backend routes require an authenticated session.

## Testing

- Middleware tests cover login bypass, anonymous Portal routes, Admin surface behavior, and cross-surface redirects.
