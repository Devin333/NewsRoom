## Context

Parser bake-off already has ingest CLIs and a report builder that reads per-parser `research_document.json` artifacts plus optional RAG benchmark reports. The report currently summarizes raw parser metrics and recommendations, but raw averages can overstate quality when a parser skips difficult papers, fails ingest, emits many warnings, or lacks source locators and bounding boxes.

The enterprise RAG review specifically calls out the missing penalized bake-off path and a missing cascade 20-paper acceptance gate. This change adds those evaluation controls to the report layer so real artifact sets can be judged without changing production parser routing.

## Goals / Non-Goals

**Goals:**
- Add penalized parser scores that explicitly account for failures and missing evidence-quality metadata.
- Keep scoring deterministic and transparent through per-penalty details.
- Add cascade acceptance checks with a default 20-paper minimum.
- Let callers tune thresholds through the existing parser bake-off report CLI.
- Preserve existing report fields for current users.

**Non-Goals:**
- Download or parse the 20-paper corpus inside unit tests or PR CI.
- Change the default parser cascade order.
- Add a new production parser backend.
- Replace the full RAG benchmark suite.

## Decisions

1. Put penalized scoring in `paper_parser_bakeoff_report.py`.

   The bake-off report already has all parser summaries, ingest manifests, and optional RAG metrics. Adding scores there avoids duplicating artifact parsing and keeps scoring close to the report schema.

2. Report both raw and penalized signals.

   Existing raw metrics remain visible. New `penalized_metrics` fields include `raw_quality_score`, `penalty_total`, `penalized_quality_score`, `penalty_details`, and `acceptance_checks`. This prevents a single opaque score from hiding why a parser failed.

3. Use requested-count based acceptance.

   For real cascade acceptance, the relevant denominator is the requested corpus size from the ingest manifest. If no manifest is provided, the gate falls back to artifact count for local comparisons but marks the evidence source in the check details.

4. Make thresholds configurable from the CLI.

   Defaults are suitable for the review requirement: 20 requested papers, high parse success, useful locator coverage, and non-trivial RAG evidence metrics. CLI overrides allow calibration when a curated corpus has different expectations.

## Risks / Trade-offs

- Penalized score can be mistaken for an absolute scientific benchmark -> Mitigate by writing penalty details and raw metrics alongside it.
- Missing ingest manifests weaken the 20-paper gate -> Mitigate by making requested-count evidence explicit in acceptance check details.
- Threshold defaults may be too strict for early parser runs -> Mitigate by allowing CLI overrides while keeping the default gate honest for cascade acceptance.

## Migration Plan

1. Existing parser bake-off report callers continue to work because new fields are additive.
2. Teams running the real 20-paper cascade bake-off pass the cascade parser artifacts and ingest manifest to `run_parser_bakeoff_report`.
3. A failing acceptance gate is reported in JSON/Markdown; production parser routing is unchanged until a human reviews the artifact.
