# Offline History Fixtures

These records are frozen, detached inputs for the history-only migration
classifier. They retain source checksums and deterministic Graph mapping
evidence so repeated audit runs produce the same plan checksum.

The records are staging evidence only. They must never be imported by
production composition, resumed, replayed for execution, dispatched to a
worker, written to memory, or published as artifacts.
