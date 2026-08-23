"""Top-level framework package."""

from framework.shared import env as env
from framework.shared.env import load_root_env

load_root_env()

from framework import shared

# The root package intentionally exposes only cross-cutting primitives. Graph
# orchestration and Artifact ownership live behind their respective namespaces;
# Retired orchestration runtime objects are not part of the public API.
__all__ = ["env", "shared"]
