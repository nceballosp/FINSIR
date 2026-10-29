"""Unauthenticated health endpoint for App Runner health checks."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def get_health() -> dict[str, str]:
    """Return a simple liveness payload (no authentication required)."""
    return {"status": "ok"}
