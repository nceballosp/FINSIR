"""Pure domain entities for the FINSIR gold layer.

These entities mirror the ``gold_train`` table schema produced by the data
platform's gold Glue job (``iac/data-platform/glue/gold_train.py``). They carry
no framework dependencies.

Business rule: a ``None`` value means the datum does not exist in the source.
The domain never fabricates defaults for a missing column.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Optional

PRODUCTS: tuple[str, ...] = (
    "ind_ahor_fin_ult1",
    "ind_aval_fin_ult1",
    "ind_cco_fin_ult1",
    "ind_cder_fin_ult1",
    "ind_cno_fin_ult1",
    "ind_ctju_fin_ult1",
    "ind_ctma_fin_ult1",
    "ind_ctop_fin_ult1",
    "ind_ctpp_fin_ult1",
    "ind_deco_fin_ult1",
    "ind_deme_fin_ult1",
    "ind_dela_fin_ult1",
    "ind_ecue_fin_ult1",
    "ind_fond_fin_ult1",
    "ind_hip_fin_ult1",
    "ind_plan_fin_ult1",
    "ind_pres_fin_ult1",
    "ind_reca_fin_ult1",
    "ind_tjcr_fin_ult1",
    "ind_valo_fin_ult1",
    "ind_viv_fin_ult1",
    "ind_nomina_ult1",
    "ind_nom_pens_ult1",
    "ind_recibo_ult1",
)
PROFILE_COLUMNS: tuple[str, ...] = (
    "ind_empleado",
    "pais_residencia",
    "sexo",
    "age",
    "antiguedad",
    "ind_nuevo",
    "indrel",
    "indrel_1mes",
    "tiprel_1mes",
    "indresi",
    "indext",
    "canal_entrada",
    "indfall",
    "cod_prov",
    "ind_actividad_cliente",
    "renta",
    "segmento",
)
LAGS: tuple[int, ...] = (1, 3, 6)

# The ``gold_train`` columns in schema order, ending with the partition key.
# Single source of truth for the Athena adapter (column mapping and the sort
# whitelist); must match ``gold_columns()`` in the gold Glue job.
GOLD_TRAIN_COLUMN_NAMES: tuple[str, ...] = (
    ("ncodpers", "month_of_year")
    + PROFILE_COLUMNS
    + PRODUCTS
    + tuple(f"{product}_lag{months}" for months in LAGS for product in PRODUCTS)
    + tuple(f"added_{product}" for product in PRODUCTS)
    + ("n_products", "n_products_added", "n_products_dropped", "has_previous_month")
    + tuple(f"label_next_{product}" for product in PRODUCTS)
    + ("label_next_n_added", "fecha_dato")
)


@dataclass(frozen=True)
class ClientRecord:
    """A single monthly ``gold_train`` row for one client (``ncodpers``).

    Every attribute is optional: a ``None`` reflects a missing value in the
    source data and must never be replaced with a fabricated default.

    Attributes:
        ncodpers: The client identifier (bigint in the gold schema).
        fecha_dato: The partition month in ``YYYY-MM-DD`` form.
        values: Remaining gold columns keyed by column name. Absent columns
            are simply not present; explicit ``None`` values are preserved.
    """

    ncodpers: Optional[int] = None
    fecha_dato: Optional[str] = None
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, column_name: str) -> Any:
        """Return the value of ``column_name`` or ``None`` when absent.

        Args:
            column_name: A gold column name.

        Returns:
            The stored value, or ``None`` when the column does not exist for
            this record. No default is fabricated.
        """
        if column_name == "ncodpers":
            return self.ncodpers
        if column_name == "fecha_dato":
            return self.fecha_dato
        return self.values.get(column_name)

    def as_dict(self) -> dict[str, Any]:
        """Return the record as a flat dict in schema order, preserving nulls."""
        flat: dict[str, Any] = {}
        for column_name in GOLD_TRAIN_COLUMN_NAMES:
            flat[column_name] = self.get(column_name)
        return flat


@dataclass(frozen=True)
class MonthPage:
    """A paginated page of client records for a single ``fecha_dato`` month.

    Attributes:
        items: The records on this page.
        page: 1-based page number.
        size: Page size requested.
        total: Total records available for the month (across all pages).
    """

    items: list[ClientRecord]
    page: int
    size: int
    total: int

    @property
    def has_next_page(self) -> bool:
        """Whether a further page exists after this one."""
        return self.page * self.size < self.total


# Guard against the schema drifting away from the dataclass contract.
_ENTITY_FIELD_NAMES = {f.name for f in fields(ClientRecord)}
assert "ncodpers" in _ENTITY_FIELD_NAMES
assert "fecha_dato" in _ENTITY_FIELD_NAMES
assert len(GOLD_TRAIN_COLUMN_NAMES) == 169


# --- Analytical gold tables (partitioned by fecha_dato, no ncodpers grain) ---
#
# The six ``gold_<key>`` analytical tables share one listing shape: a month
# (``fecha_dato``) partition, a set of string/number columns returned by Athena
# as strings, and a handful of equality filters. They are modelled with a
# generic row/page pair and an immutable registry mirroring
# ``iac/data-platform/glue/gold_analytics_tables.json`` (the source of truth),
# the same way ``GOLD_TRAIN_COLUMN_NAMES`` mirrors the gold Glue job.

EXPECTED_ANALYTICS_TABLE_COUNT = 6


@dataclass(frozen=True)
class GoldRow:
    """A single analytical gold row for one ``fecha_dato`` month.

    The row has no ``ncodpers`` grain. A ``None`` value means the datum is
    missing in the source; the domain never fabricates a default.

    Attributes:
        fecha_dato: The partition month in ``YYYY-MM-DD`` form.
        values: Table columns keyed by column name. Explicit ``None`` values
            are preserved; absent columns are simply not present.
    """

    fecha_dato: Optional[str] = None
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, column_name: str) -> Any:
        """Return the value of ``column_name`` or ``None`` when absent.

        Args:
            column_name: A column name of the table.

        Returns:
            The stored value, or ``None`` when the column is absent. No default
            is fabricated.
        """
        if column_name == "fecha_dato":
            return self.fecha_dato
        return self.values.get(column_name)

    def as_dict(self, column_names: tuple[str, ...]) -> dict[str, Any]:
        """Return the row as a flat dict in the given column order.

        Args:
            column_names: Column names defining the output order. ``fecha_dato``
                is handled transparently when present in the list.

        Returns:
            A dict mapping each requested column to its value, preserving nulls.
        """
        return {name: self.get(name) for name in column_names}


@dataclass(frozen=True)
class GoldTablePage:
    """A paginated page of analytical rows for a single ``fecha_dato`` month.

    Attributes:
        items: The rows on this page.
        page: 1-based page number.
        size: Page size requested.
        total: Total rows available for the month (across all pages).
    """

    items: list[GoldRow]
    page: int
    size: int
    total: int

    @property
    def has_next_page(self) -> bool:
        """Whether a further page exists after this one."""
        return self.page * self.size < self.total


@dataclass(frozen=True)
class AnalyticsTable:
    """Immutable metadata describing one analytical gold table.

    Attributes:
        key: The table key (e.g. ``product_monthly_kpis``). The physical Athena
            table name is ``<prefix><key>`` (``gold_product_monthly_kpis``).
        columns: The table columns in JSON order (excludes the ``fecha_dato``
            partition, which the JSON schema does not list).
        filter_columns: Columns allowed as equality filters at the API boundary.
    """

    key: str
    columns: tuple[str, ...]
    filter_columns: tuple[str, ...]

    @property
    def sortable_columns(self) -> frozenset[str]:
        """Allow-list of columns a caller may sort by (columns + fecha_dato)."""
        return frozenset(self.columns + ("fecha_dato",))


def _analytics_table(
    key: str, columns: tuple[str, ...], filter_columns: tuple[str, ...]
) -> AnalyticsTable:
    """Build an :class:`AnalyticsTable`, asserting filters are real columns."""
    for filter_column in filter_columns:
        assert filter_column in columns, (
            f"Filter column {filter_column!r} is not a column of {key!r}"
        )
    return AnalyticsTable(key=key, columns=columns, filter_columns=filter_columns)


# Registry mirroring ``gold_analytics_tables.json`` (columns in JSON order) with
# the per-table equality filter allow-lists derived from each table's grain and
# the example queries in ``03_gold_analitica.sql``.
ANALYTICS_TABLES: dict[str, AnalyticsTable] = {
    "product_monthly_kpis": _analytics_table(
        "product_monthly_kpis",
        (
            "product",
            "product_name",
            "clients",
            "holders",
            "penetration_rate",
            "eligible",
            "adds",
            "add_rate",
            "holders_prev",
            "drops",
            "drop_rate",
            "net_adds",
            "popularity_rank",
        ),
        ("product",),
    ),
    "customer_profile": _analytics_table(
        "customer_profile",
        (
            "segmento",
            "age_band",
            "sexo",
            "income_band",
            "clients",
            "active_clients",
            "active_rate",
            "new_clients",
            "avg_age",
            "avg_antiguedad_months",
            "avg_renta",
            "median_renta",
            "renta_known",
            "avg_n_products",
            "clients_without_products",
        ),
        ("segmento", "age_band", "sexo", "income_band"),
    ),
    "product_penetration": _analytics_table(
        "product_penetration",
        (
            "dimension",
            "dimension_value",
            "product",
            "product_name",
            "clients",
            "holders",
            "penetration_rate",
        ),
        ("dimension", "dimension_value", "product"),
    ),
    "product_affinity": _analytics_table(
        "product_affinity",
        (
            "product_a",
            "product_a_name",
            "product_b",
            "product_b_name",
            "clients",
            "holders_a",
            "holders_b",
            "holders_both",
            "support",
            "confidence",
            "lift",
            "phi",
        ),
        ("product_a", "product_b"),
    ),
    "product_transitions": _analytics_table(
        "product_transitions",
        (
            "from_product",
            "from_product_name",
            "to_product",
            "to_product_name",
            "clients",
            "to_product_adds",
            "share",
        ),
        ("from_product", "to_product"),
    ),
    "baseline_popularity": _analytics_table(
        "baseline_popularity",
        (
            "total_adds",
            "top_7_products",
            "popularity_ranking",
            "label_fecha_dato",
            "clients_evaluated",
            "clients_with_adds",
            "map_at_7",
            "map_at_7_buyers",
            "hit_rate_at_7_buyers",
        ),
        (),
    ),
}

assert len(ANALYTICS_TABLES) == EXPECTED_ANALYTICS_TABLE_COUNT
