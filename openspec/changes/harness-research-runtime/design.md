## Context

NewsRoom 当前已经有可复用的底层运行时资产：`framework/llm`、`framework/tool`、`framework/memory`、`framework/skills`、`framework/artifacts`、`framework/events`、`framework/workers`、`framework/scoring`、`framework/governance`、`framework/shared` 和 `framework/workflow`。这些能力服务过 daily intelligence、board runtime、paper reader、tool runtime、memory、skill runner 等路径，但流程决策被分散在 workflow runner、agent loop、board workflow、paper reader service、worker handler 和接口层组装逻辑中。

本 change 先建立 Harness Control Plane，再重建 Research。阶段 0 不实现新 runtime，只固定边界、OpenSpec 契约、执行顺序和 keep/adapt/delete 清单。后续阶段必须保留有价值的底层资产，同时删除不再服务 Harness + Research 的旧业务、旧接口、旧测试和兼容路径。

关键约束：

- `framework/` 不得依赖 `business`、`interfaces` 或具体 `infrastructure` adapter。
- `business/research` 不得依赖 `business/boards/paper_radar`、`interfaces` 或 `infrastructure`。
- Harness 是唯一 workflow decision maker；LLM 和 subagent 只能做 worker。
- UI 与前端迁移不在本 change 范围内。

## Goals / Non-Goals

**Goals:**

- 新建 `harness-research-runtime` OpenSpec change，覆盖 Harness、Research、skill evolution 和 legacy cleanup。
- 定义 `framework/harness` 的职责：状态推进、路由、重试、质量门、审批、记忆写入、artifact 发布、trace、checkpoint 和 replay。
- 定义每个 Harness step 的 `PLAN -> EXECUTE -> VERIFY` 有界状态机，以及失败后的 `replan`、`retry`、`route_to_repair`、`wait_for_approval`、`halted`、`failed` 结果。
- 定义七层 port 边界，让 Harness 通过端口消费 LLM、tool、memory、skill、artifact、event、worker、governance、context、subagent 和 RAG 能力。
- 定义 `business/research` 的领域边界和后端接口边界，不复用旧 paper API 或旧 paper_radar payload。
- 定义 skill evolution 的 Harness-controlled 生命周期，让 LLM 只能产出 candidate 或 patch。
- 生成审计清单，为阶段 8 和阶段 9 的删除工作提供依据。

**Non-Goals:**

- 阶段 0 不实现 `framework/harness`、`business/research`、Research service 或 API router。
- 不迁移 UI，不改前端，不保留旧 paper UI 兼容 adapter。
- 不为了通过测试删除旧测试；只有旧行为在阶段 8/9 明确废弃时才删除。
- 不把旧 `framework/agent/harness` 当成新 Harness Control Plane 直接复用。
- 不让 LLM、AgentLoop、subagent、reader repair 或接口层决定 workflow routing、quality verdict、memory write、tool authorization 或 publication。

## Decisions

### 1. Harness becomes a top-level framework package

`framework/harness` SHALL be a top-level framework package rather than a child of `framework/agent`.

Rationale: Harness controls workflow state, gates, ports, memory writes, skill promotion, artifact publication and replay across agents, tools, RAG and deterministic workers. Putting it under `framework/agent` would make agent execution appear to own the flow and would preserve the old sidecar shape.

Alternatives considered:

- Keep `framework/agent/harness`: rejected because it models harness as agent-adjacent test/evaluation support, not the production control plane.
- Extend `framework/workflow` only: rejected because the new Harness must also own subagent isolation, context engineering, bounded RAG and skill evolution orchestration.

### 2. Existing framework assets are ports and workers, not decision makers

Reusable framework modules SHALL be kept or adapted behind Harness ports. `framework/workflow`, `framework/agent/loop`, `framework/agent/runtime`, `framework/agent/session` and generic subagent machinery can be adapted as worker/runtime utilities, but they MUST NOT control Harness routing or final quality decisions.

Rationale: the project already has real LLM, tool, memory, skill, event, worker, artifact and governance implementations with tests. Rewriting them would create churn; letting them keep flow authority would preserve the problem.

Alternatives considered:

- Rewrite all framework assets from scratch: rejected because many assets are domain-neutral and already covered by tests.
- Keep current workflow/agent routing as primary: rejected because PRD requires Harness to be the only flow decision maker.

### 3. VERIFY gates are deterministic pure functions

Harness VERIFY SHALL use deterministic gates for schema, budget, score range, evidence coverage, source refs, tool allowlist, memory namespace and duplicate checks. LLM self-evaluation can be an input candidate only; it MUST NOT replace gates.

Rationale: quality pass/fail, routing and publication must be replayable and auditable.

Alternatives considered:

- Let evaluator agents decide pass/fail: rejected because it breaks replay and allows worker output to control routing.
- Keep quality rules inside business steps: rejected because Harness must centralize phase transition decisions while business code supplies domain-specific gate definitions.

### 4. Research is rebuilt as a clean business domain

`business/research` SHALL own Research models, ports, use cases and workflow specs. It MUST NOT import `business/boards/paper_radar`, `interfaces` or concrete `infrastructure` adapters.

Rationale: old paper_radar mixes board scoring, reader payloads, visual compiler, API caches, worker queues and UI-facing public models. Research needs a domain model that can evolve without old paper API compatibility.

Alternatives considered:

- Adapt old `business/boards/paper_radar`: rejected because the PRD explicitly forbids old compatibility and because the old module carries UI/API payload assumptions.
- Build Research directly in `interfaces/services`: rejected because interface layers must call application services, not own business rules.

### 5. Skill evolution is a Harness-controlled lifecycle

Skill package loading, validation, quality gates, runtime execution and evaluation assets remain useful. New evolution workflows SHALL add candidate storage, static validation, held-out eval replay, promotion, versioned release and rollback under Harness control.

Rationale: existing `framework/skills/package`, `framework/skills/runtime`, `framework/skills/validation`, `framework/skills/quality` and `framework/skills/evaluation` are reusable, but production skill mutation must be governed.

Alternatives considered:

- Let ordinary Research reader repair patch active skills directly: rejected because business repair experience must first become memory and only later seed governed skill evolution.
- Put skill evolution in `business/foundation/skills`: rejected because skill content can live there, but production package promotion belongs to framework-level Harness governance.

### 6. Cleanup is staged and evidence-backed

Stage 0 SHALL only inventory keep/adapt/delete candidates. Stage 8 deletes old framework control-flow pollution; stage 9 deletes old business/interface/test compatibility. Each delete candidate needs reason, replacement and test action.

Rationale: removing old runtime before the new Harness + Research phases exist would break current checks and obscure root causes.

Alternatives considered:

- Delete old paper and board modules immediately: rejected for stage 0 because PRD only asks for audit and OpenSpec.
- Keep compatibility adapters indefinitely: rejected because the final architecture explicitly excludes old paper_radar compatibility.

## Risks / Trade-offs

- [Risk] Existing tests assert old paper/board behavior that later becomes invalid. → Mitigation: mark them now, delete or replace them only in stages 8/9 when replacement runtime exists.
- [Risk] `framework/workflow` and `framework/agent/loop` continue to make hidden decisions. → Mitigation: adapt them as worker utilities under Harness and add boundary tests for routing authority.
- [Risk] Research rebuild duplicates old paper_radar model names and payload fields. → Mitigation: require new `business/research` models and forbid imports from old paper_radar, interfaces and infrastructure.
- [Risk] Skill evolution accidentally mutates active skill packages. → Mitigation: require candidate repositories, held-out evals, versioned promotion and rollback before publication.
- [Risk] Context compression drops policy, gate, schema or source refs. → Mitigation: require explicit stable prefix / dynamic tail assembly and forbid compressing critical control material.
- [Risk] Cleanup removes useful low-level assets. → Mitigation: prefer keep/adapt for neutral framework primitives and only delete assets tied to old business, old interfaces, or business pollution.

## Migration Plan

1. Stage 0: create this OpenSpec change and `audit-inventory.md`; validate with `openspec validate harness-research-runtime --strict` and `python -m scripts.dev compile`.
2. Stages 1-4: implement Harness contracts, state machine, scheduler, ports, subagent isolation, context engineering, bounded RAG, skill evolution, trace, checkpoint and replay.
3. Stages 5A-7: define Research product scenarios, implement `business/research`, single-paper loop, reader repair memory, backend service and API router.
4. Stage 8: remove or adapt obsolete framework control-flow assets after Harness coverage exists.
5. Stage 9: remove old paper/board/interface/test compatibility after Research service and API coverage exist.
6. Rollback strategy: because stage 0 only adds docs/specs, rollback is limited to removing the new OpenSpec change and audit inventory. Later code phases must commit independently and preserve replacement tests before deletion commits.

## Open Questions

- Which old board capabilities, if any, should become reusable Research primitives rather than be deleted outright after stage 5?
- Should `framework/workflow` remain as a lower-level execution engine under Harness, or should later stages split its runner pieces more aggressively?
- Which persisted paper reader memories are valid Research repair memory inputs, and which are old UI/API payload artifacts that must be discarded?
