## Design

The taxonomy module returns a typed classification containing the error type,
retryability, and whether it should affect source health. Connectors keep their
existing error construction shape but delegate classification to this module.

The daily workflow emits parse events around connector execution because fetch
and parse are currently coupled inside connector methods.
