from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from .intraday_execution import (
    ExecutionConfig,
    Fill,
    PendingExit,
    Position,
    commission,
    entry_fill,
    process_exit_bar,
)
from .intraday_signals import scan_intraday_b1, select_scheme_a_candidates
from .signals import build_signals


CandidateProvider = Callable[[pd.Timestamp, set[str]], pd.DataFrame]


@dataclass
class PortfolioResult:
    scans: pd.DataFrame
    candidates: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    nav_5m: pd.DataFrame
    nav_daily: pd.DataFrame
    rejections: pd.DataFrame
    data_audit: pd.DataFrame
    open_positions: dict[str, Position] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "PortfolioResult":
        return cls(*(pd.DataFrame() for _ in range(10)), open_positions={})


def _records(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _fill_record(fill: Fill, position_id: str) -> dict[str, object]:
    return {"position_id": position_id, **asdict(fill)}


def _bar_at(day: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, object] | None:
    row = day.loc[pd.to_datetime(day["timestamp"]).eq(timestamp)]
    return None if row.empty else row.iloc[-1].to_dict()


def _adjusted_value(position: Position, bar: Mapping[str, object], price_column: str = "close") -> float:
    scale = float(bar.get("qfq_scale", 1.0))
    adjusted_price = float(bar.get(f"qfq_{price_column}", float(bar[price_column]) * scale))
    economic_units = position.remaining_shares / position.entry_qfq_scale
    return economic_units * adjusted_price


def _economic_sell_fill(fill: Fill, position: Position, bar: Mapping[str, object], config: ExecutionConfig) -> Fill:
    scale_ratio = float(bar.get("qfq_scale", 1.0)) / position.entry_qfq_scale
    gross = fill.gross_notional * scale_ratio
    fee = commission(gross, config)
    tax = round(gross * config.sell_stamp_duty_rate, 2)
    return replace(
        fill,
        gross_notional=gross,
        commission=fee,
        stamp_duty=tax,
        slippage_cost=fill.slippage_cost * scale_ratio,
        cash_delta=gross - fee - tax,
    )


def _full_daily_b1_states(daily_by_code: Mapping[str, pd.DataFrame], config: dict[str, Any]) -> dict[str, pd.Series]:
    states: dict[str, pd.Series] = {}
    for code, frame in daily_by_code.items():
        signals = build_signals(frame.copy(), config)
        states[code] = signals.set_index(pd.to_datetime(signals["date"]))["b1_entry_signal"].astype(bool)
    return states


def _prior_state(states: pd.Series, date: pd.Timestamp) -> bool:
    prior = states.loc[states.index < date]
    return bool(prior.iloc[-1]) if not prior.empty else False


def _default_candidates(
    date: pd.Timestamp,
    held_codes: set[str],
    daily_by_code: Mapping[str, pd.DataFrame],
    minute_days: Mapping[str, pd.DataFrame],
    signal_config: dict[str, Any],
    daily_states: Mapping[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scan_frames: list[pd.DataFrame] = []
    prior_states: dict[str, bool] = {}
    for code in sorted(minute_days):
        daily = daily_by_code.get(code)
        minute_day = minute_days[code]
        if daily is None or daily.empty or minute_day.empty:
            continue
        scale_rows = daily.loc[pd.to_datetime(daily["date"]).eq(date), "qfq_scale"]
        if scale_rows.empty:
            continue
        scans = scan_intraday_b1(daily, minute_day, signal_config, qfq_scale=float(scale_rows.iloc[-1]))
        scans["qfq_scale"] = float(scale_rows.iloc[-1])
        scan_frames.append(scans)
        prior_states[code] = _prior_state(daily_states[code], date)
    all_scans = pd.concat(scan_frames, ignore_index=True) if scan_frames else pd.DataFrame()
    selected = select_scheme_a_candidates(all_scans, prior_states, held_codes) if not all_scans.empty else pd.DataFrame()
    return all_scans, selected


def _drawdown(values: pd.Series, peaks: pd.Series | None = None) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return float("nan")
    reference = numeric.cummax() if peaks is None else pd.to_numeric(peaks, errors="coerce").reindex(numeric.index).cummax()
    return float((numeric / reference - 1.0).min())


def run_intraday_portfolio(
    daily_by_code: Mapping[str, pd.DataFrame],
    minute_by_code: Mapping[str, pd.DataFrame],
    signal_config: dict[str, Any],
    execution_config: ExecutionConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    candidate_provider: CandidateProvider | None = None,
) -> PortfolioResult:
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    daily = {str(code).zfill(6): frame.sort_values("date").reset_index(drop=True) for code, frame in daily_by_code.items()}
    minutes = {str(code).zfill(6): frame.sort_values("timestamp").reset_index(drop=True) for code, frame in minute_by_code.items()}
    all_dates = sorted(
        {
            pd.Timestamp(date).normalize()
            for frame in minutes.values()
            for date in pd.to_datetime(frame["date"]).unique()
            if start <= pd.Timestamp(date).normalize() <= end
        }
    )
    daily_states = _full_daily_b1_states(daily, signal_config) if candidate_provider is None else {}
    cash = float(execution_config.initial_cash)
    open_positions: dict[str, Position] = {}
    pending: dict[str, list[PendingExit]] = {}
    expiry_dates: dict[str, pd.Timestamp | None] = {}
    entry_fills: dict[str, Fill] = {}
    sell_fills: dict[str, list[Fill]] = {}
    last_bars: dict[str, dict[str, object]] = {}
    scan_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, object]] = []
    nav_rows: list[dict[str, object]] = []

    date_index = {date: index for index, date in enumerate(all_dates)}
    for date in all_dates:
        minute_days = {
            code: frame.loc[pd.to_datetime(frame["date"]).eq(date)].copy()
            for code, frame in minutes.items()
            if pd.to_datetime(frame["date"]).eq(date).any()
        }
        timestamps = sorted({pd.Timestamp(ts) for frame in minute_days.values() for ts in pd.to_datetime(frame["timestamp"])})
        day_candidates: pd.DataFrame | None = None
        for timestamp in timestamps:
            newly_entered: set[str] = set()
            for code in sorted(list(open_positions)):
                raw_bar = _bar_at(minute_days.get(code, pd.DataFrame()), timestamp) if code in minute_days else None
                if raw_bar is None:
                    continue
                last_bars[code] = raw_bar
                position = open_positions[code]
                current_scale = float(raw_bar.get("qfq_scale", 1.0))
                execution_bar = dict(raw_bar)
                execution_bar["volume"] = int(float(raw_bar["volume"]) * position.entry_qfq_scale / current_scale)
                execution_bar["is_expiry_close"] = bool(
                    expiry_dates.get(position.position_id) == date and timestamp.strftime("%H:%M") == "15:00"
                )
                result = process_exit_bar(position, pending.get(position.position_id, []), execution_bar, execution_config)
                for reason in result.rejections:
                    rejection_rows.append({"timestamp": timestamp, "code": code, "side": "sell", "reason": reason})
                for raw_fill in result.fills:
                    fill = _economic_sell_fill(raw_fill, position, raw_bar, execution_config)
                    cash += fill.cash_delta
                    fill_rows.append(_fill_record(fill, position.position_id))
                    order_rows.append(
                        {"timestamp": timestamp, "code": code, "side": "sell", "reason": fill.reason, "status": "filled"}
                    )
                    sell_fills.setdefault(position.position_id, []).append(fill)
                open_positions[code] = result.position
                pending[position.position_id] = result.pending
                if result.position.remaining_shares <= 0:
                    buy = entry_fills[position.position_id]
                    exits = sell_fills.get(position.position_id, [])
                    proceeds = sum(fill.cash_delta for fill in exits)
                    entry_cost = -buy.cash_delta
                    exit_date = exits[-1].timestamp.normalize() if exits else timestamp.normalize()
                    trade_rows.append(
                        {
                            "position_id": position.position_id,
                            "code": code,
                            "entry_timestamp": position.entry_timestamp,
                            "exit_timestamp": exits[-1].timestamp if exits else timestamp,
                            "status": "closed",
                            "exit_reason": exits[-1].reason if exits else "unknown",
                            "entry_cost": entry_cost,
                            "net_proceeds": proceeds,
                            "net_pnl": proceeds - entry_cost,
                            "net_return": proceeds / entry_cost - 1.0,
                            "holding_days": date_index.get(exit_date, 0) - date_index.get(position.entry_date, 0),
                        }
                    )
                    del open_positions[code]
                    pending.pop(position.position_id, None)

            time_label = timestamp.strftime("%H:%M")
            if time_label == "14:55":
                if candidate_provider is None:
                    scans, day_candidates = _default_candidates(
                        date, set(open_positions), daily, minute_days, signal_config, daily_states
                    )
                    scan_rows.extend(scans.to_dict("records"))
                else:
                    day_candidates = candidate_provider(date, set(open_positions))
                if day_candidates is None:
                    day_candidates = pd.DataFrame()
                if not day_candidates.empty:
                    day_candidates = day_candidates.copy()
                    day_candidates["code"] = day_candidates["code"].astype(str).str.zfill(6)
                    candidate_rows.extend(day_candidates.to_dict("records"))
                market_value = sum(
                    _adjusted_value(position, last_bars[code])
                    for code, position in open_positions.items()
                    if code in last_bars
                )
                pre_entry_nav = cash + market_value
                for _, candidate in day_candidates.iterrows() if not day_candidates.empty else []:
                    code = str(candidate["code"]).zfill(6)
                    if code in open_positions:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "position_already_open"})
                        continue
                    if len(open_positions) >= execution_config.max_positions:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "capacity"})
                        continue
                    day = minute_days.get(code)
                    raw_bar = _bar_at(day, timestamp) if day is not None else None
                    if raw_bar is None:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "missing_entry_bar"})
                        continue
                    last_bars[code] = raw_bar
                    entry_candidate = candidate.to_dict()
                    entry_candidate["qfq_scale"] = float(raw_bar.get("qfq_scale", 1.0))
                    result = entry_fill(entry_candidate, raw_bar, pre_entry_nav, cash, execution_config)
                    order_rows.append(
                        {
                            "timestamp": timestamp,
                            "code": code,
                            "side": "buy",
                            "reason": "entry",
                            "status": "rejected" if result.rejection else "filled",
                        }
                    )
                    if result.rejection is not None or result.position is None or result.fill is None:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": result.rejection})
                        continue
                    cash += result.fill.cash_delta
                    if cash < -0.01:
                        raise ValueError("cash reconciliation failed: negative cash")
                    open_positions[code] = result.position
                    pending[result.position.position_id] = []
                    horizon_index = date_index[date] + execution_config.horizon_days
                    expiry_dates[result.position.position_id] = all_dates[horizon_index] if horizon_index < len(all_dates) else None
                    entry_fills[result.position.position_id] = result.fill
                    sell_fills[result.position.position_id] = []
                    fill_rows.append(_fill_record(result.fill, result.position.position_id))
                    newly_entered.add(code)

            for code, day in minute_days.items():
                current_bar = _bar_at(day, timestamp)
                if current_bar is not None:
                    last_bars[code] = current_bar
            marked = 0.0
            marked_low = 0.0
            for code, position in open_positions.items():
                current_bar = last_bars.get(code)
                if current_bar is None:
                    continue
                marked += _adjusted_value(position, current_bar, "close")
                low_column = "close" if code in newly_entered else "low"
                marked_low += _adjusted_value(position, current_bar, low_column)
                position_rows.append(
                    {
                        "timestamp": timestamp,
                        "position_id": position.position_id,
                        "code": code,
                        "remaining_shares": position.remaining_shares,
                        "market_value": _adjusted_value(position, current_bar, "close"),
                    }
                )
            nav = cash + marked
            if cash < -0.01 or not np.isfinite(nav):
                raise ValueError("cash or NAV invariant failed")
            nav_rows.append(
                {
                    "timestamp": timestamp,
                    "date": date,
                    "cash": cash,
                    "gross_exposure": marked,
                    "positions": len(open_positions),
                    "nav": nav,
                    "nav_low": cash + marked_low,
                }
            )

    nav_5m = _records(nav_rows)
    nav_daily = (
        nav_5m.sort_values("timestamp").groupby("date", as_index=False).tail(1).reset_index(drop=True)
        if not nav_5m.empty
        else pd.DataFrame()
    )
    for code, position in open_positions.items():
        buy = entry_fills[position.position_id]
        exits = sell_fills.get(position.position_id, [])
        proceeds = sum(fill.cash_delta for fill in exits)
        marked = _adjusted_value(position, last_bars[code]) if code in last_bars else 0.0
        entry_cost = -buy.cash_delta
        trade_rows.append(
            {
                "position_id": position.position_id,
                "code": code,
                "entry_timestamp": position.entry_timestamp,
                "exit_timestamp": pd.NaT,
                "status": "open",
                "exit_reason": "open_at_end",
                "entry_cost": entry_cost,
                "net_proceeds": proceeds,
                "net_pnl": proceeds + marked - entry_cost,
                "net_return": (proceeds + marked) / entry_cost - 1.0,
                "holding_days": date_index.get(all_dates[-1], 0) - date_index.get(position.entry_date, 0) if all_dates else 0,
            }
        )
    return PortfolioResult(
        scans=_records(scan_rows),
        candidates=_records(candidate_rows),
        orders=_records(order_rows),
        fills=_records(fill_rows),
        positions=_records(position_rows),
        trades=_records(trade_rows),
        nav_5m=nav_5m,
        nav_daily=nav_daily,
        rejections=_records(rejection_rows),
        data_audit=pd.DataFrame(),
        open_positions=dict(open_positions),
    )


def summarize_portfolio(result: PortfolioResult, initial_cash: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if result.nav_5m.empty:
        portfolio = pd.DataFrame([{"initial_cash": initial_cash, "total_net_return": float("nan")}])
    else:
        nav = result.nav_5m["nav"].astype(float)
        close_peaks = nav.cummax()
        fills = result.fills if not result.fills.empty else pd.DataFrame()
        gross = float(fills["gross_notional"].sum()) if "gross_notional" in fills else 0.0
        commission_cost = float(fills["commission"].sum()) if "commission" in fills else 0.0
        stamp_cost = float(fills["stamp_duty"].sum()) if "stamp_duty" in fills else 0.0
        slippage_cost = float(fills["slippage_cost"].sum()) if "slippage_cost" in fills else 0.0
        exposure = result.nav_5m["gross_exposure"].astype(float) / nav.replace(0, np.nan)
        portfolio = pd.DataFrame(
            [
                {
                    "initial_cash": initial_cash,
                    "final_nav": float(nav.iloc[-1]),
                    "total_net_return": float(nav.iloc[-1] / initial_cash - 1.0),
                    "max_drawdown_5m": _drawdown(nav),
                    "max_drawdown_low": _drawdown(result.nav_5m["nav_low"].astype(float), close_peaks),
                    "max_drawdown_daily": _drawdown(result.nav_daily["nav"].astype(float)),
                    "average_exposure": float(exposure.mean()),
                    "max_exposure": float(exposure.max()),
                    "max_positions": int(result.nav_5m["positions"].max()),
                    "turnover": gross / initial_cash,
                    "commission": commission_cost,
                    "stamp_duty": stamp_cost,
                    "slippage_cost": slippage_cost,
                }
            ]
        )
    trades = result.trades if not result.trades.empty else pd.DataFrame()
    closed = trades.loc[trades["status"].eq("closed")].copy() if "status" in trades else pd.DataFrame()
    wins = closed.loc[closed["net_pnl"] > 0, "net_pnl"] if not closed.empty else pd.Series(dtype=float)
    losses = closed.loc[closed["net_pnl"] < 0, "net_pnl"] if not closed.empty else pd.Series(dtype=float)
    trade = pd.DataFrame(
        [
            {
                "closed_trade_count": int(len(closed)),
                "open_trade_count": int((trades["status"] == "open").sum()) if "status" in trades else 0,
                "win_rate": float((closed["net_pnl"] > 0).mean()) if not closed.empty else float("nan"),
                "mean_net_return": float(closed["net_return"].mean()) if not closed.empty else float("nan"),
                "median_net_return": float(closed["net_return"].median()) if not closed.empty else float("nan"),
                "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else float("inf") if not wins.empty else float("nan"),
                "payoff_ratio": float(wins.mean() / abs(losses.mean())) if not wins.empty and not losses.empty else float("nan"),
                "expectancy": float(closed["net_pnl"].mean()) if not closed.empty else float("nan"),
                "average_holding_days": float(closed["holding_days"].mean()) if not closed.empty else float("nan"),
            }
        ]
    )
    return portfolio, trade
