"""HTTP response and error envelope models.

A consistent JSON shape for every response: successful payloads are wrapped in
``data``; errors use a stable ``error`` envelope that never leaks internals.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ClientRecordResponse(BaseModel):
    """A single gold_train record as a flat JSON object, nulls preserved."""

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


class GoldRowResponse(BaseModel):
    """A single analytical gold row as a flat JSON object, nulls preserved."""

    fecha_dato: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class GoldTablePageResponse(BaseModel):
    """A paginated page of analytical gold rows for a month."""

    items: list[GoldRowResponse]
    meta: PageMeta


class RecommendationInput(BaseModel):
    """One preprocessed Gold feature row for batch model inference."""

    ncodpers: Optional[int] = None
    fecha_dato: Optional[str] = None
    features: dict[str, Any]


class RecommendationBatchRequest(BaseModel):
    """Small batch request; large files should be scored outside HTTP."""

    records: list[RecommendationInput] = Field(min_length=1, max_length=100)


class RecommendedProduct(BaseModel):
    product: str
    score: float


class ClientRecommendations(BaseModel):
    ncodpers: Optional[int] = None
    fecha_dato: Optional[str] = None
    recommendations: list[RecommendedProduct]


class RecommendationBatchResponse(BaseModel):
    model_version: str
    items: list[ClientRecommendations]


class ErrorBody(BaseModel):
    """The error detail inside the error envelope."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Consistent error envelope returned for every failure."""

    error: ErrorBody
    correlationId: str
