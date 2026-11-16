"""Load and serve the trained FINSIR LightGBM product ranker."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
import joblib
import pandas as pd


class ProductRecommender:
    """In-memory wrapper around the multiclass artifact written by train.py."""

    def __init__(self, artifact: dict[str, Any]) -> None:
        required = {
            "model", "model_version", "feature_cols", "products",
            "categorical_categories", "class_to_product", "k",
        }
        missing = sorted(required - artifact.keys())
        if missing:
            raise ValueError(f"Model artifact is missing keys: {missing}")
        self.model = artifact["model"]
        self.model_version = str(artifact["model_version"])
        self.feature_cols = list(artifact["feature_cols"])
        self.products = list(artifact["products"])
        self.categories = artifact["categorical_categories"]
        self.class_to_product = {
            int(class_id): product
            for class_id, product in artifact["class_to_product"].items()
        }
        self.k = int(artifact["k"])

    @classmethod
    def from_s3(cls, uri: str, region: str) -> "ProductRecommender":
        """Download and load a joblib artifact using the task's IAM role."""
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("MODEL_S3_URI must be s3://bucket/key")
        with tempfile.TemporaryDirectory(prefix="finsir-model-") as directory:
            path = Path(directory) / "model.joblib"
            boto3.client("s3", region_name=region).download_file(
                parsed.netloc, parsed.path.lstrip("/"), str(path)
            )
            artifact = joblib.load(path)
        return cls(artifact)

    def recommend(self, features: dict[str, Any]) -> list[dict[str, Any]]:
        """Return up to K unowned products ranked by multiclass score."""
        missing = [column for column in self.feature_cols if column not in features]
        if missing:
            preview = ", ".join(missing[:8])
            suffix = "..." if len(missing) > 8 else ""
            raise ValueError(f"Missing model features: {preview}{suffix}")

        x = pd.DataFrame([{column: features[column]
                           for column in self.feature_cols}],
                         columns=self.feature_cols)
        categorical = set(self.categories)
        for column in self.feature_cols:
            if column in categorical:
                values = x[column].astype("object")
                known = values.isna() | values.isin(self.categories[column])
                x[column] = pd.Categorical(
                    values.where(known), categories=self.categories[column]
                )
            else:
                x[column] = pd.to_numeric(x[column], errors="coerce")

        probabilities = self.model.predict_proba(x)[0]
        held = {
            product for product in self.products
            if pd.to_numeric(
                pd.Series([features.get(product)]), errors="coerce"
            ).fillna(0).iloc[0] == 1
        }
        ranked = []
        for class_id, score in zip(self.model.classes_, probabilities):
            product = self.class_to_product.get(int(class_id))
            if product and product not in held:
                ranked.append((product, float(score)))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return [
            {"product": product, "score": score}
            for product, score in ranked[:self.k]
        ]
