#!/usr/bin/env python3
"""Train the full FINSIR next-product recommendation model from S3 Gold.

The script is intended for an EC2 training instance with an instance profile.
It reads partitioned Parquet directly from S3 with DuckDB, trains one
multiclass LightGBM model, selects parameters by temporal validation MAP@7,
evaluates against the popularity baseline on a held-out test month, then
refits the final artifact for inference on the latest Gold month.

Example:
    python train.py --bucket finsir-670099380322 --region us-east-1 \
      --output-dir ./artifacts --duckdb-temp-dir /mnt/finsir-duckdb-tmp \
      --artifact-s3-uri s3://finsir-670099380322/models/production/finsir.joblib

Optional local profile (never pass on an EC2 instance profile):
    python train.py --bucket finsir-670099380322 --aws-profile terraform
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

LOG = logging.getLogger("finsir.train")
LABEL_PREFIX = "label_next_"
K = 7
RANDOM_STATE = 42

# Tune ranking-relevant LightGBM settings on temporal validation only.
PARAMETER_GRID = (
    {"num_leaves": 31, "min_data_in_leaf": 20, "learning_rate": 0.05,
     "feature_fraction": 0.8},
    {"num_leaves": 64, "min_data_in_leaf": 10, "learning_rate": 0.1,
     "feature_fraction": 0.8},
    {"num_leaves": 64, "min_data_in_leaf": 25, "learning_rate": 0.05,
     "feature_fraction": 0.9},
    {"num_leaves": 96, "min_data_in_leaf": 10, "learning_rate": 0.05,
     "feature_fraction": 0.8},
)
BASE_PARAMS = {
    "task": "train",
    "boosting_type": "gbdt",
    "objective": "multiclass",
    "num_class": 24,
    "metric": "multi_logloss",
    "is_training_metric": True,
    "max_bin": 255,
    "num_leaves": 64,
    "learning_rate": 0.1,
    "feature_fraction": 0.8,
    "min_data_in_leaf": 10,
    "min_sum_hessian_in_leaf": 5,
    "n_estimators": 1000,
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
    "verbosity": -1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="S3 data lake bucket")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--gold-prefix", default="gold/train/")
    parser.add_argument("--output-dir", default="./artifacts")
    parser.add_argument("--artifact-s3-uri", default=None,
                        help="Optional S3 object URI for the finished artifact")
    parser.add_argument("--model-family", choices=("lightgbm",),
                        default="lightgbm",
                        help="Multiclass LightGBM product recommender")
    parser.add_argument("--aws-profile", default=None,
                        help="Optional local AWS profile; omit on EC2")
    parser.add_argument("--duckdb-memory-limit", default="80GB")
    parser.add_argument("--duckdb-temp-dir", default="/mnt/finsir-duckdb-tmp")
    parser.add_argument("--business-client-count", type=int, default=1000)
    parser.add_argument("--contact-cost-cop", type=float, default=None)
    parser.add_argument("--incremental-net-value-cop",
                        type=float, default=None)
    parser.add_argument("--campaign-uplift", type=float, default=None,
                        help="Optional assumed causal uplift, from 0 to 1")
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def quote_sql_string(value: str) -> str:
    return value.replace("'", "''")


def upload_artifact(session: boto3.Session, artifact_path: Path, uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError("artifact-s3-uri debe ser s3://bucket/key")
    session.client("s3").upload_file(
        str(artifact_path), parsed.netloc, parsed.path.lstrip("/")
    )


def read_gold(args: argparse.Namespace) -> pd.DataFrame:
    """Read Gold Parquet from S3. This full-data path needs a memory-sized EC2."""
    con = duckdb.connect()
    temp_dir = Path(args.duckdb_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"SET memory_limit = '{quote_sql_string(args.duckdb_memory_limit)}'")
    con.execute(f"SET temp_directory = '{quote_sql_string(str(temp_dir))}'")
    con.execute("INSTALL aws; LOAD aws; INSTALL httpfs; LOAD httpfs")

    region = quote_sql_string(args.region)
    if args.aws_profile:
        profile = quote_sql_string(args.aws_profile)
        con.execute(
            "CREATE OR REPLACE SECRET finsir_s3 (TYPE s3, "
            "PROVIDER credential_chain, CHAIN config, "
            f"PROFILE '{profile}', REGION '{region}')"
        )
    else:
        # On EC2 DuckDB obtains temporary credentials from the instance profile.
        con.execute(
            "CREATE OR REPLACE SECRET finsir_s3 (TYPE s3, "
            "PROVIDER credential_chain, CHAIN 'env;instance', "
            f"REGION '{region}')"
        )

    prefix = args.gold_prefix.strip("/")
    glob = f"s3://{args.bucket}/{prefix}/**/*.parquet"
    LOG.info("Leyendo Gold desde %s", glob)
    query = f"""
        SELECT *
        FROM read_parquet('{quote_sql_string(glob)}',
                          hive_partitioning = true, union_by_name = true)
    """
    frame = con.execute(query).fetchdf()
    con.close()
    if frame.empty:
        raise ValueError(f"No se encontraron filas Parquet en {glob}")
    frame["fecha_dato"] = pd.to_datetime(frame["fecha_dato"], errors="raise")
    # Reduce pandas' working set before temporal splits and model matrices.
    # Keep ncodpers at its source precision and leave strings as strings so
    # category vocabularies are learned only from each training fold.
    for column in frame.select_dtypes(include=["float64"]).columns:
        frame[column] = frame[column].astype("float32")
    for column in frame.select_dtypes(include=["int64"]).columns:
        if column != "ncodpers":
            frame[column] = pd.to_numeric(frame[column], downcast="integer")
    LOG.info("Gold leído: %s filas, %s clientes, %s meses, %s columnas",
             f"{len(frame):,}", f"{frame['ncodpers'].nunique():,}",
             frame["fecha_dato"].nunique(), len(frame.columns))
    return frame


def discover_products(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    label_cols = sorted(
        col for col in frame.columns
        if col.startswith(LABEL_PREFIX) and col != f"{LABEL_PREFIX}n_added"
    )
    products = [col[len(LABEL_PREFIX):] for col in label_cols]
    if len(products) != 24:
        raise ValueError(
            f"Se esperaban 24 productos; se encontraron {len(products)}")
    if any(product not in frame.columns for product in products):
        raise ValueError("Faltan columnas de tenencia de producto requeridas")
    return products, label_cols


def temporal_split(frame: pd.DataFrame, label_cols: list[str]):
    """Use the last two labeled months for validation/test and latest month for inference."""
    labeled = frame.loc[frame[label_cols].notna().all(axis=1)].copy()
    labeled_months = sorted(labeled["fecha_dato"].dropna().unique())
    all_months = sorted(frame["fecha_dato"].dropna().unique())
    if len(labeled_months) < 3 or len(all_months) < 1:
        raise ValueError(
            "Se necesitan al menos tres meses etiquetados y un mes de Gold")

    valid_month, test_month = labeled_months[-2], labeled_months[-1]
    train = labeled.loc[labeled.fecha_dato < valid_month].copy()
    valid = labeled.loc[labeled.fecha_dato == valid_month].copy()
    test = labeled.loc[labeled.fecha_dato == test_month].copy()
    inference_month = all_months[-1]
    inference = frame.loc[frame.fecha_dato == inference_month].copy()
    # Once the final holdout score has been recorded, the production artifact
    # can use every labeled month, including the test month.
    final_train = labeled

    if min(map(len, (train, valid, test, inference, final_train))) == 0:
        raise ValueError("Uno de los cortes temporales está vacío")
    if not train.fecha_dato.max() < valid.fecha_dato.min() < test.fecha_dato.min():
        raise AssertionError("Los cortes temporales no están ordenados")
    return train, valid, test, inference, final_train, {
        "train_max_feature_month": str(train.fecha_dato.max().date()),
        "validation_month": str(pd.Timestamp(valid_month).date()),
        "test_month": str(pd.Timestamp(test_month).date()),
        "inference_month": str(pd.Timestamp(inference_month).date()),
        "inference_target_month": "month following inference_month",
    }


def feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {"ncodpers", "fecha_dato"}
    cols = [c for c in frame.columns
            if not c.startswith(LABEL_PREFIX) and c not in excluded]
    if not cols:
        raise ValueError("No se encontraron features")
    return cols


def align_categories(values: pd.Series, categories: list[Any]) -> pd.Categorical:
    values = values.astype("object")
    known = values.isna() | values.isin(categories)
    return pd.Categorical(values.where(known), categories=categories)


def prepare_xy(frame: pd.DataFrame, cols: list[str], categories=None):
    x = frame[cols].copy()
    stored = {} if categories is None else categories
    categorical = x.select_dtypes(
        include=["object", "string", "category"]).columns
    for col in categorical:
        if categories is None:
            x[col] = x[col].astype("category")
            stored[col] = list(x[col].cat.categories)
        else:
            x[col] = align_categories(x[col], categories.get(col, []))
    for col in x.select_dtypes(include=["bool"]).columns:
        x[col] = x[col].astype("int8")
    return x, stored


def average_precision_at_k(actual: set[str], predicted: list[str], k: int = K) -> float:
    if not actual:
        return 0.0
    hits = 0
    score = 0.0
    for rank, product in enumerate(predicted[:k], start=1):
        if product in actual:
            hits += 1
            score += hits / rank
    return score / min(len(actual), k)


def per_row_metrics(frame: pd.DataFrame, scores: pd.DataFrame,
                    products: list[str], label_cols: list[str],
                    include_details: bool = False) -> pd.DataFrame:
    """Compute MAP@7 and hit metrics vectorially across all client-month rows."""
    held = frame[products].fillna(0).to_numpy(dtype=np.float32) == 1
    actual = frame[label_cols].to_numpy(dtype=np.float32) == 1
    score_values = scores.loc[frame.index, products].to_numpy(dtype=np.float32)
    rank_values = np.where(held, -np.inf, score_values)
    # Product columns are sorted, so stable sorting also gives deterministic
    # alphabetical tie-breaking, matching the notebook's ranking contract.
    order = np.argsort(-rank_values, axis=1, kind="stable")[:, :K]
    selected_eligible = np.take_along_axis(~held, order, axis=1)
    selected_hits = np.take_along_axis(
        actual, order, axis=1) & selected_eligible
    cumulative_hits = np.cumsum(selected_hits, axis=1)
    discounts = np.arange(1, K + 1, dtype=np.float32)
    actual_count = actual.sum(axis=1)
    denominator = np.minimum(actual_count, K)
    ap = np.divide(
        ((cumulative_hits / discounts) * selected_hits).sum(axis=1),
        denominator,
        out=np.zeros(len(frame), dtype=np.float32),
        where=denominator > 0,
    )
    hit_count = selected_hits.sum(axis=1)
    result = pd.DataFrame({
        "average_precision_at_7": ap,
        "hit_at_7": (hit_count > 0).astype("int8"),
        "precision_at_7": hit_count / K,
        "recall_at_7": np.divide(hit_count, actual_count,
                                 out=np.zeros(len(frame), dtype=np.float32),
                                 where=actual_count > 0),
    }, index=frame.index)
    if include_details:
        result["recommendations"] = [
            [products[j] for j, valid in zip(row_order, row_valid) if valid]
            for row_order, row_valid in zip(order, selected_eligible)
        ]
        result["actual_additions"] = [
            [products[j] for j, yes in enumerate(row) if yes] for row in actual
        ]
        result["held_products"] = [
            [products[j] for j, yes in enumerate(row) if yes] for row in held
        ]
    return result


def map_at_7(frame, scores, products, label_cols) -> float:
    return float(per_row_metrics(frame, scores, products, label_cols)
                 ["average_precision_at_7"].mean())


def popularity_scores(reference: pd.DataFrame, target: pd.DataFrame,
                      products: list[str]) -> tuple[pd.DataFrame, dict[str, float]]:
    rates = {}
    for product in products:
        eligible = (reference[product].fillna(0).eq(0)
                    & reference[f"{LABEL_PREFIX}{product}"].notna())
        rates[product] = float(reference.loc[
            eligible, f"{LABEL_PREFIX}{product}"
        ].mean()) if eligible.any() else 0.0
    return pd.DataFrame({p: rates[p] for p in products}, index=target.index), rates


def lgbm_params(config: dict[str, Any], n_estimators: int | None = None):
    params = {**BASE_PARAMS, **config}
    if n_estimators is not None:
        params["n_estimators"] = max(20, int(n_estimators))
    return params


def expand_product_targets(frame: pd.DataFrame, products: list[str],
                           label_cols: list[str], cols: list[str],
                           categories=None):
    """Expand each customer-month once per newly acquired product.

    This lets a multiclass learner learn the distribution of acquisition
    events while validation still measures all simultaneous additions.
    Each source row has total weight one, regardless of its number of labels.
    """
    held = frame[products].fillna(0).to_numpy(dtype=np.float32) == 1
    targets = frame[label_cols].fillna(0).to_numpy(dtype=np.int8) == 1
    targets &= ~held
    row_idx, class_idx = np.where(targets)
    if len(row_idx) == 0:
        raise ValueError("No hay adquisiciones de productos para entrenar")
    x = frame.iloc[row_idx][cols].reset_index(drop=True)
    x, stored_categories = prepare_xy(x, cols, categories)
    weights = 1.0 / np.bincount(row_idx, minlength=len(frame))[row_idx]
    return x, class_idx.astype("int32"), weights.astype("float32"), stored_categories


def score_multiclass(model, frame, cols, products, categories):
    x, _ = prepare_xy(frame, cols, categories)
    probabilities = model.predict_proba(x).astype("float32")
    scores = pd.DataFrame(0.0, index=frame.index, columns=products,
                          dtype="float32")
    for output_col, class_idx in enumerate(model.classes_):
        if 0 <= int(class_idx) < len(products):
            scores.iloc[:, int(class_idx)] = probabilities[:, output_col]
    held = frame[products].fillna(0).to_numpy(dtype=np.float32) == 1
    scores.values[held] = 0.0
    return scores


def fit_lgbm_multiclass(frame, evaluation, products, label_cols, cols,
                        config, early_stopping=True):
    x_train, y_train, weights, categories = expand_product_targets(
        frame, products, label_cols, cols)
    missing_classes = sorted(set(range(len(products))) - set(np.unique(y_train)))
    if missing_classes:
        missing_products = [products[class_idx] for class_idx in missing_classes]
        raise ValueError(
            "El corte de entrenamiento no contiene adquisiciones para "
            f"estas clases multiclase: {missing_products}")
    x_eval, y_eval, eval_weights, _ = expand_product_targets(
        evaluation, products, label_cols, cols, categories)
    model = lgb.LGBMClassifier(**lgbm_params(config))
    fit_kwargs = {
        "sample_weight": weights,
        "categorical_feature": list(categories) or "auto",
    }
    if early_stopping:
        fit_kwargs.update({
            "eval_set": [(x_eval, y_eval)],
            "eval_sample_weight": [eval_weights],
            "eval_metric": "multi_logloss",
            "callbacks": [lgb.early_stopping(60, verbose=False),
                          lgb.log_evaluation(period=0)],
        })
    model.fit(x_train, y_train, **fit_kwargs)
    return model, categories, int(model.best_iteration_ or model.n_estimators_)


def segment_metrics(frame, rows: pd.DataFrame) -> pd.DataFrame:
    data = frame[["age", "renta", "segmento", "sexo"]].copy()
    data["age_band"] = pd.cut(
        pd.to_numeric(data["age"], errors="coerce"),
        bins=[-np.inf, 24, 34, 44, 54, 64, np.inf],
        labels=["<=24", "25-34", "35-44", "45-54", "55-64", "65+"],
    ).astype("object")
    income = pd.to_numeric(data["renta"], errors="coerce")
    data["income_band"] = pd.cut(
        income, bins=[-np.inf, 50000, 100000, 150000, 250000, np.inf],
        labels=["<=50k", "50-100k", "100-150k", "150-250k", ">250k"],
    ).astype("object")
    data["segmento"] = data["segmento"].fillna("Sin dato").astype(str)
    data["sexo"] = data["sexo"].fillna("Sin dato").astype(str)
    data = data.join(rows[["average_precision_at_7", "hit_at_7"]])
    outputs = []
    for field in ("age_band", "income_band", "segmento", "sexo"):
        grouped = data.groupby(field, observed=True, dropna=False)
        stats = grouped.agg(
            clientes=("hit_at_7", "size"),
            MAP_at_7=("average_precision_at_7", "mean"),
            hit_rate_at_7=("hit_at_7", "mean"),
        ).reset_index().rename(columns={field: "segmento_valor"})
        stats.insert(0, "segmento", field)
        outputs.append(stats)
    return pd.concat(outputs, ignore_index=True)


def json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    return str(value)


def run() -> None:
    args = parse_args()
    setup_logging()
    aws_session = boto3.Session(
        profile_name=args.aws_profile,
        region_name=args.region,
    )
    if args.business_client_count < 1:
        raise ValueError("business-client-count debe ser positivo")
    if args.campaign_uplift is not None and not 0 <= args.campaign_uplift <= 1:
        raise ValueError("campaign-uplift debe estar entre 0 y 1")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = read_gold(args)
    products, labels = discover_products(frame)
    cols = feature_columns(frame)
    train, valid, test, inference, final_train, cuts = temporal_split(
        frame, labels)
    LOG.info("Cortes temporales: train=%s (%s filas), valid=%s (%s), test=%s (%s), "
             "inferencia=%s (%s)", cuts["train_max_feature_month"], f"{len(train):,}",
             cuts["validation_month"], f"{len(valid):,}", cuts["test_month"],
             f"{len(test):,}", cuts["inference_month"], f"{len(inference):,}")
    LOG.info("Features=%s; etiquetas=%s. Las etiquetas no entran a X.",
             len(cols), len(labels))

    valid_pop, popularity = popularity_scores(train, valid, products)
    test_pop, _ = popularity_scores(train, test, products)
    baseline_valid_rows = per_row_metrics(valid, valid_pop, products, labels)
    baseline_test_rows = per_row_metrics(test, test_pop, products, labels)

    # Select parameters and iteration count by validation MAP@7 only.
    tuning_rows = []
    for config in PARAMETER_GRID:
        tuning_model, tuning_categories, best_iteration = fit_lgbm_multiclass(
            train, valid, products, labels, cols, config, early_stopping=True)
        tuning_scores = score_multiclass(
            tuning_model, valid, cols, products, tuning_categories)
        tuning_rows.append({**config, "best_iteration": best_iteration,
                            "validation_MAP_at_7": map_at_7(
                                valid, tuning_scores, products, labels)})
        del tuning_model
    best_row = max(tuning_rows, key=lambda row: row["validation_MAP_at_7"])
    best_config = {key: best_row[key] for key in PARAMETER_GRID[0]}
    selected_iterations = int(best_row["best_iteration"])
    LOG.info("Selected LightGBM parameters by validation MAP@7: %s; iterations=%s",
             best_config, selected_iterations)
    pd.DataFrame(tuning_rows).to_csv(
        output / "hyperparameter_search.csv", index=False)

    # Fit one multiclass model and score each eligible product for ranking.
    valid_scores = pd.DataFrame(0.0, index=valid.index, columns=products,
                                dtype="float32")
    test_scores = pd.DataFrame(0.0, index=test.index, columns=products,
                               dtype="float32")
    model, categories, _ = fit_lgbm_multiclass(
        train, valid, products, labels, cols,
        {**best_config, "n_estimators": selected_iterations},
        early_stopping=False)
    valid_scores = score_multiclass(model, valid, cols, products, categories)
    test_scores = score_multiclass(model, test, cols, products, categories)
    train_diagnostic = train.sample(
        n=min(20_000, len(train)), random_state=RANDOM_STATE)
    train_scores = score_multiclass(
        model, train_diagnostic, cols, products, categories)
    importance_values = model.booster_.feature_importance("gain")
    importances = [{"producto": "multiclass", "feature": str(feature),
                    "importance": float(gain)}
                   for feature, gain in zip(cols, importance_values)]
    # Compare the selected multiclass model with popularity on validation.
    valid_model_rows = per_row_metrics(valid, valid_scores, products, labels)
    family_validation = pd.DataFrame([
        {"modelo": "popularidad", "MAP@7": baseline_valid_rows.average_precision_at_7.mean(),
         "hit_rate@7": baseline_valid_rows.hit_at_7.mean()},
        {"modelo": args.model_family, "MAP@7": valid_model_rows.average_precision_at_7.mean(),
         "hit_rate@7": valid_model_rows.hit_at_7.mean()},
    ]).sort_values("MAP@7", ascending=False)
    family_validation.to_csv(
        output / "model_comparison_validation.csv", index=False)

    # The held-out test is evaluated only after validation selection is complete.
    test_model_rows = per_row_metrics(test, test_scores, products, labels)
    final_test = pd.DataFrame([
        {"modelo": "popularidad", "MAP@7": baseline_test_rows.average_precision_at_7.mean(),
         "hit_rate@7": baseline_test_rows.hit_at_7.mean()},
        {"modelo": args.model_family, "MAP@7": test_model_rows.average_precision_at_7.mean(),
         "hit_rate@7": test_model_rows.hit_at_7.mean()},
    ])
    final_test.to_csv(output / "model_test_metrics.csv", index=False)

    # Bias/variance diagnosis: compare training and validation ranking metric.
    train_rows = per_row_metrics(
        train_diagnostic, train_scores, products, labels)
    diagnosis = {
        "train_MAP_at_7": float(train_rows.average_precision_at_7.mean()),
        "validation_MAP_at_7": float(valid_model_rows.average_precision_at_7.mean()),
        "train_validation_gap": float(
            train_rows.average_precision_at_7.mean()
            - valid_model_rows.average_precision_at_7.mean()
        ),
    }

    segments = segment_metrics(test, test_model_rows)
    segments.to_csv(output / "test_metrics_by_segment.csv", index=False)
    importance = pd.DataFrame(importances)
    importance_summary = (importance.groupby("feature", as_index=False).importance.sum()
                          .sort_values("importance", ascending=False))
    importance_summary.to_csv(output / "feature_importance.csv", index=False)

    # Business translation: estimated successful customers per 1,000 contacts
    # from observed holdout hit rates. This is not a causal uplift estimate.
    n_contacts = args.business_client_count
    model_hit_rate = float(test_model_rows.hit_at_7.mean())
    baseline_hit_rate = float(baseline_test_rows.hit_at_7.mean())
    business = {
        "assumed_contacts": n_contacts,
        "observed_model_successes_at_7": model_hit_rate * n_contacts,
        "observed_baseline_successes_at_7": baseline_hit_rate * n_contacts,
        "estimated_difference_vs_baseline": (model_hit_rate - baseline_hit_rate) * n_contacts,
        "interpretation": (
            "Holdout simulation only; observed association is not causal campaign uplift."
        ),
    }
    if (args.contact_cost_cop is not None
            and args.incremental_net_value_cop is not None
            and args.campaign_uplift is not None):
        expected_conversions = n_contacts * model_hit_rate * args.campaign_uplift
        business["scenario"] = {
            "assumed_contact_cost_cop": args.contact_cost_cop,
            "assumed_incremental_net_value_per_conversion_cop": args.incremental_net_value_cop,
            "assumed_campaign_uplift": args.campaign_uplift,
            "estimated_net_value_cop": (
                expected_conversions * args.incremental_net_value_cop
                - n_contacts * args.contact_cost_cop
            ),
            "warning": "Scenario depends on user-provided causal and financial assumptions.",
        }

    # Concrete cases from the held-out test month; these demonstrate how the
    # ranking behaves, including successes and misses.
    # Release the validation model before fitting the final production model.
    del model
    case_indices = test_model_rows.sort_values(
        ["hit_at_7", "average_precision_at_7"], ascending=False
    ).head(10).index
    case_subset = test.loc[case_indices]
    case_details = per_row_metrics(
        case_subset, test_scores, products, labels, include_details=True
    )
    case_frame = case_subset.join(case_details[[
        "recommendations", "actual_additions", "held_products", "hit_at_7"
    ]])
    case_cols = [c for c in ["ncodpers", "fecha_dato", "age", "sexo", "segmento",
                             "renta", "n_products", "recommendations",
                             "actual_additions", "held_products", "hit_at_7"]
                 if c in case_frame.columns]
    case_frame[case_cols].to_csv(output / "test_case_studies.csv", index=False)

    # Refit one production model on all labeled data before the test month.
    final_x, final_y, final_weights, final_categories = expand_product_targets(
        final_train, products, labels, cols)
    inference_x, _ = prepare_xy(inference, cols, final_categories)
    final_model = lgb.LGBMClassifier(
        **lgbm_params({**best_config, "n_estimators": selected_iterations}))
    final_model.fit(
        final_x, final_y, sample_weight=final_weights,
        categorical_feature=list(final_categories) or "auto")
    inference_probabilities = final_model.predict_proba(inference_x).astype("float32")
    inference_scores = pd.DataFrame(0.0, index=inference.index, columns=products,
                                    dtype="float32")
    for output_col, class_idx in enumerate(final_model.classes_):
        if 0 <= int(class_idx) < len(products):
            inference_scores.iloc[:, int(class_idx)] = inference_probabilities[:, output_col]
    inference_held = inference[products].fillna(0).to_numpy(dtype=np.float32) == 1
    inference_scores.values[inference_held] = 0.0
    example_idx = inference.index[0]
    example = inference.loc[example_idx]
    held = {p for p in products if pd.notna(example[p]) and example[p] == 1}
    ranked = sorted(
        products, key=lambda p: (-float(inference_scores.at[example_idx, p]), p))
    example_recommendations = [
        {"producto": p, "score": float(inference_scores.at[example_idx, p])}
        for p in ranked if p not in held
    ][:K]

    model_version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = output / f"finsir_{args.model_family}_full.joblib"
    joblib.dump({
        "model_name": "finsir_product_recommendation",
        "model_family": args.model_family,
        "model_version": model_version,
        "model": final_model,
        "categorical_categories": final_categories,
        "feature_cols": cols,
        "products": products,
        "class_to_product": {int(class_idx): products[int(class_idx)]
                             for class_idx in final_model.classes_},
        "k": K,
        "selected_hyperparameters": best_config,
        "selected_iterations": selected_iterations,
        "training_max_feature_month": str(final_train.fecha_dato.max().date()),
        "label_definition": "product acquired in the following month",
        "test_map_at_7": float(test_model_rows.average_precision_at_7.mean()),
        "test_baseline_map_at_7": float(baseline_test_rows.average_precision_at_7.mean()),
    }, artifact_path, compress=3)

    if args.artifact_s3_uri:
        upload_artifact(aws_session, artifact_path, args.artifact_s3_uri)
        LOG.info("Artefacto copiado a %s", args.artifact_s3_uri)

    metrics = {
        "model_version": model_version,
        "source": f"s3://{args.bucket}/{args.gold_prefix.strip('/')}/",
        "rows": {"train": len(train), "validation": len(valid), "test": len(test),
                 "inference": len(inference)},
        "clients": {"train": int(train.ncodpers.nunique()),
                    "validation": int(valid.ncodpers.nunique()),
                    "test": int(test.ncodpers.nunique()),
                    "inference": int(inference.ncodpers.nunique())},
        "temporal_cuts": cuts,
        "feature_count": len(cols),
        "products": products,
        "hyperparameter_tuning": {"scope": "all 24 products jointly",
                                  "grid": tuning_rows,
                                  "selected": best_config,
                                  "selected_iterations": selected_iterations},
        "validation_comparison": family_validation.to_dict(orient="records"),
        "test_metrics": final_test.to_dict(orient="records"),
        "bias_variance_diagnosis": diagnosis,
        "business_simulation": business,
        "top_global_features": importance_summary.head(20).to_dict(orient="records"),
        "example_customer_id": int(example.ncodpers),
        "example_recommendations": example_recommendations,
        "artifact": str(artifact_path),
        "artifact_s3_uri": args.artifact_s3_uri,
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False,
                   default=json_default),
        encoding="utf-8",
    )
    LOG.info("MAP@7 validación: baseline=%.6f, %s=%.6f",
             baseline_valid_rows.average_precision_at_7.mean(),
             args.model_family,
             valid_model_rows.average_precision_at_7.mean())
    LOG.info("MAP@7 prueba: baseline=%.6f, %s=%.6f",
             baseline_test_rows.average_precision_at_7.mean(),
             args.model_family,
             test_model_rows.average_precision_at_7.mean())
    LOG.info("Artefacto final: %s", artifact_path)
    LOG.info("Reporte de métricas: %s", output / "metrics.json")


if __name__ == "__main__":
    run()
