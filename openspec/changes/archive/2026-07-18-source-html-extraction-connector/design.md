## Design

`HtmlConnector` follows the same connector contract as existing source
connectors:

- `fetch(source, limit=None) -> (items, errors)`
- `parse(source, html_text, limit=None) -> list[RawSourceItem]`

The connector uses a stdlib `HTMLParser` based extractor. It extracts:

- `<title>` and `og:title`
- meta description / `og:description`
- canonical link / `og:url`
- `article:published_time`, date meta tags, and `<time datetime>`
- author meta tags
- visible main/body text, excluding script/style/nav/header/footer/aside/form
- `html lang`

The generated `RawSourceItem` stores extracted text as `raw_content`. Raw HTML is
left for artifact storage, keeping raw response and extracted text separated.

Confidence is deterministic and describes extraction completeness only. It must
not be treated as evidence confidence.

## Compatibility

Existing source types and connector behavior are unchanged. `html` is additive.
