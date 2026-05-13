"""Webhook primitives for the interface boundary."""

from interfaces.webhooks.incoming import IncomingWebhookEvent, IncomingWebhookHandler
from interfaces.webhooks.outgoing import OutgoingWebhookClient, OutgoingWebhookResult
from interfaces.webhooks.signatures import build_signature_header, sign_payload, verify_signature

__all__ = [
    "IncomingWebhookEvent",
    "IncomingWebhookHandler",
    "OutgoingWebhookClient",
    "OutgoingWebhookResult",
    "build_signature_header",
    "sign_payload",
    "verify_signature",
]
