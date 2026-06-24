## ADDED Requirements

### Requirement: Visual Element Chunks Separate Location Caption And References
Research paper figure and table chunks SHALL represent the visual element location, caption evidence, and body-reference evidence as separate traceable metadata fields.

#### Scenario: Figure chunk preserves visual location independently
- **WHEN** a figure chunk is emitted for a PDF figure with an image crop and caption region
- **THEN** its metadata MUST include the image reference, visual page/bbox locator, caption text, caption page/bbox locator, and caption match strategy
- **AND** body paragraph references MUST NOT overwrite the figure source locator

#### Scenario: Table chunk preserves caption and row evidence
- **WHEN** a table chunk is emitted for a PDF table with rows and caption region
- **THEN** its content MUST include caption and row text
- **AND** its metadata MUST include table id, row count, visual/caption locators, and caption match strategy when available

### Requirement: Body References Link To Visual Elements
Research paper chunking SHALL detect explicit paragraph references to figures and tables and attach those paragraph chunk ids to the referenced visual element chunks.

#### Scenario: Cross-page reference is modeled as a reference
- **WHEN** a paragraph on one page says "see Figure 1" and Figure 1 is located on another page
- **THEN** the Figure 1 chunk MUST include that paragraph id in `referenced_by_chunks`
- **AND** the Figure 1 chunk MUST retain the figure page/bbox as its source locator

#### Scenario: Missing body reference leaves visual chunk valid
- **WHEN** no paragraph explicitly references a figure or table number
- **THEN** the figure or table chunk MUST still include caption and visual location metadata when available
- **AND** `referenced_by_chunks` MUST be empty or omitted rather than inferred from proximity
