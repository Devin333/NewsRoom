## Design

`HtmlConnector.parse()` now computes:

```python
url = canonicalize_url(extraction.canonical_url or source.url, base_url=source.url)
```

The item URL and metadata `canonical_url` both use the normalized value.

## Compatibility

Absolute canonical URLs without tracking parameters remain unchanged.
