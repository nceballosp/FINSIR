"""FastAPI application factory.

Builds the app from the outside in: configures logging, installs the
correlation middleware and the single global exception handler, wires the DI
container and the JWT validator onto ``app.state``, and mounts the routers.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from app.adapters.driving.http.auth import JwtValidator
from app.adapters.driving.http.correlation import CorrelationIdMiddleware
from app.adapters.driving.http.exception_handler import register_exception_handlers
from app.adapters.driving.http.logging_config import configure_logging
from app.adapters.driving.http.routers import clients, health
from app.config import Settings
from app.container import Container, build_container


def create_app(
    settings: Optional[Settings] = None,
    container: Optional[Container] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings. Loaded from the environment if omitted.
        container: Pre-wired DI container. Built from ``settings`` if omitted
            (production path); tests pass a container with a fake repository.

    Returns:
        The configured FastAPI application.
    """
    resolved_settings = settings if settings is not None else Settings()
    resolved_container = (
        container if container is not None else build_container(resolved_settings)
    )

    logger = configure_logging(
        resolved_settings.service_name,
        resolved_settings.service_version,
        resolved_settings.service_environment,
    )

    app = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.service_version,
    )
    app.state.settings = resolved_settings
    app.state.container = resolved_container
    app.state.jwt_validator = JwtValidator(resolved_settings)

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app, logger)

    app.include_router(health.router)
    app.include_router(clients.router)
    return app
