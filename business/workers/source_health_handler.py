"""Compatibility import for the signal-layer source health worker handler."""

from business.layers.signal.worker_handlers import SourceHealthCheckTaskHandler

__all__ = ["SourceHealthCheckTaskHandler"]
