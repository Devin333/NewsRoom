from __future__ import annotations

import importlib.util
from pathlib import Path


_SDK_TEST_PATH = (
    Path(__file__).resolve().parents[1] / "interfaces" / "sdk" / "test_python_client.py"
)
_SPEC = importlib.util.spec_from_file_location("_newsroom_sdk_contract_tests", _SDK_TEST_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load SDK contract tests from {_SDK_TEST_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

globals().update(
    {
        name: value
        for name, value in vars(_MODULE).items()
        if name.startswith("test_")
    }
)
