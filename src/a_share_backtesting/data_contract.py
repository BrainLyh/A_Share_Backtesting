from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_BAR_COLUMNS = {
    "date",
    "code",
    "name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "market_cap",
    "is_st",
    "is_suspended",
}
PRICE_COLUMNS = ("open", "high", "low", "close")
ALLOWED_VARIANTS = {"legacy", "bbi", "b1"}
TECHNICAL_ONLY_SCOPE = "technical_only_no_historical_market_cap_or_st"


def normalize_daily_bars(frame: pd.DataFrame, require_core_pool: bool) -> pd.DataFrame:
    """Validate and normalize a local, point-in-time daily-bar data set."""
    missing = REQUIRED_BAR_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data["code"] = data["code"].astype(str).str.strip().str.zfill(6)
    if require_core_pool and "in_core_pool" not in data.columns:
        raise ValueError("in_core_pool is required when require_core_pool is true")
    if "in_core_pool" not in data.columns:
        data["in_core_pool"] = True
    if require_core_pool and data["in_core_pool"].isna().any():
        raise ValueError("in_core_pool contains missing values while require_core_pool is true")

    numeric_columns = [*PRICE_COLUMNS, "volume", "market_cap"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="raise")
    if not np.isfinite(data[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("Daily-bar numeric columns must be finite")
    if (data[list(PRICE_COLUMNS)] <= 0).any().any():
        raise ValueError("Daily-bar prices must be positive")
    if (data["volume"] < 0).any() or (data["market_cap"] < 0).any():
        raise ValueError("volume and market_cap must be non-negative")
    if data.duplicated(["date", "code"]).any():
        raise ValueError("Daily bars contain duplicate date and code rows")
    return data.sort_values(["code", "date"]).reset_index(drop=True)


def _positive_ints(values: object) -> bool:
    return isinstance(values, Iterable) and not isinstance(values, (str, bytes)) and all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in values
    )


def validate_event_config(config: dict[str, Any]) -> None:
    """Reject incomplete or ambiguous event-study parameter sets before a run."""
    required = {
        "analysis_start",
        "analysis_end",
        "variants",
        "horizons",
        "event_notional",
        "control_iterations",
        "random_seed",
    }
    missing = required - set(config)
    if missing:
        raise ValueError(f"Missing configuration keys: {', '.join(sorted(missing))}")
    start = pd.Timestamp(config["analysis_start"])
    end = pd.Timestamp(config["analysis_end"])
    if start > end:
        raise ValueError("analysis_start must not be after analysis_end")
    variants = config["variants"]
    if not isinstance(variants, list) or not variants or not set(variants).issubset(ALLOWED_VARIANTS):
        raise ValueError("variants must be a non-empty list containing only legacy, bbi, and b1")
    if len(set(variants)) != len(variants):
        raise ValueError("variants must not contain duplicates")
    if not _positive_ints(config["horizons"]):
        raise ValueError("horizons must be a non-empty list of positive integers")
    for key in ("event_notional", "control_iterations", "random_seed"):
        value = config[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{key} must be positive")


def validate_technical_only_config(config: dict[str, Any]) -> None:
    """Reject filters that cannot be supported by imported technical-only bars."""
    if config.get("data_scope_label") != TECHNICAL_ONLY_SCOPE:
        return
    if config.get("min_market_cap") != 0:
        raise ValueError("technical-only data requires min_market_cap to be 0")
    if config.get("price_adjustment") != "unadjusted":
        raise ValueError("technical-only data requires price_adjustment to be unadjusted")
