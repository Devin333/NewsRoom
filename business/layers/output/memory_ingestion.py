"""Compatibility bridge for memory ingestion moved to business.layers.memory."""

# TODO(boundary-migration): legacy adapter, remove after business memory services are stable.
from business.layers.memory.ingestion import *  # noqa: F401,F403
