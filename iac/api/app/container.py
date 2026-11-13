"""Dependency-injection container wiring adapters into use cases.

Wiring happens from the outside in: the Athena adapters (or any port
implementation) are constructed here and injected into the use cases. Tests
build a container with fake repositories, keeping boto3 out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import Settings
from app.use_cases.get_client_records import GetClientRecords
from app.use_cases.list_analytics_month import ListAnalyticsMonth
from app.use_cases.list_month import ListMonth
from app.use_cases.ports import GoldAnalyticsRepository, GoldTrainRepository


@dataclass(frozen=True)
class Container:
    """Holds the wired use cases consumed by the HTTP routers."""

    get_client_records: GetClientRecords
    list_month: ListMonth
    list_analytics_month: ListAnalyticsMonth


def build_container_from_repository(
    repository: GoldTrainRepository,
    analytics_repository: Optional[GoldAnalyticsRepository] = None,
) -> Container:
    """Wire the use cases around the given repository implementations.

    Args:
        repository: Any :class:`GoldTrainRepository` (Athena in production, a
            fake in tests).
        analytics_repository: Any :class:`GoldAnalyticsRepository`. When omitted
            a :class:`_NullGoldAnalyticsRepository` is wired so legacy callers
            that only provide the gold_train repository still build a container;
            calling an analytics endpoint then raises instead of touching AWS.

    Returns:
        A fully wired :class:`Container`.
    """
    resolved_analytics = (
        analytics_repository
        if analytics_repository is not None
        else _NullGoldAnalyticsRepository()
    )
    return Container(
        get_client_records=GetClientRecords(repository),
        list_month=ListMonth(repository),
        list_analytics_month=ListAnalyticsMonth(resolved_analytics),
    )


def build_container(settings: Settings) -> Container:
    """Wire the production container backed by the Athena adapters.

    boto3 is imported lazily so importing the container in tests (which inject
    fake repositories) does not require AWS libraries at module load time.

    Args:
        settings: Application settings providing Athena configuration.

    Returns:
        A production :class:`Container`.
    """
    import boto3  # Lazy import: keeps boto3 off the test import path.

    from app.adapters.driven.athena.athena_gold_analytics_repository import (
        AthenaGoldAnalyticsRepository,
    )
    from app.adapters.driven.athena.athena_gold_train_repository import (
        AthenaGoldTrainRepository,
    )

    athena_client = boto3.client("athena", region_name=settings.aws_region)
    repository = AthenaGoldTrainRepository(
        athena_client=athena_client,
        database=settings.athena_database,
        workgroup=settings.athena_workgroup,
        output_location=settings.athena_output,
        table=settings.athena_table,
    )
    analytics_repository = AthenaGoldAnalyticsRepository(
        athena_client=athena_client,
        database=settings.athena_database,
        workgroup=settings.athena_workgroup,
        output_location=settings.athena_output,
        table_prefix=settings.athena_analytics_table_prefix,
    )
    return build_container_from_repository(repository, analytics_repository)


class _NullGoldAnalyticsRepository(GoldAnalyticsRepository):
    """Fallback analytics repository used when none is wired.

    Keeps ``build_container_from_repository`` usable with only a gold_train
    repository (e.g. legacy callers); invoking it fails loudly rather than
    silently returning data or reaching AWS.
    """

    def list_by_month(self, table_key, fecha_dato, page, size, sort=None, filters=None):
        raise RuntimeError("No analytics repository configured")
