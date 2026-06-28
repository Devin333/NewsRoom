## Why

The first blind/de-templated Paper RAG benchmark exposed a real generalization gap: template-style metrics were optimistic, while natural blind questions dropped to low Hit@10/MRR, especially for formula, figure, table, and experiment-result QA.

Part of the drop is valid retrieval weakness, but part of it comes from the benchmark question profile removing too much semantic information. Some blind questions no longer contain enough natural anchors to identify a unique figure, table, or formula within a paper section.

## What Changes

- Add a `blind_semantic` benchmark question profile.
- Keep `template` and `blind_detemplated` behavior available.
- Generate blind questions that hide labels and long caption/claim copies while preserving short semantic anchors.
- Add an ambiguity/quality audit for generated blind questions.
- Expose the selected profile and ambiguity audit in JSON/Markdown benchmark reports.

## Impact

This is an evaluation-first change. It improves the benchmark protocol before retrieval tuning. Production retrieval and answer generation defaults remain unchanged.
