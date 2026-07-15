from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .indicators import add_grouped_indicators


MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002")


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _main_board(code: pd.Series) -> pd.Series:
    return code.astype(str).str.zfill(6).str.startswith(MAIN_BOARD_PREFIXES)


def _configured_universe(code: pd.Series, config: dict[str, Any]) -> pd.Series:
    stock_pool_codes = config.get("stock_pool_codes")
    if stock_pool_codes:
        normalized_codes = {str(pool_code).strip().zfill(6) for pool_code in stock_pool_codes if str(pool_code).strip()}
        return code.astype(str).str.zfill(6).isin(normalized_codes)
    return _main_board(code)


def build_signals(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    data = add_grouped_indicators(frame)
    data["code"] = data["code"].astype(str).str.zfill(6)
    data["is_st"] = _as_bool(data["is_st"])
    data["is_suspended"] = _as_bool(data["is_suspended"])
    data["in_core_pool"] = _as_bool(data["in_core_pool"])
    name_is_st = data["name"].fillna("").astype(str).str.contains(r"\*?ST", flags=re.IGNORECASE, regex=True)
    eligibility = _configured_universe(data["code"], config) & ~data["is_st"] & ~name_is_st
    min_market_cap = float(config["min_market_cap"])
    if min_market_cap > 0:
        eligibility &= data["market_cap"] > min_market_cap
    if config["require_core_pool"]:
        eligibility &= data["in_core_pool"]
    data["eligible"] = eligibility

    prior_volume = data.groupby("code", sort=False)["volume"].shift(1)
    prior_bbi = data.groupby("code", sort=False)["bbi"].shift(1)
    prior_j = data.groupby("code", sort=False)["j"].shift(1)
    prior_close = data.groupby("code", sort=False)["close"].shift(1)
    prior_k = data.groupby("code", sort=False)["k"].shift(1)
    prior_d = data.groupby("code", sort=False)["d"].shift(1)
    prior_j_below_threshold = prior_j < float(config["j_threshold"])

    data["legacy_pullback_signal"] = (
        eligibility
        & (data["j"] < float(config["j_threshold"]))
        & (data["dif"] > 0)
        & (data["volume"] < prior_volume)
    )
    above_bbi = data["close"] > data["bbi"]
    j_turns_up = (data["j"] > prior_j) & prior_j_below_threshold
    right_side = (
        (data["close"] > data["open"])
        & (data["volume"] >= data["volume_ma"] * float(config["volume_multiplier"]))
        & ((prior_close <= prior_bbi) | (data["close"] > data["bbi"]))
    )
    data["b1_entry_signal"] = eligibility & above_bbi & j_turns_up & right_side & (data["dif"] > 0)
    data["b1_exit_signal"] = (
        ((data["close"] < data["bbi"]) & (prior_close >= prior_bbi))
        | ((data["j"] >= 85) & (data["k"] < data["d"]) & (prior_k >= prior_d))
    )
    data["signal_strength"] = (data["j"] - prior_j).fillna(0) + (data["volume"] / data["volume_ma"]).fillna(0)
    return data


def build_signal_variants(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Add frozen event-study variants and their first-in-run trigger markers."""
    data = build_signals(frame, config)
    groups = data.groupby("code", sort=False)
    prior_bbi = groups["bbi"].shift(1)
    prior_j = groups["j"].shift(1)
    prior_j_below_threshold = prior_j < float(config["j_threshold"])
    above_bbi = data["close"] > data["bbi"]

    data["legacy_signal"] = data["legacy_pullback_signal"]
    trend = above_bbi & (data["bbi"] > prior_bbi)
    data["bbi_signal"] = data["legacy_signal"] & trend
    data["b1_signal"] = (
        data["eligible"]
        & above_bbi
        & (data["dif"] > 0)
        & prior_j_below_threshold
        & (data["j"] > prior_j)
        & (data["close"] > data["open"])
        & (data["volume"] >= data["volume_ma"] * float(config["volume_multiplier"]))
    )
    for variant in ("legacy", "bbi", "b1"):
        previous = groups[f"{variant}_signal"].shift(1).fillna(False).astype(bool)
        data[f"{variant}_first_trigger"] = data[f"{variant}_signal"] & ~previous
    return data
