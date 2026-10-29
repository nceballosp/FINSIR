"""Typed domain errors for the FINSIR API.

Infrastructure failures are translated into these errors in the adapter layer;
the global HTTP exception handler maps them to status codes. Using specific,
typed errors (never generic exceptions) keeps error handling explicit.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all FINSIR domain errors."""


class ClientNotFoundError(DomainError):
    """Raised when a client (``ncodpers``) has no silver records.

    Attributes:
        ncodpers: The client identifier that was not found.
    """

    def __init__(self, ncodpers: int) -> None:
        self.ncodpers = ncodpers
        super().__init__(f"No silver records for client {ncodpers}")


class InvalidQueryError(DomainError):
    """Raised when a query parameter fails boundary validation.

    Used as the SQL-injection guard: identifiers and dates are strictly
    validated before they reach Athena, and a violation raises this error.
    """


class RepositoryError(DomainError):
    """Raised when the persistence adapter fails to serve a request.

    Wraps infrastructure failures (botocore ``ClientError``, failed Athena
    query executions) so the domain and use cases never see boto3 types.
    """
