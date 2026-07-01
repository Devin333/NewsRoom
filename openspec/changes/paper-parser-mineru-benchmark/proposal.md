# Paper Parser MinerU Benchmark

## Summary

Add a Docker-backed MinerU PDF parser backend for paper parser bake-off runs.
The default parser remains Nougat. Benchmark ingest can explicitly select
MinerU with `--pdf-parser-backend mineru` or `NEWSROOM_PDF_PARSER_BACKEND=mineru`.

## Why

Current PDF parsing uses Nougat plus Surya/PyMuPDF. MinerU may improve complex
paper layouts, formulas, tables, and image extraction, but it must be compared
with real papers before becoming a default.

## Non-goals

- Do not replace the default Nougat parser.
- Do not change the `DocumentParserPort` interface.
- Do not add cloud services or non-Docker local installs.
- Do not commit `.newsroom` benchmark artifacts.
