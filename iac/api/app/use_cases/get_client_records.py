"""Use case: fetch all silver records for a client."""

from __future__ import annotations

from app.domain.entities import ClientRecord
from app.domain.errors import ClientNotFoundError
from app.use_cases.ports import SilverRepository


class GetClientRecords:
    """Return every silver record belonging to a client."""

    def __init__(self, repository: SilverRepository) -> None:
        self._repository = repository

    def execute(self, ncodpers: int) -> list[ClientRecord]:
        """Return the client's records.

        Args:
            ncodpers: The client identifier.

        Returns:
            The client's non-empty list of records.

        Raises:
            ClientNotFoundError: If the client has no records.
            InvalidQueryError: If ``ncodpers`` is invalid.
            RepositoryError: On an infrastructure failure.
        """
        records = self._repository.get_client_records(ncodpers)
        if not records:
            raise ClientNotFoundError(ncodpers)
        return records
