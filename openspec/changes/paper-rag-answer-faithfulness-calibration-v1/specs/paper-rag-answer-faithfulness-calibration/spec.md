## ADDED Requirements

### Requirement: Answer judge emits claim-level evidence judgments

Paper RAG answer judge SHALL emit structured per-answer claim judgments instead of only aggregate scores.

#### Scenario: LLM answer judge returns structured claims

- **WHEN** answer judge is enabled for generated answers
- **THEN** each judged sample SHALL include claim judgments with `claim_text`, `verdict`, `support_chunk_ids`, and `reason`
- **AND** verdicts SHALL be normalized to `supported`, `contradicted`, or `insufficient`
- **AND** aggregate metrics SHALL include claim support, contradiction, unsupported claim, answer faithfulness, answer relevance, and context precision

### Requirement: Answer judge evaluates citation grounding

Paper RAG answer judge SHALL diagnose whether answer citations support the claims they cite.

#### Scenario: Citation points to the wrong evidence

- **WHEN** a claim is supported by one chunk but cites a different unsupported chunk
- **THEN** the judge output SHALL mark `wrong_citation=true`
- **AND** report metrics SHALL include `wrong_citation_rate` and `citation_claim_support_rate`

#### Scenario: Supported claim has no citation

- **WHEN** a supported claim has no citation to supporting evidence
- **THEN** the judge output SHALL mark `missing_citation=true`
- **AND** report metrics SHALL include `missing_citation_rate`

### Requirement: Human spot-check annotations support answer-level quality fields

Human spot-check summaries SHALL validate and summarize answer-level annotation fields.

#### Scenario: Extended annotation is provided

- **WHEN** an annotation JSONL item includes answer, faithfulness, citation, retrieval, and context quality booleans
- **THEN** schema validation SHALL reject non-boolean values for those fields
- **AND** report output SHALL include human answer, faithfulness, and citation ok rates

### Requirement: LLM judge is calibrated against human annotations

Paper RAG reports SHALL compare LLM judge pass/fail outcomes with matching human annotations.

#### Scenario: Human annotation and LLM judge disagree

- **WHEN** a human annotation matches a judged answer by `paper_id`, `qa_type`, and `question`
- **AND** the human pass/fail verdict differs from the LLM judge verdict
- **THEN** the report SHALL count a judge-human conflict
- **AND** it SHALL write the conflict to `human_spot_check_conflicts.jsonl`
- **AND** calibration metrics SHALL include agreement, precision, recall, false positive rate, and false negative rate

### Requirement: Answer judge failures produce repair artifacts

Paper RAG benchmark suite SHALL write repair artifacts for answer judge failures and human conflicts.

#### Scenario: Answer judge detects unsupported claim or citation error

- **WHEN** answer judge metrics violate claim or citation thresholds
- **THEN** the suite output SHALL include `answer_judge_failures.jsonl`
- **AND** it SHALL include `answer_fix_manifest.json`
- **AND** manifest items SHALL include standardized failure reasons and suggested actions
