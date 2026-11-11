"""Backward-compatible entry point so ``uvicorn main:app`` keeps working.

The application lives in the ``app`` package; prefer ``uvicorn app.main:app``.
"""

from app.main import app

__all__ = ["app"]
