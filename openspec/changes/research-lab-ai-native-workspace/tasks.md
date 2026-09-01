# Tasks

## 1. Preconditions and design system

- [x] 1.1 Confirm projects-lab-workflow-contract is implemented, strictly validated, and available in the local API/client fixtures. Depends on: prerequisite change.
- [x] 1.2 Capture the existing Lab route, session detail, Projects state components, API client, i18n pattern, and baseline visual screenshots. Depends on: 1.1.
- [x] 1.3 Define Lab-scoped semantic tokens only where existing globals cannot express the state; add light/dark mappings and document ownership. Depends on: 1.2.
- [x] 1.4 Add or confirm i18n keys for touched Lab labels, errors, status, empty state, source status, tabs, and save terminology. Depends on: 1.2.

## 2. Data and presentation foundation

- [x] 2.1 Add a single frontend workflow presentation adapter for known/unknown stage, next_action, readiness, and unanswered question data. Depends on: 1.1.
- [x] 2.2 Ensure the adapter fails closed for unknown server values and does not duplicate backend readiness rules. Depends on: 2.1.
- [x] 2.3 Extract only reusable Lab view primitives from projects-product-page.tsx; preserve route-level ownership in Projects feature code. Depends on: 2.1.
- [x] 2.4 Build LabWorkspaceSkeleton aligned to the final composer, workflow, conversation, and context geometry. Depends on: 2.3.

## 3. Main /projects/lab workspace

- [x] 3.1 Implement LabBriefComposer with visible labels, real source/case summary, trim validation, pending feedback, local error association, and retained failed draft. Depends on: 2.3, 1.4.
- [x] 3.2 Implement LabWorkflowStatus with stage text, icon, count, next-action copy, aria-live, and contract-driven action availability. Depends on: 2.2, 1.4.
- [x] 3.3 Implement LabClarificationList with deterministic question order, completed/active visual states, answer mutation feedback, retry, and success focus restoration. Depends on: 2.2, 1.4.
- [x] 3.4 Wire generate action only to server-provided readiness; render 409 as a navigation back to unanswered clarification, without fake streaming. Depends on: 3.2, 3.3.
- [x] 3.5 Retain and correctly place ProjectDegradedNotice, ProjectSourceLine, ProjectEmptyState, and ProjectErrorState. Depends on: 3.1.

## 4. Context, graph, and solution views

- [x] 4.1 Extract or refine LabGraph with an accessible title, node/edge summary, text relationship list, and keyboard node controls. Depends on: 2.3.
- [x] 4.2 Connect explainProjectLabNode with local pending/error isolation and screen-reader feedback. Depends on: 4.1.
- [x] 4.3 Implement LabSolutionPanel Summary, Structured, and Evidence Tabs using existing Radix Tabs. Depends on: 2.3, 1.4.
- [x] 4.4 Add bounded JSON panel, icon+tooltip copy control, success/failure feedback, and safe unavailable-data rendering. Depends on: 4.3.
- [x] 4.5 Verify that cases, source, data policy, MVP, non-goals, and review notes are only rendered from API payloads. Depends on: 4.3.

## 5. Session detail and save semantics

- [x] 5.1 Refactor /projects/lab/[sessionId] to reuse Lab status/context/solution primitives while preserving its read-first role. Depends on: 2.3, 4.3.
- [x] 5.2 Make save availability and saved/adopted/archived wording contract-driven; do not expose approval/publication claims. Depends on: 2.2, 1.4.
- [x] 5.3 Add pending, success, error, retry, focus, and aria-live behavior for save. Depends on: 5.2.

## 6. Responsive, accessibility, and visual polish

- [x] 6.1 Implement desktop 12-column, tablet two-column, and mobile single-column layout without page-level horizontal overflow. Depends on: 3.5, 4.4, 5.3.
- [x] 6.2 Implement mobile context disclosure/Sheet if necessary while retaining an equivalent keyboard path. Depends on: 6.1.
- [x] 6.3 Audit all labels, error associations, heading hierarchy, contrast, focus rings, Tabs keyboard behavior, touch target dimensions, and motion preferences. Depends on: 6.1.
- [x] 6.4 Check Chinese and English long labels/answers at 320px and desktop widths for wrapping and overlap. Depends on: 6.3.

## 7. Tests

- [x] 7.1 Update existing Projects Lab component tests for the canonical workflow contract and answer-all-before-generate flow. Depends on: 3.4.
- [x] 7.2 Add component tests for pending states, retained draft on error, 409 readiness, unknown state fail-closed, copy feedback, source/degraded/empty states, and save terminology. Depends on: 4.4, 5.3.
- [x] 7.3 Add graph text-alternative and node explanation success/failure tests. Depends on: 4.2.
- [x] 7.4 Add keyboard-only and accessibility assertions, including live announcements and focus restoration. Depends on: 6.3.
- [x] 7.5 Add Playwright visual/responsive checks at 320, 375, 414, 768, 1024, 1280, and 1440px, including body overflow assertion. Depends on: 6.4.

## 8. Verification, rollout, and delivery

- [x] 8.1 Run targeted frontend unit tests and E2E visual tests. Depends on: 7.1-7.5.
- [x] 8.2 Run npm run lint, npm run typecheck, npm run test, and the relevant frontend build check. Depends on: 8.1.
- [x] 8.3 Run python -m scripts.dev compile and python -m scripts.dev smoke; resolve root causes if either fails. Depends on: 8.2.
- [x] 8.4 Run openspec validate projects-lab-workflow-contract --strict and openspec validate research-lab-ai-native-workspace --strict. Depends on: 8.3.
- [x] 8.5 Validate four release data modes: ready, empty, degraded, and 409 workflow gate. Depends on: 8.4.
- [x] 8.6 Commit the two completed OpenSpec changes and implementation files with path-scoped staging; do not stage unrelated worktree changes. Depends on: 8.5.
