"""Athena-backed :class:`GoldAnalyticsRepository` using boto3.

Serves the six analytical ``gold_<key>`` tables through one adapter, reusing the
shared :class:`AthenaQueryRunner` for execution and the shared validators as the
SQL-injection control (boto3 Athena has no bind parameters). The table key is
resolved against :data:`ANALYTICS_TABLES`, the ``fecha_dato`` partition against a
regex, the sort column against the table's allow-list, and each filter name and
value against the table's filter allow-list and a conservative literal pattern.
"""

from __future__ import annotations

from typing import Any, Optional

from app.adapters.driven.athena.athena_query_runner import (
    MAX_POLL_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    AthenaQueryRunner,
    validate_fecha_dato,
    validate_filter_value,
    validate_positive,
)
from app.domain.entities import ANALYTICS_TABLES, AnalyticsTable, GoldRow, GoldTablePage
from app.domain.errors import InvalidQueryError
from app.use_cases.ports import GoldAnalyticsRepository

DEFAULT_TABLE_PREFIX = "gold_"


class AthenaGoldAnalyticsRepository(GoldAnalyticsRepository):
    """Reads the analytical ``gold_<key>`` tables from Athena via boto3."""

    def __init__(
        self,
        athena_client: Any,
        database: str,
        workgroup: str,
        output_location: str,
        table_prefix: str = DEFAULT_TABLE_PREFIX,
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
        self._table_prefix = table_prefix

    def list_by_month(
        self,
        table_key: str,
        fecha_dato: str,
        page: int,
        size: int,
        sort: Optional[str] = None,
        filters: Optional[dict[str, str]] = None,
    ) -> GoldTablePage:
        """Return a paginated page of rows for one table and month.

        Pagination uses a separate ``COUNT(*)`` plus a ``LIMIT/OFFSET`` query,
        matching the ``gold_train`` month endpoint (OFFSET before LIMIT, which
        Athena/Trino requires).
        """
        table = self._resolve_table(table_key)
        safe_date = validate_fecha_dato(fecha_dato)
        safe_page = validate_positive(page, "page")
        safe_size = validate_positive(size, "size")
        order_clause = self._build_order_clause(table, sort)
        filter_clause = self._build_filter_clause(table, filters or {})
        where_clause = f"WHERE fecha_dato = '{safe_date}'{filter_clause}"
        offset = (safe_page - 1) * safe_size

        total = self._count_for_month(table, where_clause)
        query = (
            f"SELECT * FROM {self._qualified_table(table)} "
            f"{where_clause}{order_clause} "
            f"OFFSET {offset} LIMIT {safe_size}"
        )
        rows = self._runner.run_query(query)
        items = [self._to_row(table, row) for row in rows]
        return GoldTablePage(
            items=items, page=safe_page, size=safe_size, total=total
        )

    # --- internals ---------------------------------------------------------

    @staticmethod
    def _resolve_table(table_key: str) -> AnalyticsTable:
        table = ANALYTICS_TABLES.get(table_key)
        if table is None:
            raise InvalidQueryError(f"Unknown analytics table: {table_key}")
        return table

    def _qualified_table(self, table: AnalyticsTable) -> str:
        return f'"{self._database}"."{self._table_prefix}{table.key}"'

    def _count_for_month(self, table: AnalyticsTable, where_clause: str) -> int:
        query = (
            f"SELECT COUNT(*) AS total FROM {self._qualified_table(table)} "
            f"{where_clause}"
        )
        rows = self._runner.run_query(query)
        if not rows:
            return 0
        raw_total = rows[0].get("total")
        return int(raw_total) if raw_total not in (None, "") else 0

    @staticmethod
    def _build_order_clause(table: AnalyticsTable, sort: Optional[str]) -> str:
        """Return a safe ORDER BY clause, whitelisting the sort column."""
        if sort is None:
            return ""
        if sort not in table.sortable_columns:
            raise InvalidQueryError(f"Unknown sort column: {sort}")
        return f" ORDER BY {sort}"

    @staticmethod
    def _build_filter_clause(
        table: AnalyticsTable, filters: dict[str, str]
    ) -> str:
        """Return safe ``AND col = 'value'`` clauses for allowed filters.

        Both the filter name (against the table allow-list) and the value
        (against the literal pattern) are validated; this is the injection
        control for equality filters.
        """
        clauses = ""
        for column_name, value in filters.items():
            if column_name not in table.filter_columns:
                raise InvalidQueryError(f"Unknown filter column: {column_name}")
            safe_value = validate_filter_value(value, column_name)
            clauses += f" AND {column_name} = '{safe_value}'"
        return clauses

    @staticmethod
    def _to_row(table: AnalyticsTable, row: dict[str, Any]) -> GoldRow:
        """Map an Athena row into a :class:`GoldRow`, preserving nulls."""
        values = {name: row.get(name) for name in table.columns}
        return GoldRow(fecha_dato=row.get("fecha_dato"), values=values)
