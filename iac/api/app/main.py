"""ASGI entrypoint. Run with ``uvicorn app.main:app``."""

from __future__ import annotations

from app.adapters.driving.http.app_factory import create_app

app = create_app()
