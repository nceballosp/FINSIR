#!/usr/bin/env python3
"""Train the full FINSIR next-product recommendation model from S3 Gold.

The script is intended for an EC2 training instance with an instance profile.
It reads partitioned Parquet directly from S3 with DuckDB, trains the family
selected in the sample notebook, evaluates it against the popularity baseline
on temporal validation and a held-out test month, then refits the final
artifact for inference on the latest Gold month.

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
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

LOG = logging.getLogger("finsir.train")
LABEL_PREFIX = "label_next_"
K = 7
RANDOM_STATE = 42

# This small grid is intentionally bounded for repeatable EC2 runs. The best
# configuration is chosen only from temporal validation, never from test.
PARAMETER_GRID = (
    {"num_leaves": 15, "min_child_samples": 80},
    {"num_leaves": 31, "min_child_samples": 50},
    {"num_leaves": 31, "min_child_samples": 100},
)
BASE_PARAMS = {
    "objective": "binary",
    "n_estimators": 500,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
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
    parser.add_argument("--model-family", choices=("lightgbm", "logistic_regression", "random_forest"),
                        default="lightgbm",
                        help="Set to the learned family selected in the sample notebook")
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
    con.execute(
        "SET custom_extension_repository = 'https://extensions.duckdb.org'")
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
        "validation_month": str(valid_month.astype("datetime64[D]")),
        "test_month": str(test_month.astype("datetime64[D]")),
        "inference_month": str(inference_month.astype("datetime64[D]")),
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


def score_product(model, frame, cols, categories, product):
    eligible = frame.loc[frame[product].fillna(0).eq(0)]
    scores = pd.Series(0.0, index=frame.index, dtype="float32")
    if eligible.empty:
        return scores
    if categories is None:
        x = eligible[cols]
    else:
        x, _ = prepare_xy(eligible, cols, categories)
    scores.loc[eligible.index] = model.predict_proba(x)[:, 1].astype("float32")
    return scores


def make_sklearn_pipeline(family: str, frame: pd.DataFrame, cols: list[str]):
    numeric = frame[cols].select_dtypes(
        exclude=["object", "string", "category"]
    ).columns.tolist()
    categorical = [col for col in cols if col not in numeric]
    numeric_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler(with_mean=False)),
    ])
    categorical_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=25)),
    ])
    transformer = ColumnTransformer([
        ("numeric", numeric_pipeline, numeric),
        ("categorical", categorical_pipeline, categorical),
    ], sparse_threshold=0.3)
    if family == "logistic_regression":
        estimator = LogisticRegression(
            C=0.1, max_iter=250, solver="lbfgs", n_jobs=-1)
    elif family == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=80, max_depth=12, min_samples_leaf=25,
            max_features="sqrt", n_jobs=-1, random_state=RANDOM_STATE,
        )
    else:
        raise ValueError(f"Familia sklearn no soportada: {family}")
    return Pipeline([("preprocessor", transformer), ("model", estimator)])


def fit_product(family: str, frame: pd.DataFrame, evaluation: pd.DataFrame,
                product: str, cols: list[str], config: dict[str, Any]):
    if family == "lightgbm":
        return fit_lgbm_product(frame, evaluation, product, cols, config,
                                early_stopping=True)
    label = f"{LABEL_PREFIX}{product}"
    eligible = frame.loc[frame[product].fillna(0).eq(0)]
    if eligible.empty or eligible[label].nunique() < 2:
        return None, None, 0
    model = make_sklearn_pipeline(family, eligible, cols)
    model.fit(eligible[cols], eligible[label].astype("int8"))
    return model, None, 0


def fit_lgbm_product(frame, evaluation, product, cols, config,
                     early_stopping: bool = True):
    label = f"{LABEL_PREFIX}{product}"
    eligible_train = frame.loc[frame[product].fillna(0).eq(0)]
    eligible_eval = evaluation.loc[evaluation[product].fillna(0).eq(0)]
    y_train = eligible_train[label].astype("int8")
    if y_train.nunique() < 2 or eligible_eval.empty:
        return None, None, 0

    x_train, categories = prepare_xy(eligible_train, cols)
    x_eval, _ = prepare_xy(eligible_eval, cols, categories)
    model = lgb.LGBMClassifier(**lgbm_params(config))
    if early_stopping and eligible_eval[label].nunique() == 2:
        model.fit(
            x_train, y_train,
            eval_set=[(x_eval, eligible_eval[label].astype("int8"))],
            eval_metric="binary_logloss",
            categorical_feature=list(categories) or "auto",
            callbacks=[lgb.early_stopping(40, verbose=False),
                       lgb.log_evaluation(period=0)],
        )
    else:
        model.fit(x_train, y_train,
                  categorical_feature=list(categories) or "auto")
    best_iteration = int(model.best_iteration_ or model.n_estimators_)
    return model, categories, best_iteration


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

    # Select hyperparameters from validation only. Tune on the three most
    # prevalent products to bound runtime, then apply that setting to all labels.
    prevalence = {}
    for product in products:
        eligible = train[product].fillna(0).eq(0)
        prevalence[product] = float(train.loc[
            eligible, f"{LABEL_PREFIX}{product}"
        ].mean()) if eligible.any() else 0.0
    tune_products = sorted(
        products, key=lambda p: prevalence[p], reverse=True)[:3]
    tuning_rows = []
    best_config = {}
    if args.model_family == "lightgbm":
        for config in PARAMETER_GRID:
            aps = []
            for product in tune_products:
                model, categories, _ = fit_lgbm_product(
                    train, valid, product, cols, config, early_stopping=True
                )
                if model is None:
                    continue
                eligible = valid.loc[valid[product].fillna(0).eq(0)]
                if eligible[f"{LABEL_PREFIX}{product}"].nunique() < 2:
                    continue
                prediction = score_product(
                    model, valid, cols, categories, product)
                aps.append(average_precision_score(
                    valid.loc[eligible.index,
                              f"{LABEL_PREFIX}{product}"].astype("int8"),
                    prediction.loc[eligible.index],
                ))
            tuning_rows.append({**config, "mean_validation_average_precision":
                                float(np.mean(aps)) if aps else float("nan")})
        best_row = max(tuning_rows,
                       key=lambda row: row["mean_validation_average_precision"])
        best_config = {key: best_row[key] for key in PARAMETER_GRID[0]}
        LOG.info("Mejor configuración LightGBM (solo validación): %s", best_config)
    pd.DataFrame(tuning_rows).to_csv(
        output / "hyperparameter_search.csv", index=False)

    # Fit the user-selected family per product. Family selection comes from the
    # sample notebook's validation comparison; test is never used to select it.
    valid_scores = pd.DataFrame(0.0, index=valid.index, columns=products,
                                dtype="float32")
    test_scores = pd.DataFrame(0.0, index=test.index, columns=products,
                               dtype="float32")
    selected_models: dict[str, Any] = {}
    categories_by_product: dict[str, dict[str, list[Any]]] = {}
    best_iterations: dict[str, int] = {}
    importances = []
    train_diagnostic = train.sample(
        n=min(20_000, len(train)), random_state=RANDOM_STATE)
    train_scores = pd.DataFrame(0.0, index=train_diagnostic.index, columns=products,
                                dtype="float32")

    for number, product in enumerate(products, start=1):
        model, categories, best_iteration = fit_product(
            args.model_family, train, valid, product, cols, best_config
        )
        if model is None:
            LOG.warning("%s omitido: faltan clases o filas elegibles", product)
            continue
        selected_models[product] = model
        categories_by_product[product] = categories
        best_iterations[product] = best_iteration
        valid_scores[product] = score_product(
            model, valid, cols, categories, product)
        test_scores[product] = score_product(
            model, test, cols, categories, product)
        train_scores[product] = score_product(
            model, train_diagnostic, cols, categories, product)
        if args.model_family == "lightgbm":
            importance_features = cols
            importance_values = model.booster_.feature_importance("gain")
        elif args.model_family == "random_forest":
            importance_features = model.named_steps["preprocessor"].get_feature_names_out(
            )
            importance_values = model.named_steps["model"].feature_importances_
        else:
            importance_features = model.named_steps["preprocessor"].get_feature_names_out(
            )
            importance_values = np.abs(model.named_steps["model"].coef_[0])
        importances.extend({
            "producto": product,
            "feature": str(feature),
            "importance": float(gain),
        } for feature, gain in zip(importance_features, importance_values))
        LOG.info("Modelo %s/%s %s: iteración=%s", number, len(products),
                 product, best_iteration)

    if len(selected_models) != len(products):
        raise RuntimeError(
            f"Se entrenaron {len(selected_models)} de 24 modelos")

    # Baseline comparison on validation; the selected family was chosen in the
    # notebook and is recorded here for the complete data run.
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
        "mean_train_logloss": float(np.mean([
            log_loss(
                train_diagnostic.loc[train_diagnostic[p].fillna(
                    0).eq(0), f"{LABEL_PREFIX}{p}"].astype("int8"),
                np.clip(train_scores.loc[train_diagnostic[p].fillna(
                    0).eq(0), p], 1e-7, 1 - 1e-7),
                labels=[0, 1],
            ) for p in products
            if train_diagnostic.loc[train_diagnostic[p].fillna(0).eq(0), f"{LABEL_PREFIX}{p}"].nunique() == 2
        ])),
        "mean_validation_logloss": float(np.mean([
            log_loss(
                valid.loc[valid[p].fillna(0).eq(
                    0), f"{LABEL_PREFIX}{p}"].astype("int8"),
                np.clip(valid_scores.loc[valid[p].fillna(
                    0).eq(0), p], 1e-7, 1 - 1e-7),
                labels=[0, 1],
            ) for p in products
            if valid.loc[valid[p].fillna(0).eq(0), f"{LABEL_PREFIX}{p}"].nunique() == 2
        ])),
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
    # Release validation models before fitting the final production models.
    del selected_models
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

    # Refit final production models using all labeled data through validation.
    # The test month remains excluded from this final artifact.
    final_models: dict[str, Any] = {}
    final_categories: dict[str, dict[str, list[Any]]] = {}
    inference_scores = pd.DataFrame(0.0, index=inference.index, columns=products,
                                    dtype="float32")
    for product in products:
        label = f"{LABEL_PREFIX}{product}"
        eligible = final_train.loc[final_train[product].fillna(0).eq(0)]
        y = eligible[label].astype("int8")
        pred = inference.loc[inference[product].fillna(0).eq(0)]
        if y.nunique() < 2 or pred.empty:
            raise RuntimeError(f"No es posible ajustar/inferir para {product}")
        if args.model_family == "lightgbm":
            x_train, categories = prepare_xy(eligible, cols)
            x_pred, _ = prepare_xy(pred, cols, categories)
            final_model = lgb.LGBMClassifier(
                **lgbm_params(best_config, best_iterations[product])
            )
            final_model.fit(x_train, y,
                            categorical_feature=list(categories) or "auto")
        else:
            categories = None
            x_train = make_sklearn_pipeline(args.model_family, eligible, cols)
            x_train.fit(eligible[cols], y)
            final_model = x_train
            x_pred = pred[cols]
        final_models[product] = final_model
        final_categories[product] = categories
        inference_scores.loc[pred.index, product] = final_model.predict_proba(x_pred)[
            :, 1].astype("float32")

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
        "model_family": args.model_family,
        "models": final_models,
        "categorical_categories": final_categories,
        "feature_cols": cols,
        "products": products,
        "k": K,
        "selected_hyperparameters": best_config,
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
        "hyperparameter_tuning": {"products": tune_products if args.model_family == "lightgbm" else [],
                                  "grid": tuning_rows,
                                  "selected": best_config},
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
