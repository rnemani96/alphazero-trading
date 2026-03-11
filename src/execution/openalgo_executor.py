"""
src/execution/openalgo_executor.py

Thin re-export so code that imports from this path works correctly.
The real implementation lives in src/mercury.py (OpenAlgoExecutor class)
to keep MERCURY as the single execution gate per architecture.
"""
from src.mercury import OpenAlgoExecutor  # noqa: F401 — re-export

__all__ = ["OpenAlgoExecutor"]
