"""Webhook primitives for the interface boundary."""

from interfaces.webhooks.incoming import IncomingWebhookEvent, IncomingWebhookHandler
from interfaces.webhooks.outgoing import (
    OutgoingWebhookAttempt,
    OutgoingWebhookClient,
    OutgoingWebhookDeadLetter,
    OutgoingWebhookResult,
)
from interfaces.webhooks.signatures import build_signature_header, sign_payload, verify_signature

__all__ = [
    "IncomingWebhookEvent",
    "IncomingWebhookHandler",
    "OutgoingWebhookAttempt",
    "OutgoingWebhookClient",
    "OutgoingWebhookDeadLetter",
    "OutgoingWebhookResult",
    "build_signature_header",
    "sign_payload",
    "verify_signature",
]
