# Paper Parser Marker Benchmark

## Summary

Add a Docker-backed Marker PDF parser backend for paper parser bake-off runs.
The default parser remains Nougat. Benchmark ingest can explicitly select
Marker with `--pdf-parser-backend marker` or `NEWSROOM_PDF_PARSER_BACKEND=marker`.

## Why

Marker may provide a lighter RAG-friendly PDF to JSON/Markdown parser than
Nougat for some academic papers. It must be compared with real papers before
becoming a default.

## Non-goals

- Do not replace the default Nougat parser.
- Do not change the `DocumentParserPort` interface.
- Do not enable Marker LLM mode in the first benchmark.
- Do not commit `.newsroom` benchmark artifacts.
