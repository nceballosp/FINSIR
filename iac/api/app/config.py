"""Application configuration loaded from environment variables.

No secret is ever hardcoded: the signing material, issuer, and audience come
from the environment. ``Settings`` fails fast when a required production value
is missing while development auth mode is disabled.
"""

from __future__ import annotations

from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_SILVER_TABLE = "silver_train"
DEFAULT_SERVICE_NAME = "finsir-service"
DEFAULT_SERVICE_VERSION = "0.1.0"
DEFAULT_SERVICE_ENVIRONMENT = "local"


class Settings(BaseSettings):
    """Typed settings read from UPPER_SNAKE_CASE environment variables.

    Athena:
        athena_database: Glue catalog database holding the silver tables.
        athena_workgroup: Athena workgroup used to run queries.
        athena_output: S3 URI where Athena writes query results.
        athena_table: Silver table name (defaults to ``silver_train``).
        aws_region: AWS region for the Athena/boto3 clients.

    Auth (JWT validated inside FastAPI, never via API Gateway):
        auth_issuer: Expected token issuer (``iss`` claim).
        auth_audience: Expected token audience (``aud`` claim).
        auth_jwks_url: JWKS endpoint for RS256 verification in production.
        auth_required_scope: Scope required to call the data endpoints.
        is_auth_dev_mode: Enables local HS256 validation with a dev secret.
        auth_dev_secret: HS256 secret used only when dev mode is on.

    Service metadata (for structured logs):
        service_name / service_version / service_environment.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    athena_database: str = ""
    athena_workgroup: str = ""
    athena_output: str = ""
    athena_table: str = DEFAULT_SILVER_TABLE
    aws_region: str = DEFAULT_AWS_REGION

    auth_issuer: Optional[str] = None
    auth_audience: Optional[str] = None
    auth_jwks_url: Optional[str] = None
    auth_required_scope: Optional[str] = None
    is_auth_dev_mode: bool = False
    auth_dev_secret: Optional[str] = None

    service_name: str = DEFAULT_SERVICE_NAME
    service_version: str = DEFAULT_SERVICE_VERSION
    service_environment: str = DEFAULT_SERVICE_ENVIRONMENT

    @model_validator(mode="after")
    def _check_required(self) -> "Settings":
        """Fail fast when required values for the active mode are missing."""
        missing: list[str] = []
        if not self.athena_database:
            missing.append("ATHENA_DATABASE")
        if not self.athena_workgroup:
            missing.append("ATHENA_WORKGROUP")
        if not self.athena_output:
            missing.append("ATHENA_OUTPUT")

        if self.is_auth_dev_mode:
            if not self.auth_dev_secret:
                missing.append("AUTH_DEV_SECRET")
        else:
            if not self.auth_jwks_url:
                missing.append("AUTH_JWKS_URL")
            if not self.auth_audience:
                missing.append("AUTH_AUDIENCE")
            if not self.auth_issuer:
                missing.append("AUTH_ISSUER")

        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        return self
