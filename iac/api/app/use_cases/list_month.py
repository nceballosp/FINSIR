"""Use case: list and paginate silver records for a single month."""

from __future__ import annotations

from typing import Optional

from app.domain.entities import MonthPage
from app.use_cases.ports import SilverRepository


class ListMonth:
    """Return a paginated page of silver records for a given month."""

    def __init__(self, repository: SilverRepository) -> None:
        self._repository = repository

    def execute(
        self,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
    ) -> MonthPage:
        """Return a page of records for ``fecha_dato``.

        Input shape (page bounds, date format) is validated at the HTTP and
        repository boundaries; this use case orchestrates the retrieval.

        Args:
            fecha_dato: The month partition in ``YYYY-MM-DD`` form.
            page: 1-based page number.
            size: Page size.
            sort: Optional column to sort by (ascending).

        Returns:
            The requested page.

        Raises:
            InvalidQueryError: If any parameter fails validation.
            RepositoryError: On an infrastructure failure.
        """
        return self._repository.list_by_month(fecha_dato, page, size, sort)
