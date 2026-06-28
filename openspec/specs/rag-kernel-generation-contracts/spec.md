# rag-kernel-generation-contracts Specification

## Purpose
TBD - created by archiving change rag-kernel-generation-contracts. Update Purpose after archive.
## Requirements
### Requirement: Kernel defines generation contracts
The RAG kernel SHALL provide domain-neutral generated answer and generation context contracts.

#### Scenario: Generated answer serializes context ids and metadata
- **WHEN** a generated RAG answer is serialized
- **THEN** it includes the question, answer, context ids, contexts, and metadata

### Requirement: Kernel builds grounded numbered-context prompts
The RAG kernel SHALL provide a prompt builder for numbered context passages and citation-grounded answers.

#### Scenario: Prompt includes numbered contexts
- **WHEN** a question and context strings are provided
- **THEN** the prompt includes numbered context passages
- **AND** instructs the model to cite numbered passages

### Requirement: Kernel parses bracket citation indexes
The RAG kernel SHALL parse bracketed citation numbers into unique zero-based context indexes.

#### Scenario: Duplicate or out-of-range citations are ignored
- **WHEN** an answer contains duplicate or out-of-range bracket citations
- **THEN** only unique valid context indexes are returned

### Requirement: Paper generation uses kernel prompt builder
Research answer generation SHALL use the kernel prompt builder while keeping Paper-specific context selection and LLM orchestration in Research.

#### Scenario: Paper prompt remains compatible
- **WHEN** Research builds an answer generation prompt
- **THEN** the prompt still contains the same grounded instruction, numbered contexts, question, and citation answer marker

