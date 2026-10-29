"""Use case: fetch a client's most recent silver record."""

from __future__ import annotations

from app.domain.entities import ClientRecord
from app.domain.errors import ClientNotFoundError
from app.use_cases.ports import SilverRepository


class GetClientLatest:
    """Return the most recent silver record for a client."""

    def __init__(self, repository: SilverRepository) -> None:
        self._repository = repository

    def execute(self, ncodpers: int) -> ClientRecord:
        """Return the client's latest record.

        Args:
            ncodpers: The client identifier.

        Returns:
            The client's most recent record.

        Raises:
            ClientNotFoundError: If the client has no records.
            InvalidQueryError: If ``ncodpers`` is invalid.
            RepositoryError: On an infrastructure failure.
        """
        record = self._repository.get_client_latest(ncodpers)
        if record is None:
            raise ClientNotFoundError(ncodpers)
        return record
