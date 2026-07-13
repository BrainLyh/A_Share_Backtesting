from __future__ import annotations

import numpy as np
import pandas as pd


def tdx_sma(values: pd.Series, period: int, weight: int = 1) -> pd.Series:
    """Tongdaxin SMA(X, N, M): (M*X + (N-M)*previous) / N."""
    result = np.full(len(values), np.nan, dtype=float)
    for index, value in enumerate(values.astype(float).to_numpy()):
        if not np.isfinite(value):
            continue
        if index == 0 or not np.isfinite(result[index - 1]):
            result[index] = value
        else:
            result[index] = (weight * value + (period - weight) * result[index - 1]) / period
    return pd.Series(result, index=values.index)


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.sort_values(["code", "date"]).copy()
    low_9 = data["low"].rolling(9, min_periods=9).min()
    high_9 = data["high"].rolling(9, min_periods=9).max()
    denominator = high_9 - low_9
    data["rsv"] = ((data["close"] - low_9) / denominator * 100).where(denominator.ne(0), 50.0)
    data["k"] = tdx_sma(data["rsv"], 3, 1)
    data["d"] = tdx_sma(data["k"], 3, 1)
    data["j"] = 3 * data["k"] - 2 * data["d"]
    data["dif"] = data["close"].ewm(span=12, adjust=False).mean() - data["close"].ewm(span=26, adjust=False).mean()
    data["dea"] = data["dif"].ewm(span=9, adjust=False).mean()
    data["bbi"] = (
        data["close"].rolling(3, min_periods=3).mean()
        + data["close"].rolling(6, min_periods=6).mean()
        + data["close"].rolling(12, min_periods=12).mean()
        + data["close"].rolling(24, min_periods=24).mean()
    ) / 4
    data["volume_ma"] = data["volume"].rolling(5, min_periods=5).mean()
    return data


def add_grouped_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    groups = [add_indicators(group) for _, group in frame.groupby("code", sort=False)]
    return pd.concat(groups, ignore_index=True) if groups else frame.copy()
