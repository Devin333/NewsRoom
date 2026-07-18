## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` requires explicit parse/cooldown
events and a unified Source Error Taxonomy. Current workflows only emit coarse
normalization events, and connectors duplicate exception classification logic.

## What Changes

- Add a centralized source error taxonomy helper.
- Route connector and health-check exception classification through the helper.
- Emit `source_parse_started`, `source_parse_succeeded`, `source_parse_failed`,
  and `source_cooldown_started` events in the daily Source Pipeline.

## Out Of Scope

- Rewriting connector fetch/parse APIs.
- Long-term source event storage beyond existing run artifacts.
