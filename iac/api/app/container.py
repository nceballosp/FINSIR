"""Dependency-injection container wiring adapters into use cases.

Wiring happens from the outside in: the Athena adapter (or any
:class:`SilverRepository`) is constructed here and injected into the three use
cases. Tests build a container with a fake repository, keeping boto3 out.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.use_cases.get_client_latest import GetClientLatest
from app.use_cases.get_client_records import GetClientRecords
from app.use_cases.list_month import ListMonth
from app.use_cases.ports import SilverRepository


@dataclass(frozen=True)
class Container:
    """Holds the wired use cases consumed by the HTTP routers."""

    get_client_records: GetClientRecords
    get_client_latest: GetClientLatest
    list_month: ListMonth


def build_container_from_repository(repository: SilverRepository) -> Container:
    """Wire the use cases around a given repository implementation.

    Args:
        repository: Any :class:`SilverRepository` (Athena in production, a fake
            in tests).

    Returns:
        A fully wired :class:`Container`.
    """
    return Container(
        get_client_records=GetClientRecords(repository),
        get_client_latest=GetClientLatest(repository),
        list_month=ListMonth(repository),
    )


def build_container(settings: Settings) -> Container:
    """Wire the production container backed by the Athena adapter.

    boto3 is imported lazily so importing the container in tests (which inject a
    fake repository) does not require AWS libraries at module load time.

    Args:
        settings: Application settings providing Athena configuration.

    Returns:
        A production :class:`Container`.
    """
    import boto3  # Lazy import: keeps boto3 off the test import path.

    from app.adapters.driven.athena.athena_silver_repository import (
        AthenaSilverRepository,
    )

    athena_client = boto3.client("athena", region_name=settings.aws_region)
    repository = AthenaSilverRepository(
        athena_client=athena_client,
        database=settings.athena_database,
        workgroup=settings.athena_workgroup,
        output_location=settings.athena_output,
        table=settings.athena_table,
    )
    return build_container_from_repository(repository)
