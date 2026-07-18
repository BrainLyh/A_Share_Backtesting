from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from typing import Any

import pandas as pd

from .indicators import add_atr14
from .signals import build_signals


SCAN_TIMES = ("14:40", "14:45", "14:50")
_SCAN_ORDER = {time: index for index, time in enumerate(SCAN_TIMES)}


def build_provisional_daily_bar(minute_day: pd.DataFrame, scan_time: str, qfq_scale: float) -> dict[str, object]:
    """Aggregate only completed five-minute bars into a qfq provisional daily bar."""
    if not math.isfinite(float(qfq_scale)) or float(qfq_scale) <= 0:
        raise ValueError("qfq_scale must be finite and positive")
    data = minute_day.sort_values("timestamp").copy()
    if data.empty or data["code"].astype(str).nunique() != 1 or pd.to_datetime(data["date"]).nunique() != 1:
        raise ValueError("minute_day must contain one non-empty code-date group")
    visible = data.loc[data["time"].astype(str) <= str(scan_time)]
    if visible.empty or str(scan_time) not in set(visible["time"].astype(str)):
        raise ValueError(f"missing completed scan bar {scan_time}")
    scale = float(qfq_scale)
    first = visible.iloc[0]
    last = visible.iloc[-1]
    return {
        "date": pd.Timestamp(last["date"]).normalize(),
        "code": str(last["code"]).zfill(6),
        "open": float(first["open"]) * scale,
        "high": float(visible["high"].max()) * scale,
        "low": float(visible["low"].min()) * scale,
        "close": float(last["close"]) * scale,
        "volume": int(visible["volume"].sum()),
    }


def _indicator_input(history: pd.DataFrame, provisional: dict[str, object]) -> pd.DataFrame:
    code = str(provisional["code"])
    date = pd.Timestamp(provisional["date"])
    data = history.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.loc[(data["code"].astype(str).str.zfill(6) == code) & (data["date"] < date)].copy()
    row: dict[str, Any] = {
        **provisional,
        "name": code,
        "market_cap": 0,
        "is_st": False,
        "is_suspended": False,
        "in_core_pool": False,
    }
    for column in ("name", "market_cap", "is_st", "is_suspended", "in_core_pool"):
        if not data.empty and column in data.columns:
            row[column] = data.iloc[-1][column]
    return pd.concat([data, pd.DataFrame([row])], ignore_index=True, sort=False)


def scan_intraday_b1(
    daily_history: pd.DataFrame,
    minute_day: pd.DataFrame,
    config: dict[str, Any],
    *,
    qfq_scale: float,
) -> pd.DataFrame:
    """Evaluate the existing B1 formula at each approved D-day scan time."""
    rows: list[dict[str, object]] = []
    for scan_time in SCAN_TIMES:
        provisional = build_provisional_daily_bar(minute_day, scan_time, qfq_scale)
        signals = add_atr14(build_signals(_indicator_input(daily_history, provisional), config))
        current = signals.iloc[-1]
        prior_j = float(signals.iloc[-2]["j"]) if len(signals) > 1 else float("nan")
        rows.append(
            {
                "date": pd.Timestamp(provisional["date"]),
                "code": str(provisional["code"]),
                "scan_time": scan_time,
                "b1_signal": bool(current["b1_entry_signal"]),
                "eligible": bool(current["eligible"]),
                "signal_strength": float(current["signal_strength"]),
                "j": float(current["j"]),
                "prior_j": prior_j,
                "bbi": float(current["bbi"]),
                "dif": float(current["dif"]),
                "volume": int(provisional["volume"]),
                "volume_ma": float(current["volume_ma"]),
                "atr14": float(current["atr14"]),
            }
        )
    return pd.DataFrame(rows)


def select_scheme_a_candidates(
    scans: pd.DataFrame,
    prior_day_b1: Mapping[str, bool],
    held_codes: Collection[str],
) -> pd.DataFrame:
    """Select persistent first-trigger candidates and apply deterministic ranking."""
    if scans.empty:
        return scans.assign(first_trigger_time=pd.Series(dtype=str))
    held = {str(code).zfill(6) for code in held_codes}
    candidates: list[dict[str, object]] = []
    data = scans.copy()
    data["code"] = data["code"].astype(str).str.zfill(6)
    for (date, code), group in data.groupby(["date", "code"], sort=False):
        true_rows = group.loc[group["b1_signal"].fillna(False).astype(bool)].copy()
        final = group.loc[group["scan_time"].astype(str).eq("14:50")]
        if true_rows.empty or final.empty or not bool(final.iloc[-1]["b1_signal"]):
            continue
        if bool(prior_day_b1.get(code, False)) or code in held:
            continue
        true_rows["_order"] = true_rows["scan_time"].map(_SCAN_ORDER)
        first_trigger_time = str(true_rows.sort_values("_order").iloc[0]["scan_time"])
        row = final.iloc[-1].to_dict()
        row["date"] = pd.Timestamp(date)
        row["code"] = code
        row["first_trigger_time"] = first_trigger_time
        candidates.append(row)
    if not candidates:
        return pd.DataFrame(columns=[*scans.columns, "first_trigger_time"])
    result = pd.DataFrame(candidates)
    result["_first_order"] = result["first_trigger_time"].map(_SCAN_ORDER)
    return (
        result.sort_values(["_first_order", "signal_strength", "code"], ascending=[True, False, True])
        .drop(columns="_first_order")
        .reset_index(drop=True)
    )
