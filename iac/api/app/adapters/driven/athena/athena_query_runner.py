"""Shared Athena query execution and input validators for the gold adapters.

Isolation: all boto3/Athena execution details live here so both the
``gold_train`` and the analytical gold adapters share one copy (DRY).
Infrastructure failures are translated into :class:`RepositoryError` and invalid
inputs into :class:`InvalidQueryError`, so the use cases never see botocore types.

SQL-injection defense: the boto3 Athena API has no bind-parameter support for
ad-hoc queries, so strict typed/allow-list validation is the control. Dates must
match ``YYYY-MM-DD``, numeric params must be positive ints, and literal filter
values must match a conservative pattern. Values are embedded only after
passing validation.
"""

from __future__ import annotations

import re
import time
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.domain.errors import InvalidQueryError, RepositoryError

FECHA_DATO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Conservative literal pattern for equality-filter values. Covers product codes
# (``ind_*_ult1``), segment labels (``02 - PARTICULARES``), bands (``000-050k``,
# ``65+``), single letters (``H`` / ``V``) and ``sin_productos``.
FILTER_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9 _\-+]{1,64}$")
TERMINAL_FAILURE_STATES = frozenset({"FAILED", "CANCELLED"})
SUCCEEDED_STATE = "SUCCEEDED"
POLL_INTERVAL_SECONDS = 0.5
MAX_POLL_ATTEMPTS = 120


def validate_fecha_dato(fecha_dato: str) -> str:
    """Validate the month matches ``YYYY-MM-DD`` (injection guard).

    Args:
        fecha_dato: The candidate month string.

    Returns:
        The validated value, unchanged.

    Raises:
        InvalidQueryError: If the value is not a well-formed date string.
    """
    if not isinstance(fecha_dato, str) or not FECHA_DATO_PATTERN.match(fecha_dato):
        raise InvalidQueryError("fecha_dato must match YYYY-MM-DD")
    return fecha_dato


def validate_positive(value: int, field_name: str) -> int:
    """Validate ``value`` is a positive integer (injection guard).

    Args:
        value: The candidate integer.
        field_name: Name used in the error message.

    Returns:
        The validated integer, unchanged.

    Raises:
        InvalidQueryError: If the value is not a positive integer.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidQueryError(f"{field_name} must be a positive integer")
    return value


def validate_filter_value(value: str, field_name: str) -> str:
    """Validate an equality-filter literal against a conservative pattern.

    Args:
        value: The candidate filter value.
        field_name: The column name, used in the error message.

    Returns:
        The validated value, unchanged.

    Raises:
        InvalidQueryError: If the value fails the literal pattern.
    """
    if not isinstance(value, str) or not FILTER_VALUE_PATTERN.match(value):
        raise InvalidQueryError(f"Invalid filter value for {field_name}")
    return value


class AthenaQueryRunner:
    """Runs an Athena query via boto3 and returns column-keyed result rows.

    Encapsulates start/poll/fetch plumbing shared by the gold adapters.
    """

    def __init__(
        self,
        athena_client: Any,
        database: str,
        workgroup: str,
        output_location: str,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        max_poll_attempts: int = MAX_POLL_ATTEMPTS,
    ) -> None:
        self._client = athena_client
        self._database = database
        self._workgroup = workgroup
        self._output_location = output_location
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts

    @property
    def database(self) -> str:
        """The Glue catalog database the runner targets."""
        return self._database

    def run_query(self, query: str) -> list[dict[str, Any]]:
        """Execute a query and return its rows as column-keyed dicts.

        Args:
            query: The fully-formed, already-validated SQL string.

        Returns:
            The result rows (excluding the header row).

        Raises:
            RepositoryError: On any boto3/Athena failure or non-success state.
        """
        try:
            execution_id = self._start(query)
            self._wait(execution_id)
            return self._fetch_rows(execution_id)
        except (ClientError, BotoCoreError) as error:
            raise RepositoryError("Athena request failed") from error

    def _start(self, query: str) -> str:
        response = self._client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self._database},
            WorkGroup=self._workgroup,
            ResultConfiguration={"OutputLocation": self._output_location},
        )
        return response["QueryExecutionId"]

    def _wait(self, execution_id: str) -> None:
        for _ in range(self._max_poll_attempts):
            response = self._client.get_query_execution(QueryExecutionId=execution_id)
            status = response["QueryExecution"]["Status"]
            state = status["State"]
            if state == SUCCEEDED_STATE:
                return
            if state in TERMINAL_FAILURE_STATES:
                reason = status.get("StateChangeReason", "unknown reason")
                raise RepositoryError(f"Athena query {state}: {reason}")
            time.sleep(self._poll_interval_seconds)
        raise RepositoryError("Athena query timed out")

    def _fetch_rows(self, execution_id: str) -> list[dict[str, Any]]:
        """Read result rows, mapping the header row to column names.

        The first row returned by ``get_query_results`` is the header; empty or
        absent cells become ``None`` so a missing datum is never fabricated.
        """
        result = self._client.get_query_results(QueryExecutionId=execution_id)
        result_set = result.get("ResultSet", {})
        raw_rows = result_set.get("Rows", [])
        if not raw_rows:
            return []

        header = [cell.get("VarCharValue") for cell in raw_rows[0].get("Data", [])]
        rows: list[dict[str, Any]] = []
        for raw_row in raw_rows[1:]:
            cells = raw_row.get("Data", [])
            row: dict[str, Any] = {}
            for index, column_name in enumerate(header):
                value = cells[index].get("VarCharValue") if index < len(cells) else None
                row[column_name] = value if value not in ("", None) else None
            rows.append(row)
        return rows
