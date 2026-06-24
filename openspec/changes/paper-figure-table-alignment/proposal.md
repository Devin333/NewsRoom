## Why

Figure and table chunks already carry captions, image references, nearby context, and PDF locators, but nearby context can be misleading when a paragraph references a figure on another page. The parser should model the visual region, caption region, and body references as separate evidence so retrieval and reader surfaces can explain why a figure or table was returned.

## What Changes

- Add first-class figure/table reference metadata that records which paragraph chunks mention a visual element by number, without treating those paragraphs as the visual element location.
- Preserve explicit caption evidence on figure/table chunks, including caption text, caption locator, caption page/bbox, match strategy, and confidence when available.
- Keep nearby context as supporting text only, with metadata that distinguishes it from caption and body-reference evidence.
- Extend tests so cross-page figure/table references do not overwrite the visual source locator.

## Capabilities

### New Capabilities
- `paper-visual-element-alignment`: Defines how Research paper figure/table chunks represent visual regions, captions, and body references.

### Modified Capabilities
- `research-runtime`: Research paper chunking must expose traceable figure/table alignment metadata for downstream RAG and reader evidence.

## Impact

- Affects `business/research/document/chunker.py` and tests around paper chunk generation.
- Does not change persisted schema because the new fields are stored in existing chunk metadata payloads.
- Does not require new external services or model dependencies.
