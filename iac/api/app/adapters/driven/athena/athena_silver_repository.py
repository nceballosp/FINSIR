"""Athena-backed :class:`SilverRepository` using boto3.

Isolation: all boto3/Athena details live here. Infrastructure failures are
translated into :class:`RepositoryError` and invalid inputs into
:class:`InvalidQueryError` so the use cases never see botocore types.

SQL-injection defense: the boto3 Athena API has no bind-parameter support for
ad-hoc queries, so strict typed validation is the control. ``ncodpers`` must be
an integer and ``fecha_dato`` must match ``YYYY-MM-DD``; the sort column is
whitelisted against the known silver schema. Values are embedded only after
passing validation.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from botocore.exceptions import BotoCoreError, ClientError

from app.domain.entities import SILVER_COLUMN_NAMES, ClientRecord, MonthPage
from app.domain.errors import InvalidQueryError, RepositoryError
from app.use_cases.ports import SilverRepository

FECHA_DATO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TERMINAL_FAILURE_STATES = frozenset({"FAILED", "CANCELLED"})
SUCCEEDED_STATE = "SUCCEEDED"
POLL_INTERVAL_SECONDS = 0.5
MAX_POLL_ATTEMPTS = 120
_SORTABLE_COLUMNS = frozenset(SILVER_COLUMN_NAMES)


class AthenaSilverRepository(SilverRepository):
    """Reads ``silver_train`` from Athena via boto3."""

    def __init__(
        self,
        athena_client: Any,
        database: str,
        workgroup: str,
        output_location: str,
        table: str,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        max_poll_attempts: int = MAX_POLL_ATTEMPTS,
    ) -> None:
        self._client = athena_client
        self._database = database
        self._workgroup = workgroup
        self._output_location = output_location
        self._table = table
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts

    def get_client_records(self, ncodpers: int) -> list[ClientRecord]:
        """Return all silver records for a client, ordered by month."""
        safe_id = self._validate_ncodpers(ncodpers)
        query = (
            f"SELECT * FROM {self._qualified_table} "
            f"WHERE ncodpers = {safe_id} ORDER BY fecha_dato"
        )
        rows = self._run_query(query)
        return [self._to_record(row) for row in rows]

    def get_client_latest(self, ncodpers: int) -> Optional[ClientRecord]:
        """Return the client's most recent record, or ``None`` if none."""
        safe_id = self._validate_ncodpers(ncodpers)
        query = (
            f"SELECT * FROM {self._qualified_table} "
            f"WHERE ncodpers = {safe_id} ORDER BY fecha_dato DESC LIMIT 1"
        )
        rows = self._run_query(query)
        if not rows:
            return None
        return self._to_record(rows[0])

    def list_by_month(
        self,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
    ) -> MonthPage:
        """Return a paginated page of records for a single month.

        Pagination uses a separate ``COUNT(*)`` plus a ``LIMIT/OFFSET`` query.
        Accepted trade-offs for the append-mostly silver table:
        - ``total`` and the page come from two queries, so they can disagree
          under concurrent writes. The silver table is batch-appended, so this
          window is effectively absent in practice.
        - ``OFFSET`` re-scans from the start on deep pages. Fine at the current
          per-month scale; revisit (e.g. keyset pagination) if month listings
          grow large or are requested frequently.
        """
        safe_date = self._validate_fecha_dato(fecha_dato)
        safe_page = self._validate_positive(page, "page")
        safe_size = self._validate_positive(size, "size")
        order_clause = self._build_order_clause(sort)
        offset = (safe_page - 1) * safe_size

        total = self._count_for_month(safe_date)
        query = (
            f"SELECT * FROM {self._qualified_table} "
            f"WHERE fecha_dato = DATE '{safe_date}'{order_clause} "
            f"LIMIT {safe_size} OFFSET {offset}"
        )
        rows = self._run_query(query)
        items = [self._to_record(row) for row in rows]
        return MonthPage(items=items, page=safe_page, size=safe_size, total=total)

    # --- internals ---------------------------------------------------------

    @property
    def _qualified_table(self) -> str:
        return f'"{self._database}"."{self._table}"'

    def _count_for_month(self, fecha_dato: str) -> int:
        query = (
            f"SELECT COUNT(*) AS total FROM {self._qualified_table} "
            f"WHERE fecha_dato = DATE '{fecha_dato}'"
        )
        rows = self._run_query(query)
        if not rows:
            return 0
        raw_total = rows[0].get("total")
        return int(raw_total) if raw_total not in (None, "") else 0

    @staticmethod
    def _validate_ncodpers(ncodpers: int) -> int:
        """Validate the client id is a non-negative integer (injection guard)."""
        if isinstance(ncodpers, bool) or not isinstance(ncodpers, int):
            raise InvalidQueryError("ncodpers must be an integer")
        if ncodpers < 0:
            raise InvalidQueryError("ncodpers must be non-negative")
        return ncodpers

    @staticmethod
    def _validate_fecha_dato(fecha_dato: str) -> str:
        """Validate the month matches ``YYYY-MM-DD`` (injection guard)."""
        if not isinstance(fecha_dato, str) or not FECHA_DATO_PATTERN.match(fecha_dato):
            raise InvalidQueryError("fecha_dato must match YYYY-MM-DD")
        return fecha_dato

    @staticmethod
    def _validate_positive(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise InvalidQueryError(f"{field_name} must be a positive integer")
        return value

    @staticmethod
    def _build_order_clause(sort: Optional[str]) -> str:
        """Return a safe ORDER BY clause, whitelisting the sort column."""
        if sort is None:
            return ""
        if sort not in _SORTABLE_COLUMNS:
            raise InvalidQueryError(f"Unknown sort column: {sort}")
        return f" ORDER BY {sort}"

    def _run_query(self, query: str) -> list[dict[str, Any]]:
        """Execute a query and return its rows as column-keyed dicts."""
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

    @staticmethod
    def _to_record(row: dict[str, Any]) -> ClientRecord:
        """Map an Athena row into a :class:`ClientRecord`, preserving nulls."""
        raw_id = row.get("ncodpers")
        ncodpers = int(raw_id) if raw_id not in (None, "") else None
        values = {
            name: row.get(name)
            for name in SILVER_COLUMN_NAMES
            if name not in ("ncodpers", "fecha_dato")
        }
        return ClientRecord(
            ncodpers=ncodpers,
            fecha_dato=row.get("fecha_dato"),
            values=values,
        )
