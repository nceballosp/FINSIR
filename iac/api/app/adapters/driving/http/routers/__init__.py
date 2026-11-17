"""HTTP routers."""

from app.adapters.driving.http.routers import (
    gold_analytics,
    gold_train,
    health,
    recommendations,
)

__all__ = ["gold_analytics", "gold_train", "health", "recommendations"]
