## 1. OpenSpec Setup

- [x] 1.1 Create proposal, design, specs, and tasks for `business-final-target-0-to-1`.
- [x] 1.2 Validate the change with `openspec validate business-final-target-0-to-1 --strict`.

## 2. Foundation Contracts

- [x] 2.1 Add foundation quality learning-loop models and exports.
- [x] 2.2 Add policy loader, snapshot, candidate, activation, and regression guard helpers.
- [x] 2.3 Add feedback collector, aggregator, learning signal builder, and in-memory store.

## 3. Layer Pipelines

- [x] 3.1 Add PRD-compatible Signal layer modules for raw input mapping, normalization, dedupe, classification, quality checks, rejection stats, and pipeline aliases.
- [x] 3.2 Add PRD-compatible Extraction layer modules and quality checks around the existing extraction pipeline.
- [x] 3.3 Add Relation layer linker modules, validator, quality checks, and evidence merge behavior.
- [x] 3.4 Add Analysis layer analyzer modules and ranking feature helpers.
- [x] 3.5 Add Output layer builder aliases, quality checks, final-target DTO fields, and BoardRunResult wrapping.

## 4. Boards and Cross-Board

- [x] 4.1 Add AI News, Project Radar, Paper Radar, and Community Pulse models, policies, ranking rules, presenters, workflows, and BoardRunResult methods.
- [x] 4.2 Add cross-board models, relation view service, technology journey service, technology radar service, insight service, policies, and regression guard.
- [x] 4.3 Ensure board and cross-board outputs include policy snapshots, quality summaries, feedback candidates, ranking reasons, evidence refs, provenance, trace refs, and manifest refs.

## 5. Interfaces and Boundaries

- [x] 5.1 Add or update CLI/API/MCP/Web board contracts to consume board services and DTOs.
- [x] 5.2 Add dependency boundary tests for foundation, layers, boards, and interfaces.

## 6. Verification

- [x] 6.1 Add foundation, layer, board, cross-board, interface, and boundary tests.
- [x] 6.2 Run compile, OpenSpec validation, phase tests, and existing repo checks; fix failures forward.
