## Context

The live real-corpus answer run after intent routing repair still had an expected-abstain sample asking whether an axial-attention paper specified a commercial smartphone launch date. The model answered by reciting axial-attention context and cited chunks, so phrase-based abstention detection did not fire.

The Harness must keep deterministic control over quality decisions. The LLM can generate a candidate answer, but unsupported publication, abstention, and routing decisions must remain in deterministic code.

## Goals / Non-Goals

**Goals:**

- Detect common Paper negative presence questions after answer generation.
- Abstain when the generated answer does not mention the salient requested target terms and instead appears to answer a different part of the paper.
- Preserve supported yes/no answers that mention the requested target.
- Expose metadata that explains the deterministic normalization.

**Non-Goals:**

- Do not change retrieval routing, scoring thresholds, or live eval success thresholds.
- Do not hardcode paper ids, paper titles, or one exact failure question.
- Do not add another LLM call or ask the LLM to judge relevance.

## Decisions

- Put the guard in `PaperAnswerWorker` after generation and before `GroundedAnswerCandidate` publication. This location can turn a candidate into an abstention with standard answer-worker metadata and does not disturb retrieval or prompt construction.
- Extract target terms from the question using a conservative verb pattern around `include`, `specify`, `report`, `discuss`, `provide`, `state`, `mention`, `describe`, `contain`, and related presence verbs. Stopwords and generic paper/evidence words are removed.
- Trigger only when the generated answer is not already an abstention and the answer has too little overlap with the extracted target terms. This catches unrelated recitations while allowing supported answers that mention the requested subject.

## Risks / Trade-offs

- Over-abstention on terse supported "Yes" answers without target terms -> Mitigation: require at least two salient target terms and add a regression test that a supported answer with target overlap is preserved.
- Missed unsupported cases with synonyms instead of exact target words -> Mitigation: keep this deterministic guard narrow and rely on future real-corpus taxonomy to expand terms deliberately.
- Metadata growth in generated-answer payloads -> Mitigation: store only compact target terms and overlap score.
