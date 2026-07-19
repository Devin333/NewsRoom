from __future__ import annotations


SOURCE_URL_GOLDEN_CASES = (
    ("blank", " \t ", None, ""),
    (
        "unresolved-relative",
        " ../Post/?utm_source=x#section ",
        None,
        "../Post/?utm_source=x#section",
    ),
    (
        "fragment-trailing-query-order",
        "HTTPS://Example.COM/News/?b=2&a=1#section",
        None,
        "https://example.com/News?a=1&b=2",
    ),
    (
        "tracking-case-duplicate-query",
        "https://example.com/post?UTM_Source=x&FbClId=y&GCLID=z&Topic=ML&Topic=AI&empty=",
        None,
        "https://example.com/post?Topic=AI&Topic=ML&empty=",
    ),
    (
        "https-default-port",
        "https://Example.com:443/post",
        None,
        "https://example.com/post",
    ),
    (
        "http-default-port",
        "http://Example.com:80/post",
        None,
        "http://example.com/post",
    ),
    (
        "custom-port",
        "https://Example.com:8443/post",
        None,
        "https://example.com:8443/post",
    ),
    (
        "ipv6-default-port",
        "https://[2001:DB8::1]:443/post",
        None,
        "https://[2001:db8::1]/post",
    ),
    (
        "userinfo-removed",
        "https://User:Pass@Example.com:443/post",
        None,
        "https://example.com/post",
    ),
    (
        "root-relative",
        "/post?utm_source=x",
        " https://Example.com/blog/index.html ",
        "https://example.com/post",
    ),
    (
        "path-relative",
        "post?b=2&a=1",
        "https://example.com/blog/",
        "https://example.com/blog/post?a=1&b=2",
    ),
    (
        "origin-root",
        "HTTPS://Example.com",
        None,
        "https://example.com/",
    ),
    (
        "non-http-source-scheme",
        "manual://Signal/path/",
        None,
        "manual://signal/path",
    ),
)


SOURCE_URL_MALFORMED_CASES = (
    ("invalid-port", "https://example.com:invalid/post"),
    ("invalid-ipv6", "https://[2001:db8::1/post"),
    ("absolute-without-host", "https:///post"),
)


__all__ = ["SOURCE_URL_GOLDEN_CASES", "SOURCE_URL_MALFORMED_CASES"]
