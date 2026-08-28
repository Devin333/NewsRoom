# Framework Boundaries

`framework/` is the domain-neutral runtime layer. Its fixed top-level modules are:

- `agent`: owns `AgentLoop`, Action/Observation, ToolCall/SkillCall models, agent runtime, harness, and subagent support. It may call Skill Runtime through contracts but must not embed Skill Runtime internals.
- `artifacts`: owns artifact model, manifest, resolver, serializer, validator, store protocol, replay, and inspection.
- `events`: owns event model, event bus, filters, ordering, and replay.
- `governance`: owns safety policy, timeout policy, audit, human review, and security policy. It must not carry scoring algorithms.
- `llm`: owns LLM client contracts, request/response models, routing, cache, structured output, and redaction.
- `memory`: owns Memory runtime, indexing, recall/write policy, diagnostics, serialization, and tool integration.
- `scoring`: owns feature extraction, scoring context, gate, fusion, ranking, explanation, and registry. It must not encode Agora Hub business rules.
- `shared`: owns IDs, hashing, JSON serialization, and time helpers. It must not become a `common.py` or `utils.py` dumping ground.
- `skills`: owns Skill Runtime, manifest/metadata, package loader, registry, scanner, schema validation, prompt builder, executor, runner, quality gates, evaluator, and trace. It must not contain business skill content.
- `harness`: owns Graph definitions, normalized Graph compilation, preflight validation, activity bindings, runtime resolution, Graph state, Waits, and Graph control-plane contracts.
- `tool`: owns tool definition, schema, registry, runtime, built-in tools, tool governance, and inspection.
- `workers`: owns worker runtime, queue, scheduler, registry, approval, and diagnostics.
- `harness` keeps the outer control plane separate from the bounded AgentLoop inner loop: AgentLoop handles action/observation, tool calls, and single-agent diagnostics, but does not own Graph routing, quality gates, Wait transitions, memory writes, or publication.

## Forbidden Dependencies

`framework` must not import from `business`, `interfaces`, or concrete infrastructure adapter modules. Protocols and neutral model contracts are allowed; implementation binding belongs in business assembly, infrastructure adapters, or application services.

## Stability Rule

Framework code defines reusable runtime behavior only. Agora Hub business concepts such as sources, reports, boards, evidence, claims, and daily intelligence profiles belong outside `framework`.

Graph activity executors may support generic declaration-driven mechanics, but node identity, routing, gate policy, and business meaning belong to the Graph definition and Harness control plane. AgentLoop telemetry remains an inner activity result; framework code must not turn it into a second outer controller.

## LLM Configuration

`framework.llm` owns domain-neutral model configuration loading and schema validation. `configs/models.yaml` is validated at load time for known top-level, route, deployment, and capability fields so misspelled model config keys fail fast before any Graph run starts.

Config file read and decode failures are normalized to `LLMConfigurationError` without echoing file content, so interface-layer diagnostics and live smoke readiness checks can report `model_config` failures without duplicating framework schema rules or leaking secrets.
