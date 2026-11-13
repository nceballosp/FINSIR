"""Versioned ``/v1/gold/...`` routers over the analytical gold tables (auth required).

One paginated month-listing endpoint per analytical ``gold_<key>`` table,
mirroring the ``gold_train`` month endpoint:

    GET /v1/gold/<resource>/months/{fecha_dato}

with ``page`` (>= 1), ``size`` (1..200), ``sort`` (allow-listed per table) and
the per-table optional equality filters. The six routers are built from a map
keyed off :data:`ANALYTICS_TABLES`, so routes and filters stay in sync with the
registry. All routes require a valid bearer token; query parameters are
validated at this HTTP boundary (422 on violation) and again as the
SQL-injection control in the Athena adapter.
"""

from __future__ import annotations

import inspect
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.adapters.driving.http.auth import require_authenticated
from app.adapters.driving.http.dependencies import list_analytics_month_use_case
from app.adapters.driving.http.schemas import (
    DataResponse,
    GoldRowResponse,
    GoldTablePageResponse,
    PageMeta,
)
from app.domain.entities import ANALYTICS_TABLES, GoldTablePage
from app.use_cases.list_analytics_month import ListAnalyticsMonth

MIN_PAGE = 1
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
FECHA_DATO_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# Resource path per table key (plural/kebab-case nouns under /v1/gold).
RESOURCE_PATHS: dict[str, str] = {
    "product_monthly_kpis": "product-kpis",
    "customer_profile": "customer-profiles",
    "product_penetration": "product-penetration",
    "product_affinity": "product-affinity",
    "product_transitions": "product-transitions",
    "baseline_popularity": "baseline-popularity",
}


def _to_page_response(page: GoldTablePage) -> GoldTablePageResponse:
    return GoldTablePageResponse(
        items=[
            GoldRowResponse(fecha_dato=item.fecha_dato, attributes=dict(item.values))
            for item in page.items
        ],
        meta=PageMeta(
            page=page.page,
            size=page.size,
            total=page.total,
            has_next_page=page.has_next_page,
        ),
    )


def build_analytics_router(
    resource_path: str,
    table_key: str,
    filter_params: tuple[str, ...],
) -> APIRouter:
    """Build an auth-protected month-listing router for one analytical table.

    Args:
        resource_path: The kebab-case resource segment (e.g. ``product-kpis``).
        table_key: The analytics table key passed to the use case.
        filter_params: Names of the optional equality-filter query params.

    Returns:
        An :class:`APIRouter` exposing ``GET /v1/gold/<resource>/months/{fecha_dato}``.
    """
    router = APIRouter(
        prefix=f"/v1/gold/{resource_path}",
        dependencies=[Depends(require_authenticated)],
        tags=[f"gold_{table_key}"],
    )

    async def list_month_records(
        fecha_dato: str = Path(
            ..., pattern=FECHA_DATO_PATTERN, description="Month in YYYY-MM-DD form"
        ),
        page: int = Query(MIN_PAGE, ge=MIN_PAGE, description="1-based page number"),
        size: int = Query(
            DEFAULT_PAGE_SIZE,
            ge=MIN_PAGE_SIZE,
            le=MAX_PAGE_SIZE,
            description="Page size",
        ),
        sort: Optional[str] = Query(None, description="Column to sort by (ascending)"),
        use_case: ListAnalyticsMonth = Depends(list_analytics_month_use_case),
        **filter_values: Optional[str],
    ) -> DataResponse[GoldTablePageResponse]:
        """Return a paginated page of rows for ``fecha_dato`` for this table.

        The per-table equality filters are injected as keyword arguments by the
        dynamic signature built in :func:`_attach_filter_params`.
        """
        filters = {
            name: value for name, value in filter_values.items() if value is not None
        }
        page_result = use_case.execute(table_key, fecha_dato, page, size, sort, filters)
        return DataResponse(data=_to_page_response(page_result))

    _attach_filter_params(list_month_records, filter_params)

    router.add_api_route(
        "/months/{fecha_dato}",
        list_month_records,
        methods=["GET"],
        response_model=DataResponse[GoldTablePageResponse],
        summary=f"List {table_key} rows for a month (paginated, sortable)",
    )
    return router


def _attach_filter_params(endpoint, filter_params: tuple[str, ...]) -> None:
    """Declare one optional ``str`` query param per filter on ``endpoint``.

    FastAPI reads the function signature to build query params and OpenAPI docs.
    Injecting the per-table filters here keeps every endpoint's filter set in
    sync with the registry without copy-pasting a handler per table. The handler
    reads the values back from ``request.query_params``.
    """
    signature = inspect.signature(endpoint)
    # Drop the ``**filter_values`` var-keyword placeholder; the concrete filter
    # params replace it so FastAPI documents and validates each one.
    declared_params = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind is not inspect.Parameter.VAR_KEYWORD
    ]
    use_case_param = declared_params.pop()  # keep ``use_case`` last.
    filter_parameters = [
        inspect.Parameter(
            name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Query(None, description=f"Filter by {name} (equality)"),
            annotation=Optional[str],
        )
        for name in filter_params
    ]
    endpoint.__signature__ = signature.replace(
        parameters=[*declared_params, *filter_parameters, use_case_param]
    )


def build_analytics_routers() -> list[APIRouter]:
    """Build the month-listing router for every table in the registry."""
    return [
        build_analytics_router(
            RESOURCE_PATHS[table_key], table_key, table.filter_columns
        )
        for table_key, table in ANALYTICS_TABLES.items()
    ]
