"""Central structured (JSON) logging.

A single JSON formatter emits the log field set required by the logging
standard: ``@timestamp`` (ISO 8601 UTC), ``level``, ``message`` (stable key),
``service.name/version/environment``, ``logger``, and ``correlationId``.
Error events add ``error.type`` / ``error.message``. ``print`` is never used.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.adapters.driving.http.correlation import get_correlation_id

LOGGER_NAME = "finsir.api"

# Reserved LogRecord attributes we never copy into the JSON payload blindly.
_RESERVED_LOG_RECORD_KEYS = frozenset(vars(logging.makeLogRecord({})).keys())


class JsonLogFormatter(logging.Formatter):
    """Format log records as single-line JSON per the logging standard."""

    def __init__(
        self, service_name: str, service_version: str, service_environment: str
    ) -> None:
        super().__init__()
        self._service_name = service_name
        self._service_version = service_version
        self._service_environment = service_environment

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a JSON string with the standard fields."""
        timestamp = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).isoformat()
        payload: dict[str, Any] = {
            "@timestamp": timestamp,
            "level": record.levelname,
            "message": record.getMessage(),
            "service.name": self._service_name,
            "service.version": self._service_version,
            "service.environment": self._service_environment,
            "logger": record.name,
            "correlationId": get_correlation_id(),
        }

        error_type = getattr(record, "error_type", None)
        if error_type is not None:
            payload["error.type"] = error_type
            payload["error.message"] = getattr(record, "error_message", "")

        return json.dumps(payload, default=str)


def configure_logging(
    service_name: str, service_version: str, service_environment: str
) -> logging.Logger:
    """Configure and return the application's JSON logger.

    Args:
        service_name: Emitted as ``service.name``.
        service_version: Emitted as ``service.version``.
        service_environment: Emitted as ``service.environment``.

    Returns:
        The configured application logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonLogFormatter(service_name, service_version, service_environment)
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
