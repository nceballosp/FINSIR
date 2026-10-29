"""Production auth path tests: RS256 tokens verified against a JWKS key.

These exercise the production branch of :class:`JwtValidator` (RS256 +
``PyJWKClient``), which the dev-mode HS256 tests never reach. No network call
is made: the signing key the JWKS client would fetch is injected directly, and
the ``cryptography`` backend performs the real RSA signature verification.
"""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.adapters.driving.http.auth import AuthError, JwtValidator
from app.config import Settings

AUDIENCE = "finsir-clients"
ISSUER = "finsir-prod"
REQUIRED_SCOPE = "silver:read"
JWKS_URL = "https://auth.example.com/.well-known/jwks.json"


@pytest.fixture
def rsa_key_pair() -> tuple[object, str]:
    """Return an RSA private key and its PEM public key for RS256 signing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, public_pem


@pytest.fixture
def prod_settings() -> Settings:
    """Settings in production auth mode (RS256 via JWKS)."""
    return Settings(
        ATHENA_DATABASE="finsir",
        ATHENA_WORKGROUP="finsir",
        ATHENA_OUTPUT="s3://finsir-bucket/athena-results/",
        IS_AUTH_DEV_MODE=False,
        AUTH_JWKS_URL=JWKS_URL,
        AUTH_AUDIENCE=AUDIENCE,
        AUTH_ISSUER=ISSUER,
        AUTH_REQUIRED_SCOPE=REQUIRED_SCOPE,
        _env_file=None,
    )


def _sign_rs256(private_key: object, scope: str = REQUIRED_SCOPE) -> str:
    return jwt.encode(
        {"sub": "tester", "scope": scope, "aud": AUDIENCE, "iss": ISSUER},
        private_key,
        algorithm="RS256",
    )


def _inject_signing_key(
    monkeypatch: pytest.MonkeyPatch, validator: JwtValidator, public_pem: str
) -> None:
    """Make the validator's JWKS client return ``public_pem`` without network."""
    monkeypatch.setattr(
        validator._jwks_client,
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=public_pem),
    )


def test_rs256_token_is_accepted(prod_settings, rsa_key_pair, monkeypatch):
    private_key, public_pem = rsa_key_pair
    validator = JwtValidator(prod_settings)
    _inject_signing_key(monkeypatch, validator, public_pem)

    claims = validator.validate(_sign_rs256(private_key))

    assert claims["sub"] == "tester"
    assert claims["iss"] == ISSUER


def test_rs256_token_with_wrong_key_is_rejected(prod_settings, monkeypatch):
    signing_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_public_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    validator = JwtValidator(prod_settings)
    _inject_signing_key(monkeypatch, validator, other_public_pem)

    with pytest.raises(AuthError) as excinfo:
        validator.validate(_sign_rs256(signing_private))

    assert excinfo.value.status_code == 401


def test_rs256_token_without_scope_is_forbidden(
    prod_settings, rsa_key_pair, monkeypatch
):
    private_key, public_pem = rsa_key_pair
    validator = JwtValidator(prod_settings)
    _inject_signing_key(monkeypatch, validator, public_pem)

    with pytest.raises(AuthError) as excinfo:
        validator.validate(_sign_rs256(private_key, scope="other:scope"))

    assert excinfo.value.status_code == 403


def test_prod_mode_without_jwks_rejects_token(monkeypatch):
    settings = Settings(
        ATHENA_DATABASE="finsir",
        ATHENA_WORKGROUP="finsir",
        ATHENA_OUTPUT="s3://finsir-bucket/athena-results/",
        IS_AUTH_DEV_MODE=False,
        AUTH_JWKS_URL=JWKS_URL,
        AUTH_AUDIENCE=AUDIENCE,
        AUTH_ISSUER=ISSUER,
        _env_file=None,
    )
    validator = JwtValidator(settings)
    validator._jwks_client = None

    with pytest.raises(AuthError) as excinfo:
        validator.validate("any.token.value")

    assert excinfo.value.status_code == 401
