"""Persistent strategy definitions for the Streamlit dashboard."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from impact_cost import fit_impact_cost
from transfer_coefficient import TransferCoefficientModel, DEFAULT_TC_POINTS
from alpha_decay import AlphaDecayModel, DEFAULT_POINTS
from capacity_model import MIN_AUM, MODEL_VERSION, BUCKETS, annual_cost_from_buckets, validate_buckets, validate_trades


STORE_PATH = Path(__file__).resolve().parent / "data" / "strategies.user.json"
BUCKET_COLUMNS = [
    "label", "lower", "upper", "p", "share", "cost", "realised", "trades", "valueUsdMillion",
]
ADV_COLUMNS = ["percentile", "advUsd"]
IR_COLUMNS = ["aumBn", "ir"]
DEFAULT_IR_POINTS = pd.DataFrame({
    "aumBn": list(range(10)),
    "ir": [0.60, 0.53, 0.47, 0.40, 0.33, 0.27, 0.20, 0.14, 0.07, 0.00],
})

DEFAULT_PARAMETERS: dict[str, Any] = {
    "model_kind": "Three-pillar empirical", "alpha_points": DEFAULT_POINTS, "tc_points": DEFAULT_TC_POINTS,
    "turnover": 13.9, "aum0": 3.4, "gross_alpha": 0.5, "tracking_error": 1.3,
    "max_aum": 15.0, "daily": 20.0, "half_life": 10.0,
    "annual_cost_bps": annual_cost_from_buckets(BUCKETS, 13.9),
    "cost_elasticity": 0.0, "minimum_ir": 0.4, "retained_threshold": 80.0,
    "regulatory_aum": None, "competition_aum": None,
    "calculation_mode": "Deterministic", "mc_samples": 2000, "mc_seed": 2026,
}


def upgrade_parameters(parameters: dict, buckets: list[dict]) -> dict:
    """Preserve old settings as metadata, migrate cost units, retire model selection."""
    result = {**DEFAULT_PARAMETERS, **parameters}
    if "annual_cost_bps" not in parameters:
        result["annual_cost_bps"] = annual_cost_from_buckets(pd.DataFrame(buckets), float(parameters.get("turnover", 13.9)))
    result["engine_name"] = "Execution delay"
    return result


def default_strategy() -> dict[str, Any]:
    return {
        "name": "Swiss Strategy",
        "parameters": deepcopy(DEFAULT_PARAMETERS),
        "buckets": BUCKETS[BUCKET_COLUMNS].to_dict("records"),
        "adv_points": [],
        "ir_points_source": "illustrative-default",
        "ir_points": DEFAULT_IR_POINTS[IR_COLUMNS].to_dict("records"),
    }


def load_strategies(path: Path = STORE_PATH) -> dict[str, dict[str, Any]]:
    strategies = {"Swiss Strategy": default_strategy()}
    if path.exists():
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Strategy file must contain a JSON object.")
        for name, strategy in payload.items():
            strategy["parameters"] = upgrade_parameters(strategy.get("parameters", {}), strategy.get("buckets", []))
            strategy["ir_points_source"] = strategy.get("ir_points_source", "saved" if "ir_points" in strategy else "illustrative-default")
            strategy["ir_points"] = strategy.get(
                "ir_points", DEFAULT_IR_POINTS[IR_COLUMNS].to_dict("records"),
            )
            validate_strategy(
                name, strategy["parameters"], strategy.get("buckets", []),
                strategy.get("adv_points", []), strategy["ir_points"],
                strategy.get("trades"),
            )
            strategies[name] = strategy
    return strategies


def _finite(frame: pd.DataFrame, columns: list[str]) -> bool:
    try:
        return frame[columns].apply(pd.to_numeric, errors="raise").map(math.isfinite).all().all()
    except (KeyError, TypeError, ValueError):
        return False


def validate_strategy(
    name: str,
    parameters: dict,
    buckets: list[dict],
    adv_points: list[dict],
    ir_points: list[dict] | None = None,
    trades: list[dict] | None = None,
) -> None:
    if not name.strip():
        raise ValueError("Strategy name is required.")
    missing_parameters = [key for key in DEFAULT_PARAMETERS if key not in parameters]
    if missing_parameters:
        raise ValueError("Missing strategy parameters: " + ", ".join(missing_parameters))
    numeric_parameters = [key for key in DEFAULT_PARAMETERS if key not in ("regulatory_aum", "competition_aum", "calculation_mode", "model_kind", "alpha_points", "tc_points")]
    if any(not isinstance(parameters[key], (int, float)) or not math.isfinite(parameters[key]) for key in numeric_parameters):
        raise ValueError("Model parameters must be finite numbers.")
    if parameters["model_kind"] not in ("Three-pillar empirical", "Execution delay", "Calibrated alpha decay", "Calibrated transfer coefficient"):
        raise ValueError("Unknown capacity model.")
    tc = TransferCoefficientModel(parameters["tc_points"], parameters["tracking_error"])
    if parameters["model_kind"] == "Calibrated transfer coefficient" and parameters["aum0"] > tc.maximum:
        raise ValueError("Current AUM exceeds the zero-TC boundary.")
    alpha = AlphaDecayModel(parameters["alpha_points"], parameters["tracking_error"])
    if parameters["model_kind"] == "Three-pillar empirical":
        if parameters["alpha_points"][0][2]<=0 or parameters["tc_points"][0][2]<=0:
            raise ValueError("Combined retention factors require positive initial IR and TC alpha.")
    if parameters["model_kind"] == "Calibrated alpha decay" and parameters["aum0"] > alpha.maximum:
        raise ValueError("Current AUM exceeds the calibrated model's 100% congestion boundary.")
    if parameters["calculation_mode"] not in ("Monte Carlo", "Deterministic"):
        raise ValueError("Unknown calculation mode.")
    for key, lower, upper in (("mc_samples", 2, 20000), ("mc_seed", 0, 2**32-1)):
        if isinstance(parameters[key], bool) or not isinstance(parameters[key], int) or not lower <= parameters[key] <= upper:
            raise ValueError(f"{key} must be an integer in [{lower}, {upper}].")
    for key in ("aum0", "tracking_error", "daily", "half_life"):
        if parameters[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    if parameters["aum0"] < MIN_AUM:
        raise ValueError("Current AUM must be at least $500m.")
    if parameters["daily"] > 100 or parameters["max_aum"] < parameters["aum0"]:
        raise ValueError("Daily participation must not exceed 100%; chart horizon must cover current AUM.")
    if any(parameters[key] < 0 for key in ("gross_alpha", "annual_cost_bps", "cost_elasticity", "minimum_ir", "turnover")):
        raise ValueError("Alpha, costs, elasticity and minimum IR cannot be negative.")
    for key in ("regulatory_aum", "competition_aum"):
        if parameters[key] is not None and (not math.isfinite(parameters[key]) or parameters[key] <= 0):
            raise ValueError("Display-marker AUM must be positive or blank.")
    bucket_frame = pd.DataFrame(buckets)
    if bucket_frame.empty or any(column not in bucket_frame for column in BUCKET_COLUMNS):
        raise ValueError("Liquidity buckets must include all required columns.")
    validate_buckets(bucket_frame)
    if parameters["model_kind"] == "Three-pillar empirical":
        maximum=min(alpha.maximum,tc.maximum)
        for model in (alpha,tc):
            zero=model.capacity(0,maximum)
            if zero is not None:maximum=min(maximum,zero)
        if parameters["aum0"]>maximum:
            raise ValueError("Current AUM exceeds the combined model's nonnegative-retention domain.")
        fit_impact_cost(bucket_frame)
    if trades is not None:
        validate_trades(pd.DataFrame(trades))
    # Legacy universe ADV is preserved for compatibility, not used or calibrated.

    ir_frame = pd.DataFrame(
        DEFAULT_IR_POINTS[IR_COLUMNS].to_dict("records") if ir_points is None else ir_points,
    )
    if len(ir_frame) < 3 or any(column not in ir_frame for column in IR_COLUMNS):
        raise ValueError("The backtest IR curve requires at least three AUM and IR observations.")
    if not _finite(ir_frame, IR_COLUMNS):
        raise ValueError("Backtest AUM and IR values must be numeric and finite.")
    if (ir_frame["aumBn"] < 0).any():
        raise ValueError("Backtest AUM values cannot be negative.")
    if ir_frame["aumBn"].duplicated().any():
        raise ValueError("Backtest AUM values must be unique.")


def save_strategy(
    name: str,
    parameters: dict[str, Any],
    buckets: pd.DataFrame,
    adv_points: pd.DataFrame | None = None,
    path: Path = STORE_PATH,
    ir_points: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
) -> None:
    clean_name = name.strip()
    bucket_records = buckets[BUCKET_COLUMNS].to_dict("records")
    adv_records = [] if adv_points is None else adv_points.reindex(columns=ADV_COLUMNS).to_dict("records")
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text())
    if ir_points is None:
        ir_records = existing.get(clean_name, {}).get(
            "ir_points", DEFAULT_IR_POINTS[IR_COLUMNS].to_dict("records"),
        )
    else:
        ir_records = ir_points[IR_COLUMNS].to_dict("records")
    trade_records = None if trades is None else validate_trades(trades).to_dict("records")
    validate_strategy(clean_name, parameters, bucket_records, adv_records, ir_records, trade_records)
    existing[clean_name] = {
        "name": clean_name,
        "parameters": parameters,
        "buckets": bucket_records,
        "adv_points": adv_records,
        "ir_points": ir_records,
        "ir_points_source": "saved",
        "trades": trade_records,
        "methodology": "three-pillar-empirical-v1" if parameters["model_kind"] == "Three-pillar empirical" else "three-point-tc-v1" if parameters["model_kind"] == "Calibrated transfer coefficient" else "three-point-alpha-decay-v1" if parameters["model_kind"] == "Calibrated alpha decay" else MODEL_VERSION,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(existing, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
