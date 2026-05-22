# Framework Boundaries

`framework/` is the domain-neutral runtime layer. Its fixed top-level modules are:

- `agent`: owns `AgentLoop`, Action/Observation, ToolCall/SkillCall models, agent runtime, harness, and subagent support. It may call Skill Runtime through contracts but must not embed Skill Runtime internals.
- `artifacts`: owns artifact model, manifest, resolver, serializer, validator, store protocol, replay, and inspection.
- `events`: owns event model, event bus, filters, ordering, and replay.
- `governance`: owns safety policy, timeout policy, audit, human review, and security policy. It must not carry scoring algorithms.
- `llm`: owns LLM client contracts, request/response models, routing, cache, structured output, and redaction.
- `memory`: owns Memory runtime, indexing, recall/write policy, diagnostics, serialization, and tool integration.
- `scoring`: owns feature extraction, scoring context, gate, fusion, ranking, explanation, and registry. It must not encode NewsRoom business rules.
- `shared`: owns IDs, hashing, JSON serialization, and time helpers. It must not become a `common.py` or `utils.py` dumping ground.
- `skills`: owns Skill Runtime, manifest/metadata, package loader, registry, scanner, schema validation, prompt builder, executor, runner, quality gates, evaluator, and trace. It must not contain business skill content.
- `specs`: owns WorkflowSpec, StepSpec, EdgeSpec, TriggerSpec, and PolicySpec. It only defines specifications and does not execute them.
- `tool`: owns tool definition, schema, registry, runtime, built-in tools, tool governance, and inspection.
- `workers`: owns worker runtime, queue, scheduler, registry, approval, and diagnostics.
- `workflow`: owns compiler, runtime, runners, buffer, checkpoint, routing, scheduling, operations, and inspection.

## Forbidden Dependencies

`framework` must not import from `business`, `interfaces`, or concrete infrastructure adapter modules. Protocols and neutral model contracts are allowed; implementation binding belongs in business assembly, infrastructure adapters, or application services.

## Stability Rule

Framework code defines reusable runtime behavior only. NewsRoom business concepts such as sources, reports, boards, evidence, claims, and daily intelligence profiles belong outside `framework`.
