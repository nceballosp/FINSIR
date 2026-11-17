#!/usr/bin/env python3
"""Read Gold Parquet rows from S3 and send them to the recommendation API."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any

import duckdb
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-s3-uri", required=True,
                        help="Gold prefix, e.g. s3://bucket/gold/test_ver2/")
    parser.add_argument("--api-url", required=True,
                        help="API base URL, e.g. http://1.2.3.4:8080")
    parser.add_argument("--fecha-dato", default=None,
                        help="Optional Gold month to sample (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Maximum rows to send; requests are split into batches of 100")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--aws-profile", default=None,
                        help="Local AWS profile; omit on EC2 with an instance role")
    parser.add_argument("--token", default=os.getenv("FINSIR_API_TOKEN"),
                        help="Bearer token (or set FINSIR_API_TOKEN)")
    args = parser.parse_args()
    if not args.token:
        parser.error("pass --token or set FINSIR_API_TOKEN")
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.fecha_dato and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.fecha_dato):
        parser.error("--fecha-dato must use YYYY-MM-DD")
    if not args.gold_s3_uri.startswith("s3://"):
        parser.error("--gold-s3-uri must start with s3://")
    return args


def json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def request_recommendations(api_url: str, token: str,
                            records: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps({"records": records}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        api_url.rstrip("/") + "/v1/recommendations/batch",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {error.code}: {detail}") from error


def main() -> None:
    args = parse_args()
    con = duckdb.connect()
    con.execute("INSTALL aws; LOAD aws; INSTALL httpfs; LOAD httpfs")
    region = args.region.replace("'", "''")
    if args.aws_profile:
        profile = args.aws_profile.replace("'", "''")
        con.execute(
            "CREATE OR REPLACE SECRET finsir_s3 (TYPE s3, "
            "PROVIDER credential_chain, CHAIN config, "
            f"PROFILE '{profile}', REGION '{region}')"
        )
    else:
        con.execute(
            "CREATE OR REPLACE SECRET finsir_s3 (TYPE s3, "
            "PROVIDER credential_chain, CHAIN 'env;instance', "
            f"REGION '{region}')"
        )

    prefix = args.gold_s3_uri.rstrip("/")
    parquet_glob = prefix + "/**/*.parquet"
    sql = (
        "SELECT * FROM read_parquet('" + parquet_glob.replace("'", "''")
        + "', hive_partitioning=true, union_by_name=true)"
    )
    if args.fecha_dato:
        sql += " WHERE fecha_dato = '" + args.fecha_dato + "'"
    sql += f" LIMIT {args.limit}"
    rows = con.execute(sql).fetchdf()
    con.close()
    if rows.empty:
        raise SystemExit("No Gold rows found for that S3 prefix/month")

    records = []
    for row in rows.to_dict(orient="records"):
        features = {str(key): json_value(value) for key, value in row.items()}
        records.append({
            "ncodpers": json_value(row.get("ncodpers")),
            "fecha_dato": json_value(row.get("fecha_dato")),
            "features": features,
        })

    for start in range(0, len(records), 100):
        result = request_recommendations(
            args.api_url, args.token, records[start:start + 100]
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
