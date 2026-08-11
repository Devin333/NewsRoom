# llm-stream-cache-replay Specification

## Purpose
TBD - created by archiving change llm-cache-production-hardening. Update Purpose after archive.
## Requirements
### Requirement: Stream caching uses the router-owned cache lifecycle
Cache-aware streaming SHALL use the same route resolution, deployment identity, eligibility, lookup-before-cooldown/budget ordering, accounting, fallback, single-flight, response validation, rollout modes, and event sink as synchronous completion. Provider-client wrappers MUST NOT own a separate stream cache.

#### Scenario: Streaming hit precedes cooldown and budget
- **WHEN** an enabled capability-compatible deployment has a valid stream-replay entry while its provider is in cooldown or provider budget is exhausted
- **THEN** the router replays the entry without provider admission, provider call, fallback, or cooldown mutation

#### Scenario: Streaming miss preserves provider behavior
- **WHEN** no valid entry exists
- **THEN** the router applies existing cooldown, budget, provider stream, error, retry, and fallback behavior before considering a write

### Requirement: Source stream events are normalized and structurally validated
The miss path SHALL normalize every source item through `LLMStreamEvent.from_any` and feed a deterministic accumulator. A cacheable stream MUST contain exactly one `message_start`, zero or more allowed deltas in protocol order, exactly one `message_complete`, no event after completion, no error event, and no tool event or tool call.

#### Scenario: Valid completed text stream
- **WHEN** a stream emits one start, valid text/usage deltas, one complete event, and then terminates normally
- **THEN** accumulation produces one complete response eligible for deterministic write validation

#### Scenario: Missing or duplicate start is invalid
- **WHEN** deltas occur before start or more than one start occurs
- **THEN** the stream is not cached and existing stream error behavior is preserved

#### Scenario: Missing or duplicate completion is invalid
- **WHEN** the source terminates without completion, emits more than one completion, or emits any event after completion
- **THEN** no cache write occurs

#### Scenario: Tool event refuses caching
- **WHEN** the source emits any tool-call start, delta, complete event, or accumulated tool call
- **THEN** no cache entry is written or replayed for phase one

### Requirement: Provider events are yielded without waiting for cache storage
On a miss, the router SHALL yield validated normalized provider events as they arrive. Cache accumulation and bounded write eligibility SHALL not delay the full stream until completion, and cache write failure MUST NOT retroactively fail an otherwise successful provider stream.

#### Scenario: Deltas remain incremental
- **WHEN** the provider yields several text deltas
- **THEN** the caller receives each normalized delta before the provider stream finishes

#### Scenario: Write fails after terminal event
- **WHEN** the provider stream completes successfully but cache encoding or storage fails
- **THEN** all provider events remain successfully delivered and a redacted write-failure event is recorded

### Requirement: Only normal full consumption can populate the cache
A stream write SHALL occur only after the source iterator terminates normally following its unique completion event and the consumer fully exhausts the router generator. Cancellation, early close, iteration error, provider error, caller deadline, or generator finalization before normal exhaustion MUST leave no entry.

#### Scenario: Consumer closes early
- **WHEN** a consumer stops after receiving only part of the stream and closes the generator
- **THEN** no cache write is attempted

#### Scenario: Provider raises after deltas
- **WHEN** the provider raises an error before normal terminal exhaustion
- **THEN** partial content is never cached

#### Scenario: Cancellation follows complete event but precedes source exhaustion
- **WHEN** a completion event was observed but the consumer cancels before the iterator ends normally
- **THEN** no cache entry is written

#### Scenario: Normal exhaustion writes once
- **WHEN** an eligible stream completes, exhausts normally, validates, fits size limits, and mode permits writes
- **THEN** exactly one complete response write is attempted by the current single-flight owner

### Requirement: Accumulated stream responses pass the common write validator
After structural completion, the accumulated `LLMResponse` SHALL pass the same safe projection, tool refusal, response-format validation, output-schema validation, deployment identity, TTL, and size rules as synchronous responses. Stream metadata MUST NOT self-authorize a cache write.

#### Scenario: Accumulated structured output is invalid
- **WHEN** a complete stream cannot produce structured output conforming to the current request schema
- **THEN** deterministic validation rejects the result and no cache write occurs

#### Scenario: Accumulated response is oversized
- **WHEN** the safe encoded complete response exceeds `max_entry_bytes`
- **THEN** the delivered stream remains successful but no value is stored

### Requirement: Cache-hit replay emits a normalized bounded event sequence
A stream cache hit SHALL reconstruct a fresh response and emit a provider-independent legal sequence consisting of one `message_start`, zero or more bounded `text_delta` events, an optional source-usage event, and one `message_complete`. Replay MUST NOT promise the original provider's chunk boundaries, timing, IDs, raw fields, or mutable event objects.

#### Scenario: Text response replay
- **WHEN** a cached text response is replayed
- **THEN** the sequence starts once, emits the full content in chunks no larger than the configured replay bound, completes once, and can be reconstructed by `LLMStreamAccumulator`

#### Scenario: Empty response replay
- **WHEN** a valid cached response has empty content
- **THEN** replay still emits one start and one complete with no invalid empty-loop or duplicate event

#### Scenario: Replayed events are isolated
- **WHEN** a consumer mutates a dictionary converted from one replayed event
- **THEN** later replays and the stored response are unchanged

#### Scenario: Replay contains no tool events
- **WHEN** any phase-one entry is replayed
- **THEN** no tool-call start, delta, complete, or authorization-like event is emitted

### Requirement: Replay distinguishes source usage from current provider usage
Usage stored in an entry SHALL be presented only as source-result usage metadata. A replay SHALL record zero current provider calls, tokens, and cost, SHALL not settle provider budget, and SHALL not update cooldown. Logical request accounting SHALL still increase once.

#### Scenario: Usage-bearing replay
- **WHEN** an entry records tokens and estimated cost from its source provider call
- **THEN** replay can expose those values as source usage while current-call provider accounting remains zero

#### Scenario: Stream hit evidence reports avoided call
- **WHEN** a stream is replayed from cache
- **THEN** response/event metadata records a logical request and `provider_call=false` without attributing source usage to the current budget

### Requirement: Stream cache events are redacted and terminally accurate
The router SHALL emit redacted stream-cache eligibility, lookup, hit/miss, completion, bypass, and write events through the existing router event sink. It MUST emit write success only after normal exhaustion and successful storage, and MUST use stable reasons for interruption, early close, tool refusal, invalid protocol, validation failure, oversize, and backend failure.

#### Scenario: Interrupted stream evidence
- **WHEN** a source or consumer interrupts a cacheable stream
- **THEN** a stable non-write reason is emitted without partial content, prompt, scope, raw provider event, or full key

#### Scenario: Successful stream write evidence
- **WHEN** a complete validated stream is stored
- **THEN** write success is emitted after storage and includes only bounded route/deployment/mode/version/timing/size evidence

### Requirement: Replay respects caller deadlines and bounded work
Cache lookup, single-flight wait, decode, and replay chunking SHALL be bounded by configured limits and caller deadline. Replay MUST NOT start background threads or sleep to mimic provider timing.

#### Scenario: Deadline expires during single-flight wait
- **WHEN** a streaming caller's deadline expires before a waited-for entry appears
- **THEN** the router stops waiting and follows the existing deadline/error contract without replaying a partial value

#### Scenario: Replay is immediate and bounded
- **WHEN** a valid entry is replayed
- **THEN** events are generated synchronously in bounded chunks without provider-like delays or unbounded allocation
