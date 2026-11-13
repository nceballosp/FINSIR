"""Athena-backed :class:`GoldTrainRepository` using boto3.

Isolation: all boto3/Athena execution is delegated to
:class:`AthenaQueryRunner`; this adapter only builds the ``gold_train`` SQL and
maps rows to :class:`ClientRecord`. Infrastructure failures surface as
:class:`RepositoryError` and invalid inputs as :class:`InvalidQueryError`, so
the use cases never see botocore types.

SQL-injection defense: the boto3 Athena API has no bind-parameter support for
ad-hoc queries, so strict typed validation is the control. ``ncodpers`` must be
an integer and ``fecha_dato`` must match ``YYYY-MM-DD``; the sort column is
whitelisted against the known gold_train schema. Values are embedded only after
passing validation.

``fecha_dato`` is a string partition key, so it is compared to a string literal.
"""

from __future__ import annotations

from typing import Any, Optional

from app.adapters.driven.athena.athena_query_runner import (
    MAX_POLL_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    AthenaQueryRunner,
    validate_fecha_dato,
    validate_positive,
)
from app.domain.entities import GOLD_TRAIN_COLUMN_NAMES, ClientRecord, MonthPage
from app.domain.errors import InvalidQueryError
from app.use_cases.ports import GoldTrainRepository

_SORTABLE_COLUMNS = frozenset(GOLD_TRAIN_COLUMN_NAMES)


class AthenaGoldTrainRepository(GoldTrainRepository):
    """Reads ``gold_train`` from Athena via boto3."""

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
        self._runner = AthenaQueryRunner(
            athena_client=athena_client,
            database=database,
            workgroup=workgroup,
            output_location=output_location,
            poll_interval_seconds=poll_interval_seconds,
            max_poll_attempts=max_poll_attempts,
        )
        self._database = database
        self._table = table

    def get_client_records(self, ncodpers: int) -> list[ClientRecord]:
        """Return all gold_train records for a client, ordered by month."""
        safe_id = self._validate_ncodpers(ncodpers)
        query = (
            f"SELECT * FROM {self._qualified_table} "
            f"WHERE ncodpers = {safe_id} ORDER BY fecha_dato"
        )
        rows = self._runner.run_query(query)
        return [self._to_record(row) for row in rows]

    def list_by_month(
        self,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
    ) -> MonthPage:
        """Return a paginated page of records for a single month.

        Pagination uses a separate ``COUNT(*)`` plus a ``LIMIT/OFFSET`` query.
        Accepted trade-offs for the batch-rebuilt gold table:
        - ``total`` and the page come from two queries, so they can disagree
          while the gold job is rewriting the table. Outside a job run this
          window is absent.
        - ``OFFSET`` re-scans from the start on deep pages. Fine at the current
          per-month scale; revisit (e.g. keyset pagination) if month listings
          grow large or are requested frequently.
        """
        safe_date = validate_fecha_dato(fecha_dato)
        safe_page = validate_positive(page, "page")
        safe_size = validate_positive(size, "size")
        order_clause = self._build_order_clause(sort)
        offset = (safe_page - 1) * safe_size

        total = self._count_for_month(safe_date)
        # Athena (Trino) requires OFFSET before LIMIT; "LIMIT n OFFSET m" is a
        # syntax error there.
        query = (
            f"SELECT * FROM {self._qualified_table} "
            f"WHERE fecha_dato = '{safe_date}'{order_clause} "
            f"OFFSET {offset} LIMIT {safe_size}"
        )
        rows = self._runner.run_query(query)
        items = [self._to_record(row) for row in rows]
        return MonthPage(items=items, page=safe_page, size=safe_size, total=total)

    # --- internals ---------------------------------------------------------

    @property
    def _qualified_table(self) -> str:
        return f'"{self._database}"."{self._table}"'

    def _count_for_month(self, fecha_dato: str) -> int:
        query = (
            f"SELECT COUNT(*) AS total FROM {self._qualified_table} "
            f"WHERE fecha_dato = '{fecha_dato}'"
        )
        rows = self._runner.run_query(query)
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
    def _build_order_clause(sort: Optional[str]) -> str:
        """Return a safe ORDER BY clause, whitelisting the sort column."""
        if sort is None:
            return ""
        if sort not in _SORTABLE_COLUMNS:
            raise InvalidQueryError(f"Unknown sort column: {sort}")
        return f" ORDER BY {sort}"

    @staticmethod
    def _to_record(row: dict[str, Any]) -> ClientRecord:
        """Map an Athena row into a :class:`ClientRecord`, preserving nulls."""
        raw_id = row.get("ncodpers")
        ncodpers = int(raw_id) if raw_id not in (None, "") else None
        values = {
            name: row.get(name)
            for name in GOLD_TRAIN_COLUMN_NAMES
            if name not in ("ncodpers", "fecha_dato")
        }
        return ClientRecord(
            ncodpers=ncodpers,
            fecha_dato=row.get("fecha_dato"),
            values=values,
        )
