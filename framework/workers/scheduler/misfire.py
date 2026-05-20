from __future__ import annotations

from enum import Enum


class MisfirePolicy(str, Enum):
    SKIP = "skip"
    RUN_ONCE = "run_once"
    CATCH_UP = "catch_up"
    CATCH_UP_LIMITED = "catch_up_limited"
