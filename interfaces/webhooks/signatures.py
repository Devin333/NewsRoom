from __future__ import annotations

import hmac
from hashlib import sha256


SIGNATURE_PREFIX = "sha256="


def sign_payload(payload: bytes, secret: str) -> str:
    if not secret:
        raise ValueError("webhook secret is required")
    return hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()


def build_signature_header(payload: bytes, secret: str) -> str:
    return f"{SIGNATURE_PREFIX}{sign_payload(payload, secret)}"


def verify_signature(payload: bytes, secret: str, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    signature = signature_header.strip()
    if signature.startswith(SIGNATURE_PREFIX):
        signature = signature[len(SIGNATURE_PREFIX) :]
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(signature, expected)
