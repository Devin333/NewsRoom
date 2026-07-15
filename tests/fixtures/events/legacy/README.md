# Legacy durable-event migration fixtures

These files freeze the supported and unsafe historical shapes discovered by
`durable-event-runtime` task 1.1. Import and dry-run code must treat every file
as read-only. Fixed identities and timestamps make repeated scans deterministic.

## Importable fixtures

| File | Shape | Expected mapping |
| --- | --- | --- |
| `valid/framework_event_record_v1.jsonl` | framework flat record, including the supported `timestamp` alias | One canonical event per line; preserve id/time and store the 0-based source offset separately |
| `valid/framework_event_envelope_v1.jsonl` | envelope with nested `newsroom.event.v1` and equal duplicate context | Accept one authoritative context and preserve event identity/correlation |
| `valid/storage_event_record.jsonl` | schema-less storage record with diagnostic identifiers | Map `timestamp`, business identifiers, severity, and explicitly redacted payload |
| `valid/workflow_flat.jsonl` | minimal historical workflow artifact | Use registered legacy mapping and deterministic identity; never invent current time |
| `valid/harness_history.jsonl` | typed Harness event and event-log projection | Preserve transition time/run/step and map through Harness schemas |
| `valid/checkpoints.json` | legacy workflow and Harness checkpoint boundaries | Preserve legacy offset metadata and map through an explicit 0-based-to-1-based table |
| `valid/checkpoint_boundary_mappings.json` | recorded checkpoint-to-import boundary identities | Resolve offset zero, last line, and empty history without assuming offset arithmetic |
| `valid/schema_upcast_v1.jsonl` | registered historical payload schema | Resolve through the complete adjacent upcaster chain without changing occurrence time or source bytes |

## Quarantine fixtures

| File | Expected reason |
| --- | --- |
| `invalid/context_conflict_envelope_v1.jsonl` | `context_conflict` |
| `invalid/missing_time_record_v1.jsonl` | `missing_occurred_at` |
| `invalid/unknown_schema.jsonl` | `unknown_schema` |
| `invalid/malformed.jsonl` | `invalid_json` |
| `invalid/non_object.jsonl` | `invalid_record_type` |
| `invalid/unsafe_run_id.jsonl` | `invalid_stream_identity` before any write |
| `invalid/secret_payload.jsonl` | `security_policy_violation`; raw secret must never reach a new durable write or diagnostic |
| `invalid/same_id_collision.jsonl` | first record importable, second record `identity_collision` |
| `invalid/upcast_failure.jsonl` | `upcast_failed`; bounded diagnostic must not include payload values |

Blank lines may be ignored but must retain physical source location in the
migration report. Re-reading any fixture must yield the same import/quarantine
classification, stable import key, and checksum.
