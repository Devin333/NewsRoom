## 1. Shared API Cleanup

- [x] 1.1 Remove the Shared `canonical_json` wrapper and public re-export while preserving `stable_json_dumps` bytes.
- [x] 1.2 Update Shared JSON tests to cover the unique serializer API and layered hashing behavior.
- [x] 1.3 Confirm repository production code has no dependency on the removed Shared symbol and TaskPlan canonicalization remains separate.

## 2. Learning Materials

- [x] 2.1 Update `framework-shared.md` to distinguish conversion, serialization, and hashing functions without slash-as-synonym wording.
- [x] 2.2 Redraw the Shared JSON/hashing Excalidraw diagram as the actual nested dependency chain and validate its structure.

## 3. Verification

- [x] 3.1 Run strict OpenSpec validation and targeted Shared tests.
- [x] 3.2 Run compile and the required smoke gate, then verify the source tree and learning-artifact references.
- [x] 3.3 Commit the completed code, OpenSpec artifacts, tests, and scoped learning-document updates where version control is available.
