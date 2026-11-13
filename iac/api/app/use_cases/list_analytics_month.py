"""Use case: list and paginate an analytical gold table for a single month."""

from __future__ import annotations

from typing import Optional

from app.domain.entities import GoldTablePage
from app.use_cases.ports import GoldAnalyticsRepository


class ListAnalyticsMonth:
    """Return a paginated page of analytical rows for a table and month."""

    def __init__(self, repository: GoldAnalyticsRepository) -> None:
        self._repository = repository

    def execute(
        self,
        table_key: str,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
        filters: Optional[dict[str, str]] = None,
    ) -> GoldTablePage:
        """Return a page of rows for ``table_key`` and ``fecha_dato``.

        Input shape (page bounds, date format, allow-listed sort/filters) is
        validated at the HTTP and repository boundaries; this use case
        orchestrates the retrieval.

        Args:
            table_key: The analytical table key (e.g. ``product_monthly_kpis``).
            fecha_dato: The month partition in ``YYYY-MM-DD`` form.
            page: 1-based page number.
            size: Page size.
            sort: Optional column to sort by (ascending).
            filters: Optional equality filters keyed by column name.

        Returns:
            The requested page.

        Raises:
            InvalidQueryError: If the table key or any parameter fails
                validation.
            RepositoryError: On an infrastructure failure.
        """
        return self._repository.list_by_month(
            table_key, fecha_dato, page, size, sort, filters
        )
