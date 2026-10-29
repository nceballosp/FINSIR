"""Single global exception handler.

All exceptions are mapped to status codes and the consistent error envelope
here, and ERROR events are logged at this one point (no log-and-throw, no
per-layer logging). Stack traces are never returned to the client.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.adapters.driving.http.auth import AuthError
from app.adapters.driving.http.correlation import get_correlation_id
from app.adapters.driving.http.schemas import ErrorBody, ErrorResponse
from app.domain.errors import (
    ClientNotFoundError,
    InvalidQueryError,
    RepositoryError,
)

_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404
_HTTP_UNPROCESSABLE = 422
_HTTP_INTERNAL_ERROR = 500


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message),
        correlationId=get_correlation_id(),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_exception_handlers(app: FastAPI, logger: logging.Logger) -> None:
    """Register the global exception handlers on ``app``.

    Args:
        app: The FastAPI application.
        logger: The configured JSON logger; ERROR events are emitted here only.
    """

    @app.exception_handler(ClientNotFoundError)
    async def _handle_not_found(_: Request, error: ClientNotFoundError):
        return _error_response(_HTTP_NOT_FOUND, "client_not_found", str(error))

    @app.exception_handler(InvalidQueryError)
    async def _handle_invalid_query(_: Request, error: InvalidQueryError):
        return _error_response(_HTTP_BAD_REQUEST, "invalid_query", str(error))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, __: RequestValidationError):
        return _error_response(
            _HTTP_UNPROCESSABLE, "validation_error", "Invalid request parameters"
        )

    @app.exception_handler(AuthError)
    async def _handle_auth(_: Request, error: AuthError):
        return _error_response(error.status_code, error.code, error.message)

    @app.exception_handler(RepositoryError)
    async def _handle_repository(_: Request, error: RepositoryError):
        logger.error(
            "repository_error",
            extra={"error_type": type(error).__name__, "error_message": str(error)},
        )
        return _error_response(
            _HTTP_INTERNAL_ERROR, "internal_error", "Internal server error"
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, error: Exception):
        logger.error(
            "unhandled_exception",
            extra={"error_type": type(error).__name__, "error_message": str(error)},
        )
        return _error_response(
            _HTTP_INTERNAL_ERROR, "internal_error", "Internal server error"
        )
