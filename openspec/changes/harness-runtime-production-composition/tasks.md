## 1. Baseline, scope, and inventory

- [x] 1.1 Freeze a dated baseline with commit, related OpenSpec status, supported entrypoints, fingerprints, environment capabilities, and honest contract-pass/blocked classifications.
- [x] 1.2 Maintain a versioned caller inventory for production `ToolExecutor`, execution environment, direct process, and selected Research parser construction sites; classify each as migrated, trusted exemption, or blocked with owner, rationale, proof, review date, and automated check.
- [x] 1.3 Define the `trusted_in_process`, `sandboxed`, and `external_process` profile/provider catalog, unsupported Docker capabilities, and stable typed denial taxonomy.
- [x] 1.4 Reconcile proposal, design, specs, and tasks with `prd.md`; hand child supervision, durable event/operator reconnect, side-effect recovery, outbound MCP, and external release qualification to their named follow-up changes without claiming them complete here.

## 2. Production execution composition (P0)

- [x] 2.1 Implement a lightweight process-local `RuntimeExecutionComposition` factory with immutable versioned identity, deterministic composition/policy/provider fingerprints, explicit profile registry, execution registry, and `ToolExecutor` factory.
- [x] 2.2 Wire API, worker, CLI, Harness, and Research composition roots to resolve the same execution configuration/policy identity while owning separate process-local objects; reject configured fingerprint drift.
- [x] 2.3 Inject the composition execution registry/profile resolver into `AgentRunner`, Harness tool activity, batch executor, and external subagent tool execution; keep external activity fail closed by default.
- [x] 2.4 Make required providers role-scoped: Research parser requires `docker`, while catalogued-but-unselected providers remain admission-gated; expose typed readiness/admission diagnostics for unavailable provider, unsupported capability, missing/invalid profile, Graph identity mismatch, invalid execution spec, and composition drift.
- [x] 2.5 Remove legacy widened control-plane port requirements from execution composition and Research wiring; child, event, projection, operator, approval, and business side-effect owners must remain outside this factory.

## 3. Research parser vertical slice (P1)

- [x] 3.1 Route the selected Research Marker/MinerU PDF parser through `ResearchParserExecutionAdapter` and inject the process composition registry/profile.
- [x] 3.2 Map exact Graph/activity identity, argv, canonical cwd, read/write/cache/config roots, allowlisted environment, network deny, timeout, and cancellation to `ExecutionRequest`.
- [x] 3.3 Remove host-process fallback from selected parser paths; keep the unselected PDF compiler and outbound MCP/sidecar paths explicit in caller inventory/handoff.
- [x] 3.4 Verify receipt mapping, provider unavailable, path/environment policy, capability denial, timeout, and termination-unconfirmed/indeterminate outcomes with contract and adversarial tests.

## 4. Qualification and evidence (P2)

- [x] 4.1 Enforce the production caller inventory with source validation that fails for unapproved Harness-managed process creation, raw external execution, or uncomposed external `ToolExecutor` construction.
- [x] 4.2 Verify execution wiring does not transfer Graph routing, quality gate, approval, memory write, artifact publication, runtime-event authority, or business side-effect authority to LLM/worker/parser code.
- [x] 4.3 Record the selected parser/Docker capability matrix and fingerprints; when Docker is unavailable, record typed blocked/skip evidence and do not claim real sandbox qualification.
- [ ] 4.4 Complete an independent review of AC-01 through AC-08, source inventory, authority boundaries, evidence labels, and follow-up handoffs.
- [ ] 4.5 Run focused tests, compile, mandatory `python -m scripts.dev smoke`, target and repository-wide strict OpenSpec validation, and record exact commands/results.

## 5. Documentation and commit

- [ ] 5.1 Update `prd.md` baseline/status and `evidence.md` to describe final execution-only ownership, supported profiles, fingerprints, known blockers, and implementation commits.
- [ ] 5.2 Scan repository documentation for stale claims that this change owns child lifecycle, durable event/operator reconnect, side-effect recovery, optional Research provider fallback, or host-process parser execution.
- [ ] 5.3 Ensure `evidence.md` distinguishes local contract evidence, environment-blocked Docker qualification, follow-up change ownership, and external evidence that is explicitly outside this change.
- [ ] 5.4 Commit code and OpenSpec updates with path-scoped staging after all required gates pass.
