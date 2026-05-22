from __future__ import annotations

import argparse
from collections.abc import Callable


CommandHandler = Callable[[argparse.Namespace], int]


def call_handler(args: argparse.Namespace, handler: CommandHandler) -> int:
    return handler(args)


__all__ = ["CommandHandler", "call_handler"]
