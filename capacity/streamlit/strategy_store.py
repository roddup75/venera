"""Persistent strategy definitions for the Streamlit dashboard."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from capacity_model import ADV_POINTS, BUCKETS, LIVE, calibrate_orders


STORE_PATH = Path(__file__).resolve().parent / "data" / "strategies.user.json"
BUCKET_COLUMNS = [
    "label", "lower", "upper", "p", "share", "cost", "realised", "trades", "valueUsdMillion",
]
ADV_COLUMNS = ["percentile", "advUsd"]

DEFAULT_PARAMETERS: dict[str, Any] = {
    "engine_name": "ADV-calibrated migration",
    "aum0": 3.4,
    "gross_alpha": 0.5,
    "tracking_error": 1.3,
    "turnover": 13.9,
    "holdings": 40,
    "universe_size": 203,
    "max_aum": 15.0,
    "daily": 10.0,
    "max_days": 10,
    "half_life": 10.0,
    "adv_volume": 100.0,
    "liquidity_deterioration": 0.0,
    "preference_label": "Neutral prior",
    "eta": 0.85,
    "kappa": 0.0,
    "minimum_ir": 0.4,
    "retained_threshold": 80.0,
    "regulatory_aum": None,
    "competition_aum": None,
    "burr_c": float(LIVE["calibration"]["burrC"]),
    "burr_d": float(LIVE["calibration"]["burrD"]),
    "burr_scale": float(LIVE["calibration"]["burrScale"]),
    "impact_a": float(LIVE["calibration"]["impactA"]),
    "impact_b": float(LIVE["calibration"]["impactB"]),
    "impact_gamma": float(LIVE["calibration"]["impactGamma"]),
}


def default_strategy() -> dict[str, Any]:
    return {
        "name": "Swiss Strategy",
        "parameters": deepcopy(DEFAULT_PARAMETERS),
        "buckets": BUCKETS[BUCKET_COLUMNS].to_dict("records"),
        "adv_points": ADV_POINTS[ADV_COLUMNS].to_dict("records"),
    }


def load_strategies(path: Path = STORE_PATH) -> dict[str, dict[str, Any]]:
    strategies = {"Swiss Strategy": default_strategy()}
    if path.exists():
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Strategy file must contain a JSON object.")
        for name, strategy in payload.items():
            strategy["parameters"] = {**DEFAULT_PARAMETERS, **strategy.get("parameters", {})}
            validate_strategy(name, strategy["parameters"], strategy.get("buckets", []), strategy.get("adv_points", []))
            strategies[name] = strategy
    return strategies


def _finite(frame: pd.DataFrame, columns: list[str]) -> bool:
    try:
        return frame[columns].apply(pd.to_numeric, errors="raise").map(math.isfinite).all().all()
    except (KeyError, TypeError, ValueError):
        return False


def validate_strategy(name: str, parameters: dict, buckets: list[dict], adv_points: list[dict]) -> None:
    if not name.strip():
        raise ValueError("Strategy name is required.")
    missing_parameters = [key for key in DEFAULT_PARAMETERS if key not in parameters]
    if missing_parameters:
        raise ValueError("Missing strategy parameters: " + ", ".join(missing_parameters))
    if int(parameters["universe_size"]) < 2:
        raise ValueError("Trading-universe size must be at least two stocks.")
    if int(parameters["holdings"]) > int(parameters["universe_size"]):
        raise ValueError("Average holdings cannot exceed the trading-universe size.")

    bucket_frame = pd.DataFrame(buckets)
    if bucket_frame.empty or any(column not in bucket_frame for column in BUCKET_COLUMNS):
        raise ValueError("Liquidity buckets must include all required columns.")
    numeric_bucket_columns = [column for column in BUCKET_COLUMNS if column != "label"]
    if not _finite(bucket_frame, numeric_bucket_columns):
        raise ValueError("Liquidity bucket values must be numeric and finite.")
    if (bucket_frame["upper"] <= bucket_frame["lower"]).any():
        raise ValueError("Every bucket upper bound must exceed its lower bound.")
    if (bucket_frame[["trades", "valueUsdMillion"]] <= 0).any().any():
        raise ValueError("Every bucket requires positive parent-order counts and traded value.")
    if (bucket_frame["upper"].diff().dropna() <= 0).any():
        raise ValueError("Liquidity buckets must be ordered by increasing upper bound.")

    adv_frame = pd.DataFrame(adv_points)
    if len(adv_frame) < 2 or any(column not in adv_frame for column in ADV_COLUMNS):
        raise ValueError("The ADV distribution requires at least two percentile points.")
    if not _finite(adv_frame, ADV_COLUMNS):
        raise ValueError("ADV percentile values must be numeric and finite.")
    if (adv_frame["advUsd"] <= 0).any() or (adv_frame["percentile"] < 0).any() or (adv_frame["percentile"] > 100).any():
        raise ValueError("ADV must be positive and percentiles must lie between 0 and 100.")
    if (adv_frame["percentile"].diff().dropna() <= 0).any() or (adv_frame["advUsd"].diff().dropna() <= 0).any():
        raise ValueError("ADV percentile points and values must increase strictly.")
    try:
        calibrate_orders(0.0, bucket_frame, adv_frame, int(parameters["universe_size"]))
    except ValueError as error:
        raise ValueError(f"Liquidity buckets cannot be reconciled with the ADV distribution: {error}") from error


def save_strategy(
    name: str,
    parameters: dict[str, Any],
    buckets: pd.DataFrame,
    adv_points: pd.DataFrame,
    path: Path = STORE_PATH,
) -> None:
    clean_name = name.strip()
    bucket_records = buckets[BUCKET_COLUMNS].to_dict("records")
    adv_records = adv_points[ADV_COLUMNS].to_dict("records")
    validate_strategy(clean_name, parameters, bucket_records, adv_records)
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text())
    existing[clean_name] = {
        "name": clean_name,
        "parameters": parameters,
        "buckets": bucket_records,
        "adv_points": adv_records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(existing, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
