# Evaluation Data

`golden_set.json` is the reviewed retrieval and answer evaluation contract.
`golden_corpus_snapshot.json` is the smallest version-controlled subset of the
real parsed corpus needed to hydrate that contract in a clean checkout. It
contains every referenced gold chunk, source lineage, stable parsed-document
checksums, and a checksum over the complete snapshot. It is not a replacement
for the full local `.newsroom/papers` corpus.

After refreshing or re-curating the real corpus, rebuild and verify the snapshot:

```powershell
python -m data.eval.build_golden_corpus_snapshot
python -m data.eval.build_golden_corpus_snapshot --check
```

The document checksum excludes only `parse_artifact_dir` and `parse_artifacts`,
which are machine-local output paths. Content, parser quality metadata, source
hashes, and lineage remain covered. CI validates the snapshot against the exact
bytes of `golden_set.json` and validates each chunk's content hash and semantic
key before hydration.
