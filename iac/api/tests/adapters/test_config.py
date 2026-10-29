"""Settings validation tests."""

from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_fail_fast_when_athena_missing():
    with pytest.raises(ValueError):
        Settings(IS_AUTH_DEV_MODE=True, AUTH_DEV_SECRET="x", _env_file=None)


def test_settings_dev_mode_requires_dev_secret():
    with pytest.raises(ValueError):
        Settings(
            ATHENA_DATABASE="finsir",
            ATHENA_WORKGROUP="finsir",
            ATHENA_OUTPUT="s3://b/r/",
            IS_AUTH_DEV_MODE=True,
            _env_file=None,
        )


def test_settings_prod_mode_requires_jwks_audience_issuer():
    with pytest.raises(ValueError):
        Settings(
            ATHENA_DATABASE="finsir",
            ATHENA_WORKGROUP="finsir",
            ATHENA_OUTPUT="s3://b/r/",
            IS_AUTH_DEV_MODE=False,
            _env_file=None,
        )


def test_settings_valid_dev_mode():
    settings = Settings(
        ATHENA_DATABASE="finsir",
        ATHENA_WORKGROUP="finsir",
        ATHENA_OUTPUT="s3://b/r/",
        IS_AUTH_DEV_MODE=True,
        AUTH_DEV_SECRET="secret",
        _env_file=None,
    )
    assert settings.athena_table == "silver_train"
    assert settings.aws_region == "us-east-1"
