## Why

The current Paper RAG benchmark proves that parser output, evidence alignment, and retrieval wiring are working, but many generated questions still include table labels, figure labels, equation labels, caption snippets, or quoted claims. That can make metrics too optimistic because the retriever can match benchmark templates instead of handling natural user questions.

## What Changes

- Add an explicit benchmark question profile for blind, de-templated Paper RAG evaluation.
- Preserve the existing template benchmark as the default regression profile.
- Mark blind/de-templated generated QA pairs with metadata so reports and audits can distinguish them.
- Expose the profile through `run_benchmark_suite` CLI and benchmark reports.

## Impact

This is an evaluation-only change. Production retrieval, parsing, chunking, and answer generation behavior remain unchanged.
