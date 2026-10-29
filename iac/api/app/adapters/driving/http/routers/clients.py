"""Versioned ``/v1`` data routers over the silver layer (auth required).

Endpoints:
- ``GET /v1/clients/{ncodpers}``          a client's silver records
- ``GET /v1/clients/{ncodpers}/latest``   the client's most recent record
- ``GET /v1/months/{fecha_dato}/clients`` paginated listing for a month

All routes require a valid bearer token. Query parameters are validated at this
HTTP boundary (fail fast); violations become 422 via the validation handler.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.adapters.driving.http.auth import require_authenticated
from app.adapters.driving.http.dependencies import (
    get_client_latest_use_case,
    get_client_records_use_case,
    list_month_use_case,
)
from app.adapters.driving.http.schemas import (
    ClientRecordResponse,
    DataResponse,
    MonthPageResponse,
    PageMeta,
)
from app.domain.entities import ClientRecord, MonthPage
from app.use_cases.get_client_latest import GetClientLatest
from app.use_cases.get_client_records import GetClientRecords
from app.use_cases.list_month import ListMonth

MIN_PAGE = 1
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
FECHA_DATO_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(require_authenticated)],
    tags=["clients"],
)


def _to_record_response(record: ClientRecord) -> ClientRecordResponse:
    return ClientRecordResponse(
        ncodpers=record.ncodpers,
        fecha_dato=record.fecha_dato,
        attributes=dict(record.values),
    )


def _to_page_response(page: MonthPage) -> MonthPageResponse:
    return MonthPageResponse(
        items=[_to_record_response(item) for item in page.items],
        meta=PageMeta(
            page=page.page,
            size=page.size,
            total=page.total,
            has_next_page=page.has_next_page,
        ),
    )


@router.get(
    "/clients/{ncodpers}",
    response_model=DataResponse[list[ClientRecordResponse]],
    summary="List a client's silver records",
)
async def list_client_records(
    ncodpers: int = Path(..., ge=0, description="Client identifier"),
    use_case: GetClientRecords = Depends(get_client_records_use_case),
) -> DataResponse[list[ClientRecordResponse]]:
    """Return every silver record for ``ncodpers`` (404 if none)."""
    records = use_case.execute(ncodpers)
    return DataResponse(data=[_to_record_response(record) for record in records])


@router.get(
    "/clients/{ncodpers}/latest",
    response_model=DataResponse[ClientRecordResponse],
    summary="Get a client's most recent silver record",
)
async def get_client_latest(
    ncodpers: int = Path(..., ge=0, description="Client identifier"),
    use_case: GetClientLatest = Depends(get_client_latest_use_case),
) -> DataResponse[ClientRecordResponse]:
    """Return the most recent silver record for ``ncodpers`` (404 if none)."""
    record = use_case.execute(ncodpers)
    return DataResponse(data=_to_record_response(record))


@router.get(
    "/months/{fecha_dato}/clients",
    response_model=DataResponse[MonthPageResponse],
    summary="List clients for a month (paginated, sortable)",
)
async def list_month_clients(
    fecha_dato: str = Path(
        ..., pattern=FECHA_DATO_PATTERN, description="Month in YYYY-MM-DD form"
    ),
    page: int = Query(MIN_PAGE, ge=MIN_PAGE, description="1-based page number"),
    size: int = Query(
        DEFAULT_PAGE_SIZE, ge=MIN_PAGE_SIZE, le=MAX_PAGE_SIZE, description="Page size"
    ),
    sort: Optional[str] = Query(None, description="Column to sort by (ascending)"),
    use_case: ListMonth = Depends(list_month_use_case),
) -> DataResponse[MonthPageResponse]:
    """Return a paginated page of client records for ``fecha_dato``."""
    page_result = use_case.execute(fecha_dato, page, size, sort)
    return DataResponse(data=_to_page_response(page_result))
