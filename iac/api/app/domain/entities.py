"""Pure domain entities for the FINSIR silver layer.

These entities mirror the ``silver_train`` table schema produced by the data
platform's Glue job. They carry no framework dependencies.

Business rule: a ``None`` value means the datum does not exist in the source.
The domain never fabricates defaults for a missing column.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Optional

# The ``silver_train`` columns, in schema order (excluding the partition key).
# Kept here as the single source of truth so the Athena adapter and the API
# response model stay aligned with the domain entity.
SILVER_COLUMN_NAMES: tuple[str, ...] = (
    "ncodpers",
    "ind_empleado",
    "pais_residencia",
    "sexo",
    "age",
    "fecha_alta",
    "ind_nuevo",
    "antiguedad",
    "indrel",
    "ult_fec_cli_1t",
    "indrel_1mes",
    "tiprel_1mes",
    "indresi",
    "indext",
    "conyuemp",
    "canal_entrada",
    "indfall",
    "tipodom",
    "cod_prov",
    "nomprov",
    "ind_actividad_cliente",
    "renta",
    "segmento",
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
    "campos_rescatados",
    "campos_invalidados",
    # Partition key, present on every silver record.
    "fecha_dato",
)


@dataclass(frozen=True)
class ClientRecord:
    """A single monthly silver record for one client (``ncodpers``).

    Every attribute is optional: a ``None`` reflects a missing value in the
    source data and must never be replaced with a fabricated default.

    Attributes:
        ncodpers: The client identifier (bigint in the silver schema).
        fecha_dato: The partition month in ``YYYY-MM-DD`` form.
        values: Remaining silver columns keyed by column name. Absent columns
            are simply not present; explicit ``None`` values are preserved.
    """

    ncodpers: Optional[int] = None
    fecha_dato: Optional[str] = None
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, column_name: str) -> Any:
        """Return the value of ``column_name`` or ``None`` when absent.

        Args:
            column_name: A silver column name.

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
        for column_name in SILVER_COLUMN_NAMES:
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
