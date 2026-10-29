"""Correlation-id context and middleware.

The correlation id ties all logs for one request together. The middleware
reuses an inbound ``X-Correlation-ID`` header when present, otherwise it
generates a UUID4, and always echoes the value back in the response header.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the correlation id bound to the current request context."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Bind a correlation id to the current context (used in tests/handlers)."""
    _correlation_id.set(correlation_id)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id per request and return it in the response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Resolve the correlation id, process the request, and echo it back."""
        incoming = request.headers.get(CORRELATION_ID_HEADER)
        correlation_id = incoming if incoming else str(uuid.uuid4())
        token = _correlation_id.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            _correlation_id.reset(token)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
