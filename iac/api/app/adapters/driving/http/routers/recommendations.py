"""Authenticated product recommendation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.adapters.driving.http.auth import require_authenticated
from app.adapters.driving.http.dependencies import (
    get_client_records_use_case,
    get_product_recommender,
)
from app.adapters.driving.http.schemas import (
    ClientRecommendations,
    DataResponse,
    RecommendationBatchRequest,
    RecommendationBatchResponse,
)
from app.domain.errors import InvalidModelInputError, ModelUnavailableError
from app.services.product_recommender import ProductRecommender
from app.use_cases.get_client_records import GetClientRecords

router = APIRouter(
    prefix="/v1/recommendations",
    dependencies=[Depends(require_authenticated)],
    tags=["recommendations"],
)


def _recommend_item(model: ProductRecommender, ncodpers, fecha_dato, features):
    try:
        recommendations = model.recommend(features)
    except ValueError as error:
        raise InvalidModelInputError(str(error)) from error
    return ClientRecommendations(
        ncodpers=ncodpers,
        fecha_dato=fecha_dato,
        recommendations=recommendations,
    )


def _require_model(model: ProductRecommender | None) -> ProductRecommender:
    if model is None:
        raise ModelUnavailableError()
    return model


@router.get(
    "/clients/{ncodpers}",
    response_model=DataResponse[RecommendationBatchResponse],
    summary="Recommend the next products for a client in Gold",
)
async def recommend_for_client(
    ncodpers: int = Path(..., ge=0),
    client_records: GetClientRecords = Depends(get_client_records_use_case),
    recommender: ProductRecommender | None = Depends(get_product_recommender),
) -> DataResponse[RecommendationBatchResponse]:
    model = _require_model(recommender)
    records = client_records.execute(ncodpers)
    latest = max(records, key=lambda record: record.fecha_dato or "")
    item = _recommend_item(
        model, latest.ncodpers, latest.fecha_dato, latest.values
    )
    return DataResponse(data=RecommendationBatchResponse(
        model_version=model.model_version, items=[item]
    ))


@router.post(
    "/batch",
    response_model=DataResponse[RecommendationBatchResponse],
    summary="Score up to 100 preprocessed Gold rows",
)
async def recommend_batch(
    body: RecommendationBatchRequest,
    recommender: ProductRecommender | None = Depends(get_product_recommender),
) -> DataResponse[RecommendationBatchResponse]:
    model = _require_model(recommender)
    items = [
        _recommend_item(
            model,
            record.ncodpers,
            record.fecha_dato,
            record.features,
        )
        for record in body.records
    ]
    return DataResponse(data=RecommendationBatchResponse(
        model_version=model.model_version, items=items
    ))
