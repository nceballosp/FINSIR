"""Bearer-JWT authentication validated inside FastAPI (no API Gateway).

A FastAPI dependency decodes and verifies the token:
- Development mode: HS256 with a secret supplied via ``AUTH_DEV_SECRET``.
- Production mode: RS256 with keys fetched from ``AUTH_JWKS_URL``, verifying
  the expected audience and issuer.

Missing or invalid tokens raise 401; insufficient scope raises 403. The token
is never logged. No secret is hardcoded.
"""

from __future__ import annotations

from typing import Optional

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

_DEV_ALGORITHM = "HS256"
_PROD_ALGORITHM = "RS256"
_SCOPE_CLAIM = "scope"

# auto_error=False so a missing token yields our typed 401, not FastAPI's 403.
_bearer_scheme = HTTPBearer(auto_error=False)


class AuthError(Exception):
    """Raised when authentication fails.

    Attributes:
        status_code: 401 (unauthenticated) or 403 (insufficient scope).
        code: Stable machine-readable error code.
        message: Human-readable, non-sensitive message.
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class JwtValidator:
    """Validates bearer JWTs according to the active settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_client: Optional[jwt.PyJWKClient] = None
        if not settings.is_auth_dev_mode and settings.auth_jwks_url:
            self._jwks_client = jwt.PyJWKClient(settings.auth_jwks_url)

    def validate(self, token: str) -> dict:
        """Decode and verify ``token``; return its claims.

        Raises:
            AuthError: 401 if the token is invalid/expired; 403 if the required
                scope is absent.
        """
        try:
            claims = self._decode(token)
        except jwt.PyJWTError as error:
            raise AuthError(401, "invalid_token", "Invalid or expired token") from error

        self._check_scope(claims)
        return claims

    def _decode(self, token: str) -> dict:
        if self._settings.is_auth_dev_mode:
            return jwt.decode(
                token,
                self._settings.auth_dev_secret,
                algorithms=[_DEV_ALGORITHM],
                audience=self._settings.auth_audience,
                issuer=self._settings.auth_issuer,
                options={
                    "verify_aud": self._settings.auth_audience is not None,
                    "verify_iss": self._settings.auth_issuer is not None,
                },
            )
        if self._jwks_client is None:
            raise AuthError(401, "invalid_token", "Token verification unavailable")
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[_PROD_ALGORITHM],
            audience=self._settings.auth_audience,
            issuer=self._settings.auth_issuer,
        )

    def _check_scope(self, claims: dict) -> None:
        required = self._settings.auth_required_scope
        if not required:
            return
        granted = claims.get(_SCOPE_CLAIM, "")
        scopes = granted.split() if isinstance(granted, str) else list(granted)
        if required not in scopes:
            raise AuthError(403, "insufficient_scope", "Insufficient scope")


def get_jwt_validator(request: Request) -> JwtValidator:
    """Return the request-scoped :class:`JwtValidator` from app state."""
    return request.app.state.jwt_validator


def require_authenticated(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    validator: JwtValidator = Depends(get_jwt_validator),
) -> dict:
    """FastAPI dependency enforcing a valid bearer token on a route.

    Returns:
        The validated token claims.

    Raises:
        AuthError: 401 when the bearer token is missing or invalid; 403 when
            the required scope is absent.
    """
    if credentials is None or not credentials.credentials:
        raise AuthError(401, "missing_token", "Missing bearer token")
    return validator.validate(credentials.credentials)
