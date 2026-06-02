from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid"}


def canonicalize_url(url: str, *, base_url: str | None = None) -> str:
    raw_url = url.strip()
    if base_url:
        raw_url = urljoin(base_url.strip(), raw_url)
    parts = urlsplit(raw_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_KEYS and not key.startswith(TRACKING_PREFIXES)
    ]
    normalized_path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            _canonical_netloc(parts),
            normalized_path,
            urlencode(sorted(query)),
            "",
        )
    )


def _canonical_netloc(parts) -> str:
    scheme = parts.scheme.lower()
    host = (parts.hostname or parts.netloc).lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host
    return f"{host}:{port}"


__all__ = ["canonicalize_url"]

