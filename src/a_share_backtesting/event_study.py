from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


EVENT_COLUMNS = [
    "event_id", "code", "variant", "horizon", "signal_date", "entry_date", "exit_date",
    "status", "gross_return", "net_return", "max_adverse_excursion", "close_max_drawdown",
]


def _blocked(row: pd.Series, side: str) -> bool:
    if bool(row["is_suspended"]):
        return True
    limit_column = "upper_limit" if side == "buy" else "lower_limit"
    return limit_column in row.index and pd.notna(row[limit_column]) and (
        row["open"] >= row[limit_column] if side == "buy" else row["open"] <= row[limit_column]
    )


def _unavailable(code: str, variant: str, horizon: int, signal_date: pd.Timestamp, status: str) -> dict[str, Any]:
    return {
        "event_id": f"{code}:{variant}:{horizon}:{signal_date:%Y%m%d}", "code": code,
        "variant": variant, "horizon": horizon, "signal_date": signal_date,
        "entry_date": pd.NaT, "exit_date": pd.NaT, "status": status,
        "gross_return": np.nan, "net_return": np.nan,
        "max_adverse_excursion": np.nan, "close_max_drawdown": np.nan,
    }


def _measure_event(bars: pd.DataFrame, signal_index: int, entry_index: int, exit_index: int, variant: str, horizon: int, config: dict[str, Any]) -> dict[str, Any]:
    signal, entry, exit_row = bars.iloc[signal_index], bars.iloc[entry_index], bars.iloc[exit_index]
    code, signal_date = str(signal["code"]), pd.Timestamp(signal["date"])
    if _blocked(entry, "buy"):
        return _unavailable(code, variant, horizon, signal_date, "unfilled_entry")
    if _blocked(exit_row, "sell"):
        return _unavailable(code, variant, horizon, signal_date, "unfilled_exit")
    entry_price, exit_price = float(entry["open"]), float(exit_row["open"])
    lot = int(config["lot_size"])
    shares = int(float(config["event_notional"]) // entry_price // lot) * lot
    if shares == 0:
        return _unavailable(code, variant, horizon, signal_date, "unfilled_entry")
    buy_value, sell_value = shares * entry_price, shares * exit_price
    buy_fee = max(buy_value * float(config["commission_rate"]), float(config["minimum_commission"]))
    sell_fee = max(sell_value * float(config["commission_rate"]), float(config["minimum_commission"])) + sell_value * float(config["sell_stamp_duty_rate"])
    path = bars.iloc[entry_index : exit_index + 1]
    close_curve = path["close"].astype(float) / entry_price
    return {
        "event_id": f"{code}:{variant}:{horizon}:{signal_date:%Y%m%d}", "code": code,
        "variant": variant, "horizon": horizon, "signal_date": signal_date,
        "entry_date": pd.Timestamp(entry["date"]), "exit_date": pd.Timestamp(exit_row["date"]),
        "status": "filled", "gross_return": sell_value / buy_value - 1,
        "net_return": (sell_value - sell_fee) / (buy_value + buy_fee) - 1,
        "max_adverse_excursion": float(path["low"].min() / entry_price - 1),
        "close_max_drawdown": float((close_curve / close_curve.cummax() - 1).min()),
    }


def measure_events(signals: pd.DataFrame, variant: str, horizon: int, config: dict[str, Any]) -> pd.DataFrame:
    """Measure first-trigger events without overlapping outcomes for the same code."""
    trigger = f"{variant}_first_trigger"
    if trigger not in signals.columns:
        raise ValueError(f"Missing trigger column: {trigger}")
    rows: list[dict[str, Any]] = []
    for code, bars in signals.groupby("code", sort=False):
        bars = bars.sort_values("date").reset_index(drop=True)
        next_allowed = 0
        for signal_index in bars.index[bars[trigger].astype(bool)]:
            if signal_index < next_allowed:
                continue
            entry_index, exit_index = signal_index + 1, signal_index + 1 + horizon
            if exit_index >= len(bars):
                rows.append(_unavailable(str(code), variant, horizon, pd.Timestamp(bars.iloc[signal_index]["date"]), "insufficient_history"))
                continue
            rows.append(_measure_event(bars, signal_index, entry_index, exit_index, variant, horizon, config))
            next_allowed = exit_index + 1
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)
