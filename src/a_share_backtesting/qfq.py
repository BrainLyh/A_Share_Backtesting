from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_QFQ_COLUMNS = {"date", "code", "open", "high", "low", "close", "preclose"}
PRICE_COLUMNS = ("open", "high", "low", "close")


def _adjust_one_code(frame: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    data = frame.sort_values("date").reset_index(drop=True).copy()
    data["raw_prev_close"] = data["close"].shift(1)
    ratio = data["preclose"] / data["raw_prev_close"]
    data["preclose_to_raw_prev_close_ratio"] = ratio
    data["adjustment_jump"] = ratio.notna() & np.isfinite(ratio) & ((ratio - 1.0).abs() > tolerance)
    scale = pd.Series(1.0, index=data.index, dtype=float)
    for index, row in data.iterrows():
        if not bool(row["adjustment_jump"]):
            continue
        scale.loc[: index - 1] *= float(row["preclose_to_raw_prev_close_ratio"])
    data["qfq_scale"] = scale
    for column in PRICE_COLUMNS:
        data[f"qfq_{column}"] = data[column] * data["qfq_scale"]
    data["raw_gap_return"] = data["close"] / data["raw_prev_close"] - 1.0
    data["adjusted_day_return"] = data["close"] / data["preclose"] - 1.0
    return data


def apply_qfq_adjustment(frame: pd.DataFrame, tolerance: float = 0.001) -> pd.DataFrame:
    """Add front-adjusted OHLC and adjustment-audit columns from rustdx preclose data."""
    missing = REQUIRED_QFQ_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required qfq columns: {', '.join(sorted(missing))}")
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data["code"] = data["code"].astype(str).str.strip().str.zfill(6)
    numeric_columns = [*PRICE_COLUMNS, "preclose"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="raise")
    adjusted = [_adjust_one_code(group, tolerance) for _, group in data.groupby("code", sort=False)]
    return pd.concat(adjusted, ignore_index=True) if adjusted else data.copy()
