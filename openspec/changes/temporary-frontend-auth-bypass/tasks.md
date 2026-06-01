## 1. Spec

- [x] 1.1 Create temporary frontend auth bypass OpenSpec artifacts.
- [x] 1.2 Validate `temporary-frontend-auth-bypass` with strict OpenSpec validation.

## 2. Middleware

- [x] 2.1 Add temporary frontend auth bypass controlled by `NEWSROOM_ENABLE_FRONTEND_AUTH`.
- [x] 2.2 Redirect `/login` to safe local destinations while bypass is active.
- [x] 2.3 Preserve cross-surface redirects and backend auth API behavior.

## 3. Verification

- [x] 3.1 Update middleware tests for temporary bypass behavior.
- [x] 3.2 Run middleware tests and frontend typecheck.
- [x] 3.3 Commit the completed change.
