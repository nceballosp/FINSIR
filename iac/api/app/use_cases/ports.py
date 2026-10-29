"""Ports (interfaces) the use cases depend on.

Adapters implement these ports; the use cases depend only on the abstraction,
never on boto3 or Athena directly (dependency-inversion).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.entities import ClientRecord, MonthPage


class SilverRepository(ABC):
    """Read port over the ``silver_train`` dataset.

    Implementations translate infrastructure failures into
    :class:`app.domain.errors.RepositoryError` and invalid inputs into
    :class:`app.domain.errors.InvalidQueryError`.
    """

    @abstractmethod
    def get_client_records(self, ncodpers: int) -> list[ClientRecord]:
        """Return every silver record for a client, ordered by month.

        Args:
            ncodpers: The client identifier.

        Returns:
            The client's records (possibly empty).

        Raises:
            InvalidQueryError: If ``ncodpers`` is not a valid identifier.
            RepositoryError: On an infrastructure failure.
        """

    @abstractmethod
    def get_client_latest(self, ncodpers: int) -> Optional[ClientRecord]:
        """Return the client's most recent record, or ``None`` if none exist.

        Args:
            ncodpers: The client identifier.

        Raises:
            InvalidQueryError: If ``ncodpers`` is not a valid identifier.
            RepositoryError: On an infrastructure failure.
        """

    @abstractmethod
    def list_by_month(
        self,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
    ) -> MonthPage:
        """Return a paginated page of records for a single month.

        Args:
            fecha_dato: The month partition in ``YYYY-MM-DD`` form.
            page: 1-based page number.
            size: Page size.
            sort: Optional column name to sort by (ascending).

        Raises:
            InvalidQueryError: If any parameter fails validation.
            RepositoryError: On an infrastructure failure.
        """
