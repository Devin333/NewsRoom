## Context

`DailyIntelligenceRunner` and `AgenticDailyIntelligenceRunner` duplicate connector setup and source assembly. `interfaces/cli/news.py` owns many command groups. Daily artifact publishing also mixes source, evidence, quality, agentic, and report artifact logic in one file.

## Goals / Non-Goals

**Goals:**
- Share daily source runtime assembly between normal and agentic runners.
- Continue reducing CLI file size with compatibility preserved.
- Split artifact publishing internals behind the existing facade.
- Clarify gate naming responsibilities.

**Non-Goals:**
- No public runner constructor changes.
- No artifact manifest key changes.
- No broad memory model migration.
- No gate type renaming.

## Decisions

- Introduce `runtime_assembly.py` with a dataclass that owns source registry, fetch policy, shared rate limiter, connectors, dispatcher, collector, and health manager.
- Runners instantiate the assembly and keep existing attributes for compatibility with tests and callers.
- CLI command groups move incrementally to modules under `interfaces/cli/commands`; `news.py` remains the parser/compatibility layer.
- Artifact publisher split uses private helper modules while `DailyIntelligenceArtifactPublisher` keeps the same public class and publisher id.

## Risks / Trade-offs

- Daily runner tests assert injected connector behavior -> assembly must copy all existing constructor defaults and attribute names.
- CLI command modules can break monkeypatches -> facade wrappers continue to resolve service classes from `interfaces.cli.news`.
- Artifact publisher split can disturb manifest order or keys -> tests must verify existing manifest artifacts unchanged.
