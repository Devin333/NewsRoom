## ADDED Requirements

### Requirement: Natural query intent coverage

Paper RAG SHALL classify natural user phrasing for quantitative evidence, visual evidence, mathematical relations, and result takeaways into the intended retrieval intent.

#### Scenario: Mathematical relation questions

- **WHEN** the query says "mathematical relation", "objective", "loss", or "optimization"
- **THEN** it SHALL route to `formula_query`

#### Scenario: Visual evidence questions

- **WHEN** the query says "visual evidence", "diagram", "plot", "mask", "architecture figure", or "example images"
- **THEN** it SHALL route to `figure_query`

#### Scenario: Quantitative result questions

- **WHEN** the query says "quantitative evidence", "reported experiments", "performance", "score", "accuracy", "BLEU", or "F1"
- **THEN** it SHALL route to result/table evidence routes

### Requirement: Route observability

Paper RAG evaluation reports SHALL expose which retrieval intents and recall routes were used.

#### Scenario: Benchmark report route distribution

- **WHEN** a benchmark suite is run
- **THEN** the candidate report SHALL include `intent_distribution`, `route_distribution`, and `intent_confusion`
- **AND** the Markdown report SHALL include a Route Distribution section
