## 1. OpenSpec

- [x] 1.1 Validate the `framework-scoring-runtime-v2` OpenSpec change with strict validation

## 2. Framework Package Classification

- [x] 2.1 Add classified `framework/scoring` subpackages and migrate implementation behind them
- [x] 2.2 Convert existing top-level scoring modules into compatibility wrappers
- [x] 2.3 Register all new framework scoring packages in packaging metadata

## 3. V2 Framework API

- [x] 3.1 Add v2 core helpers, errors, feature providers, normalizers, recipe loaders, and dict adapters
- [x] 3.2 Add algorithm class names and composite algorithm support while preserving scorer compatibility
- [x] 3.3 Extend registry with algorithms, normalizers, and default gate specs

## 4. Business Scoring Migration Layer

- [x] 4.1 Add `business/scoring` adapters, feature builders, recipes, and application service without switching existing board flows
- [x] 4.2 Register new business scoring packages in packaging metadata

## 5. Tests and Validation

- [x] 5.1 Add categorized framework scoring tests for v2 imports and APIs
- [x] 5.2 Add business scoring migration tests
- [x] 5.3 Run compile, framework scoring tests, business scoring tests, board/business regressions, boundary checks, and strict OpenSpec validation
