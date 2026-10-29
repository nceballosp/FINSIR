"""HTTP response and error envelope models.

A consistent JSON shape for every response: successful payloads are wrapped in
``data``; errors use a stable ``error`` envelope that never leaks internals.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ClientRecordResponse(BaseModel):
    """A single silver record as a flat JSON object, nulls preserved."""

    ncodpers: Optional[int] = None
    fecha_dato: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class DataResponse(BaseModel, Generic[T]):
    """Envelope wrapping a successful payload."""

    data: T


class PageMeta(BaseModel):
    """Pagination metadata for a month listing."""

    page: int
    size: int
    total: int
    has_next_page: bool


class MonthPageResponse(BaseModel):
    """A paginated page of client records for a month."""

    items: list[ClientRecordResponse]
    meta: PageMeta


class ErrorBody(BaseModel):
    """The error detail inside the error envelope."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Consistent error envelope returned for every failure."""

    error: ErrorBody
    correlationId: str
